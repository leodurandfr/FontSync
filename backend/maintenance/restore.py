"""Restauration d'un instantané de base, serveur arrêté.

Appelé par `scripts/restore-from-backup.sh` dans un conteneur jetable :
`python -m backend.maintenance.restore /backups/<instantané>.db
[--fonts-from /backups/fonts] [--protect-backups /backups]
[--devices-json /backups/<fichier>.json]` (ou `--check` pour seulement
vérifier l'instantané, avant d'arrêter quoi que ce soit).

Ce que ce module garantit, et qu'un simple `cp` ne garantit pas :

- **Le WAL de l'ancienne base ne se rejoue pas.** Une base SQLite en WAL vit
  dans trois fichiers ; laisser `-wal`/`-shm` à côté de l'instantané posé fait
  rejouer l'ancien journal par-dessus au démarrage : la restauration est
  annulée en silence, `integrity_check` compris.
- **Rien ne s'efface.** La base remplacée et ses annexes sont *déplacées* dans
  `pre-restore-<horodatage>/`, à côté de la base, avec une copie de
  l'instantané restauré ; les instantanés quotidiens existants sont mis à
  l'abri de la rotation (qui tourne à chaque démarrage du serveur) ; les
  polices sont recopiées du miroir sans rien retirer.
- **Aucun Mac ne réagit à l'aveugle.** Avant de poser la base restaurée,
  auto-pull et « Propager les suppressions » y sont coupés sur TOUS les
  appareils (y compris ceux masqués), valeurs d'avant conservées : même un
  `docker compose up -d` prématuré ne réinstalle ni ne propage rien.

Codes de sortie : 0 restaurée ; 1 refusée, base inchangée ; 2 base non
SQLite ; 3 restaurée mais une étape annexe a échoué (polices, copies) ;
4 état incertain (remise en place impossible : voir le dossier indiqué).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.config import settings
from backend.services.backup import mirror_blobs, sqlite_database_path, write_snapshot

# Annexes d'abord, base en dernier : un arrêt brutal entre deux déplacements
# ne laisse jamais un `-wal` orphelin à côté d'une base absente.
_MOVE_ORDER = ("-wal", "-shm", "-journal", "")

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_NOT_SQLITE = 2
EXIT_RESTORED_WITH_WARNINGS = 3
EXIT_UNCERTAIN = 4


class RestoreError(RuntimeError):
    """L'instantané ne peut pas être posé ; la base en place n'a pas bougé."""


class RollbackFailed(RuntimeError):
    """La remise en place a échoué : l'état est à examiner à la main."""

    def __init__(self, aside: Path, cause: BaseException) -> None:
        super().__init__(f"remise en place impossible ({cause}) ; voir {aside}")
        self.aside = aside


@dataclass
class RestoreResult:
    """Ce que la restauration a fait."""

    restored: Path
    set_aside: Path
    moved: tuple[str, ...]
    devices_before: list[dict[str, Any]] = field(default_factory=list)
    protected: Path | None = None
    warnings: list[str] = field(default_factory=list)


def check_snapshot(snapshot: Path) -> str | None:
    """Vérifie un instantané et renvoie sa révision Alembic (None si absente).

    Lecture `immutable` : rien n'est écrit à côté de l'instantané.

    Raises:
        RestoreError: instantané absent, illisible, endommagé ou vide.
    """
    if not snapshot.is_file():
        raise RestoreError(f"instantané introuvable : {snapshot.name}")
    try:
        conn = sqlite3.connect(f"file:{snapshot}?mode=ro&immutable=1", uri=True)
        try:
            verdict = conn.execute("PRAGMA integrity_check").fetchone()[0]
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            revision = None
            if "alembic_version" in tables:
                row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
                revision = row[0] if row else None
        finally:
            conn.close()
    except sqlite3.Error as error:
        raise RestoreError(f"instantané illisible ({error})") from error
    if verdict != "ok":
        raise RestoreError(f"instantané endommagé (integrity_check : {verdict})")
    if not tables:
        raise RestoreError("instantané sans aucune table")
    return revision


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _unique_dir(parent: Path, name: str) -> Path:
    candidate = parent / name
    suffix = 1
    while candidate.exists():
        candidate = parent / f"{name}-{suffix}"
        suffix += 1
    return candidate


def _make_devices_safe(db: Path) -> list[dict[str, Any]]:
    """Coupe auto-pull et propagation sur tous les appareils ; renvoie l'avant."""
    conn = sqlite3.connect(db)
    try:
        conn.execute("PRAGMA journal_mode=DELETE")
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='devices'"
        ).fetchone()
        if not exists:
            return []
        conn.row_factory = sqlite3.Row
        before = [
            dict(row)
            for row in conn.execute(
                "SELECT id, name, auto_pull, auto_push, propagate_deletions, "
                "deleted_at FROM devices"
            )
        ]
        conn.execute("UPDATE devices SET auto_pull = 0, propagate_deletions = 0")
        conn.commit()
        return before
    finally:
        conn.close()


def _protect_backups(backups: Path, stamp: str, keep_out: Path) -> Path | None:
    """Met les instantanés quotidiens hors de portée de la rotation."""
    snapshots = [p for p in backups.glob("fontsync-*.db") if p.resolve() != keep_out]
    if not snapshots:
        return None
    shelter = _unique_dir(backups, f"pre-restore-{stamp}")
    shelter.mkdir()
    for snap in snapshots:
        for suffix in _MOVE_ORDER:
            item = Path(f"{snap}{suffix}")
            if item.exists():
                os.replace(item, shelter / item.name)
    return shelter


def restore_snapshot(
    snapshot: Path,
    db_path: Path,
    *,
    safe_devices: bool = True,
    protect_backups: Path | None = None,
) -> RestoreResult:
    """Pose `snapshot` à la place de `db_path`, sans rien supprimer.

    L'instantané est d'abord copié (API de sauvegarde SQLite) dans
    `pre-restore-<horodatage>/`, à côté de la base, et ses appareils y sont
    passés en réglages sûrs ; puis la base en place et ses annexes sont
    déplacées dans ce dossier et la copie préparée prend leur place. Toute
    erreur jusque-là remet les fichiers d'origine en place. Les étapes
    suivantes (copie de l'instantané, mise à l'abri des sauvegardes) ne
    lèvent pas : leurs échecs sont rendus dans `warnings`.

    Raises:
        RestoreError: instantané refusé — rien n'a été touché.
        RollbackFailed: la remise en place a échoué — état à examiner.
    """
    snapshot = snapshot.resolve()
    if db_path.exists() and snapshot == db_path.resolve():
        raise RestoreError("l'instantané est la base elle-même")
    check_snapshot(snapshot)

    stamp = _stamp()
    aside = _unique_dir(db_path.parent, f"pre-restore-{stamp}")
    aside.mkdir()
    staging = aside / f"incoming-{db_path.name}"
    moved: list[str] = []
    devices_before: list[dict[str, Any]] = []
    try:
        write_snapshot(snapshot, staging, immutable_source=True)
        if safe_devices:
            devices_before = _make_devices_safe(staging)
        for suffix in _MOVE_ORDER:
            current = Path(f"{db_path}{suffix}")
            if current.exists():
                os.replace(current, aside / current.name)
                moved.append(current.name)
        os.replace(staging, db_path)
    except BaseException as error:
        try:
            for name in reversed(moved):
                os.replace(aside / name, db_path.parent / name)
            for leftover in (staging, Path(f"{staging}-journal")):
                leftover.unlink(missing_ok=True)
            if not any(aside.iterdir()):
                aside.rmdir()
        except BaseException as rollback_error:
            raise RollbackFailed(aside, rollback_error) from error
        raise

    result = RestoreResult(
        restored=db_path,
        set_aside=aside,
        moved=tuple(moved),
        devices_before=devices_before,
    )
    try:
        shutil.copy2(snapshot, aside / f"restored-{snapshot.name}")
    except OSError as error:
        result.warnings.append(f"copie de l'instantané non gardée ({error})")
    if protect_backups is not None:
        try:
            result.protected = _protect_backups(protect_backups, stamp, snapshot)
        except OSError as error:
            result.warnings.append(f"sauvegardes non mises à l'abri ({error})")
    return result


def main(argv: list[str] | None = None) -> int:
    """Point d'entrée du conteneur de maintenance."""
    parser = argparse.ArgumentParser(
        prog="python -m backend.maintenance.restore",
        description="Restaure un instantané de base (serveur arrêté).",
    )
    parser.add_argument("snapshot", type=Path, help="instantané .db à poser")
    parser.add_argument(
        "--check", action="store_true", help="vérifier seulement l'instantané"
    )
    parser.add_argument(
        "--db", type=Path, default=None, help="base à remplacer (défaut : DATABASE_URL)"
    )
    parser.add_argument(
        "--fonts-from",
        type=Path,
        default=None,
        help="miroir des polices à recopier (ex. /backups/fonts) ; rien n'est retiré",
    )
    parser.add_argument(
        "--fonts-to",
        type=Path,
        default=None,
        help="stockage des polices (défaut : FONT_STORAGE_PATH)",
    )
    parser.add_argument(
        "--protect-backups",
        type=Path,
        default=None,
        help="dossier des instantanés quotidiens à mettre hors rotation",
    )
    parser.add_argument(
        "--devices-json",
        type=Path,
        default=None,
        help="où écrire les réglages des appareils d'avant (JSON)",
    )
    args = parser.parse_args(argv)

    if args.check:
        try:
            revision = check_snapshot(args.snapshot.resolve())
        except RestoreError as error:
            print(f"[restore] ERREUR : {error}.", file=sys.stderr)
            return EXIT_REFUSED
        print(
            f"[restore] {args.snapshot.name} : instantané valide "
            f"(révision du schéma : {revision or 'inconnue'})."
        )
        return EXIT_OK

    db_path = args.db or sqlite_database_path()
    if db_path is None:
        print("[restore] ERREUR : base non SQLite, rien à restaurer.", file=sys.stderr)
        return EXIT_NOT_SQLITE
    try:
        result = restore_snapshot(
            args.snapshot, db_path, protect_backups=args.protect_backups
        )
    except RestoreError as error:
        print(f"[restore] ERREUR : {error}. Base inchangée.", file=sys.stderr)
        return EXIT_REFUSED
    except RollbackFailed as error:
        print(
            f"[restore] ÉTAT INCERTAIN : {error}. Ne PAS démarrer le serveur ; "
            "les fichiers d'origine sont dans ce dossier.",
            file=sys.stderr,
        )
        return EXIT_UNCERTAIN
    except BaseException as error:  # y compris Ctrl-C : la remise en place a eu lieu
        print(
            f"[restore] ERREUR : {type(error).__name__}: {error}. Fichiers "
            "d'origine remis en place : base inchangée.",
            file=sys.stderr,
        )
        return EXIT_REFUSED

    # À partir d'ici la base EST restaurée : aucun échec ne doit dire le contraire.
    code = EXIT_OK
    print(f"[restore] {args.snapshot.name} posé à la place de {db_path.name}.")
    print(
        f"[restore] mis de côté (rien supprimé) dans {result.set_aside.name}/ : "
        f"{', '.join(result.moved) or 'aucune base en place'}."
    )
    print(
        f"[restore] auto-pull et propagation coupés sur {len(result.devices_before)} "
        "appareil(s) dans la base restaurée."
    )
    if result.protected is not None:
        print(
            f"[restore] instantanés quotidiens existants mis hors rotation dans "
            f"{result.protected.name}/."
        )
    for warning in result.warnings:
        print(f"[restore] ATTENTION : {warning}.", file=sys.stderr)
        code = EXIT_RESTORED_WITH_WARNINGS
    try:
        if args.devices_json is not None:
            args.devices_json.write_text(
                json.dumps(result.devices_before, indent=2, ensure_ascii=False)
            )
            print(f"[restore] réglages d'avant : {args.devices_json.name}")
        if args.fonts_from is not None:
            print("[restore] copie des polices depuis le miroir (peut être long)…")
            fonts_to = args.fonts_to or Path(settings.font_storage_path)
            mirror = mirror_blobs(args.fonts_from, fonts_to)
            print(
                f"[restore] polices recopiées : {mirror.copied} copiée(s), "
                f"{mirror.repaired} réparée(s), {mirror.failed} en échec (rien retiré)."
            )
            if mirror.failed:
                code = EXIT_RESTORED_WITH_WARNINGS
    except BaseException as error:  # y compris Ctrl-C pendant la copie
        print(
            f"[restore] ATTENTION : {type(error).__name__}: {error}. La base EST "
            "restaurée ; étape annexe incomplète (réglages d'avant ou polices).",
            file=sys.stderr,
        )
        code = EXIT_RESTORED_WITH_WARNINGS
    return code


if __name__ == "__main__":
    sys.exit(main())
