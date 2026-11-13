"""Contrôles et instantané avant `alembic upgrade head` (entrypoint du conteneur).

Appelé par `scripts/docker-entrypoint.sh` juste avant les migrations :
`python -m backend.premigrate`. Un code de sortie non nul arrête le démarrage
(l'entrypoint est en `set -e`) avec un message qui dit quoi faire, au lieu
d'une migration lancée sans filet ou d'une erreur Alembic obscure.

1. Base absente ou vide : premier démarrage, rien à protéger.
2. Base illisible (fichier endommagé, pas une base SQLite) : refus explicite.
3. Révision inconnue de cette image (base migrée par une image plus récente) :
   refus explicite, base intacte.
4. Tables `_alembic_tmp_<t>` (migration SQLite « batch » interrompue) : si
   `<t>` existe encore, instantané puis suppression de la table temporaire —
   sans danger, `alembic_version` n'a pas avancé et l'originale est intacte ;
   si `<t>` manque, refus sans rien toucher.
5. Migration en attente : instantané `pre-migrate-<rev>-<horodatage>.db` dans
   `BACKUP_DIR` (à défaut, à côté de la base), écrit atomiquement et vérifié.
   Échec de l'instantané = pas de migration.

Pas de rotation de ces instantanés : c'est précisément eux qu'on veut
retrouver après coup. En contrepartie, une migration qui échoue en boucle
(redémarrages du conteneur) s'arrête après `MAX_SNAPSHOTS_PER_DAY`
instantanés de la même révision en 24 h, au lieu d'en écrire un par
redémarrage jusqu'à remplir le disque.
"""

from __future__ import annotations

import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.script.revision import RevisionError
from alembic.util import CommandError

from backend.config import settings
from backend.services.backup import sqlite_database_path, write_snapshot

_APP_ROOT = Path(__file__).resolve().parents[1]
_TMP_PREFIX = "_alembic_tmp_"
# Alembic tronque le nom de la table temporaire à 50 caractères
# (`BatchOperationsImpl._calc_temp_name`).
_TMP_NAME_MAX = 50

MAX_SNAPSHOTS_PER_DAY = 3

EXIT_FUTURE_REVISION = 3
EXIT_BROKEN_MIGRATION = 4
EXIT_SNAPSHOT_FAILED = 5
EXIT_RETRY_LIMIT = 6
EXIT_UNREADABLE = 7

_RESTORE_HOWTO = (
    "Restaurer : arrêter le conteneur, supprimer fontsync.db-wal et "
    "fontsync.db-shm (sinon l'ancien journal se rejoue par-dessus), copier "
    "l'instantané pre-migrate-*.db choisi à la place de fontsync.db, puis "
    "redémarrer avec l'image qui l'a créé (docs/INSTALL-NAS.md §5, Restore ; "
    "docs/RELEASE.md, Rollback)."
)


def _say(message: str) -> None:
    print(f"[premigrate] {message}", flush=True)


def _fail(message: str) -> None:
    print(f"[premigrate] ERREUR : {message}", file=sys.stderr, flush=True)


def _script_directory() -> ScriptDirectory:
    config = Config(str(_APP_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_APP_ROOT / "alembic"))
    return ScriptDirectory.from_config(config)


def _read_state(db_path: Path) -> tuple[set[str], list[str]]:
    """Tables de la base et révision(s) Alembic courante(s).

    Connexion en lecture-écriture (sans création) : un journal ou un WAL
    laissé par un arrêt brutal est ainsi rejoué ou annulé par SQLite, comme
    le ferait Alembic, au lieu de bloquer une connexion en lecture seule.
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=rw", uri=True)
    try:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        revisions: list[str] = []
        if "alembic_version" in tables:
            revisions = [
                row[0]
                for row in conn.execute("SELECT version_num FROM alembic_version")
            ]
    finally:
        conn.close()
    return tables, revisions


def _is_known(script: ScriptDirectory, revision: str) -> bool:
    try:
        return script.get_revision(revision) is not None
    except (RevisionError, CommandError):
        return False


def _snapshot_dir(db_path: Path) -> Path:
    return Path(settings.backup_dir) if settings.backup_dir else db_path.parent


def _recent_snapshots(dest_dir: Path, label: str) -> list[Path]:
    """Instantanés de cette révision pris dans les dernières 24 h."""
    if not dest_dir.is_dir():
        return []
    cutoff = time.time() - 24 * 3600
    recent = []
    for path in dest_dir.glob(f"pre-migrate-{label}-*.db"):
        try:
            if path.stat().st_mtime >= cutoff:
                recent.append(path)
        except OSError:
            continue
    return sorted(recent)


def _snapshot(db_path: Path, dest_dir: Path, label: str) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    # Temporaires d'une passe tuée en cours d'écriture (un seul processus ici).
    for orphan in dest_dir.glob("pre-migrate-*.db.tmp*"):
        orphan.unlink(missing_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest_path = dest_dir / f"pre-migrate-{label}-{stamp}.db"
    suffix = 1
    while dest_path.exists():
        dest_path = dest_dir / f"pre-migrate-{label}-{stamp}-{suffix}.db"
        suffix += 1
    write_snapshot(db_path, dest_path)
    return dest_path


def main() -> int:
    """Contrôles avant migration. Retourne le code de sortie du processus."""
    db_path = sqlite_database_path()
    if db_path is None or str(db_path) == ":memory:":
        _say("base non SQLite : aucun contrôle avant migration.")
        return 0
    if not db_path.exists() or db_path.stat().st_size == 0:
        _say("aucune base existante : premier démarrage, rien à sauvegarder.")
        return 0

    try:
        tables, revisions = _read_state(db_path)
    except sqlite3.Error as error:
        _fail(
            f"base illisible ({type(error).__name__}: {error}) : fichier "
            "endommagé, verrouillé ou qui n'est pas une base SQLite. Aucune "
            f"migration lancée. {_RESTORE_HOWTO}"
        )
        return EXIT_UNREADABLE
    if not tables:
        _say("base vide : rien à sauvegarder.")
        return 0

    script = _script_directory()
    unknown = [rev for rev in revisions if not _is_known(script, rev)]
    if unknown:
        _fail(
            f"base à la révision {', '.join(unknown)}, plus récente que cette "
            f"image (révision(s) connue(s) : {', '.join(script.get_heads())}). "
            "Aucune migration lancée, base intacte. Revenir à l'image qui a "
            "créé cette révision (tag sha-…), ou restaurer l'instantané "
            f"pre-migrate-*.db pris avant la mise à jour. {_RESTORE_HOWTO}"
        )
        return EXIT_FUTURE_REVISION

    temp_names = {(_TMP_PREFIX + t)[:_TMP_NAME_MAX] for t in tables}
    leftovers = sorted(t for t in tables if t.startswith(_TMP_PREFIX))
    orphans = [t for t in leftovers if t not in temp_names]
    if orphans:
        _fail(
            f"migration interrompue : {', '.join(orphans)} sans sa table "
            "d'origine. Rien n'a été touché ; ne pas relancer la migration sur "
            "cette base. Restaurer le PREMIER instantané pre-migrate-*.db pris "
            f"depuis la mise à jour. {_RESTORE_HOWTO}"
        )
        return EXIT_BROKEN_MIGRATION

    pending = set(revisions) != set(script.get_heads())
    if not leftovers and not pending:
        _say(f"schéma à jour (révision {', '.join(revisions)}) : pas d'instantané.")
        return 0

    label = revisions[0] if revisions else "none"
    dest_dir = _snapshot_dir(db_path)
    recent = _recent_snapshots(dest_dir, label)
    if len(recent) >= MAX_SNAPSHOTS_PER_DAY:
        _fail(
            f"{len(recent)} instantanés pre-migrate-{label} déjà pris en 24 h : "
            "la migration échoue en boucle. Rien n'a été touché. Lire les "
            "journaux du démarrage précédent ; pour réessayer, déplacer ces "
            f"instantanés hors de {dest_dir.name}/ (le premier est celui "
            "d'avant la mise à jour)."
        )
        return EXIT_RETRY_LIMIT

    try:
        snapshot = _snapshot(db_path, dest_dir, label)
    except Exception as error:  # tout échec bloque la migration
        _fail(
            f"instantané avant migration impossible ({type(error).__name__}: "
            f"{error}). Migration non lancée : vérifier BACKUP_DIR (droits, "
            "espace disque) et l'intégrité de la base (PRAGMA integrity_check)."
        )
        return EXIT_SNAPSHOT_FAILED
    _say(f"instantané avant migration : {snapshot.name} (dans {snapshot.parent.name}/)")

    if leftovers:
        conn = sqlite3.connect(f"file:{db_path}?mode=rw", uri=True)
        try:
            for table in leftovers:
                conn.execute(f'DROP TABLE "{table}"')
            conn.commit()
        finally:
            conn.close()
        _say(
            "migration interrompue réparée : "
            f"{', '.join(leftovers)} supprimée(s), tables d'origine intactes."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
