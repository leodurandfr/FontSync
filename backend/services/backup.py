"""Sauvegarde automatique : instantané de la base + miroir des polices.

Fait, depuis l'intérieur du backend, ce que `scripts/backup-prod.sh` fait
depuis l'extérieur (`docker exec` + tâche planifiée du NAS) : un instantané
cohérent de la base SQLite en WAL via `sqlite3.Connection.backup()`, et un
miroir incrémental des polices qui ne réécrit ni ne supprime jamais un
fichier. Le process a déjà la base ouverte et les polices sous la main —
aucune raison de sortir du conteneur pour ça, et ça marche pareil sur
n'importe quel hôte Docker, pas seulement un NAS Synology avec Planificateur
de tâches. `scripts/backup-prod.sh` reste disponible pour une sauvegarde
manuelle ponctuelle (avant une opération risquée, export vers un stockage
externe).

Désactivée par défaut (`BACKUP_DIR` vide, cf. `backend.config`).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.engine import make_url

from backend.config import settings

logger = logging.getLogger(__name__)

# Cadence des deux boucles. La base est petite (quelques dizaines de Mo) et
# porte l'état : quotidienne. Les polices sont write-once — après la première
# passe, une sauvegarde ne coûte que les nouveautés : hebdomadaire suffit.
BACKUP_DB_INTERVAL_SECONDS = 24 * 3600
BACKUP_BLOBS_INTERVAL_SECONDS = 7 * 24 * 3600

# Instantanés de base conservés (rotation), comme `KEEP` dans backup-prod.sh.
BACKUP_KEEP = 14


async def backup_database(
    source_path: Path, dest_dir: Path, *, keep: int = BACKUP_KEEP
) -> Path:
    """Instantané cohérent de la base, même si elle tourne en WAL.

    Copier le seul fichier `.db` d'une base en WAL est invalide : les
    dernières transactions vivent dans le `-wal` qui l'accompagne. Seule
    `sqlite3.Connection.backup()` gère ça correctement — lecture seule sur la
    source (aucun verrou d'écriture pris sur la prod), `PRAGMA
    integrity_check` sur la copie avant de la garder.

    Bloquant (`sqlite3` est synchrone) : exécuté dans un thread pour ne pas
    geler la boucle asyncio le temps de la copie.

    L'instantané est écrit dans un `.tmp` (hors du motif `fontsync-*.db`),
    vérifié, synchronisé sur disque puis renommé atomiquement : un échec ne
    laisse jamais un fichier final vide ou partiel qui passerait pour une
    sauvegarde valide.

    Returns:
        Le chemin de l'instantané écrit.

    Raises:
        RuntimeError: si `integrity_check` ne renvoie pas `ok` ou si la copie
            ne contient aucune table.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest_path = dest_dir / f"fontsync-{stamp}.db"
    suffix = 1
    while dest_path.exists():
        dest_path = dest_dir / f"fontsync-{stamp}-{suffix}.db"
        suffix += 1
    tmp_path = dest_path.with_name(dest_path.name + ".tmp")

    def _copy_check_and_publish() -> None:
        try:
            src = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
            try:
                dst = sqlite3.connect(str(tmp_path))
                try:
                    src.backup(dst)
                    verdict = dst.execute("PRAGMA integrity_check").fetchone()[0]
                    tables = dst.execute(
                        "SELECT count(*) FROM sqlite_master WHERE type = 'table'"
                    ).fetchone()[0]
                finally:
                    dst.close()
            finally:
                src.close()
            if verdict != "ok":
                raise RuntimeError(f"integrity_check sur la copie : {verdict}")
            if tables == 0:
                raise RuntimeError("copie sans aucune table : source vide ou invalide")
            _fsync_file(tmp_path)
            os.replace(tmp_path, dest_path)
            _fsync_dir(dest_dir)
        except BaseException:
            for leftover in (tmp_path, *_sqlite_sidecars(tmp_path)):
                leftover.unlink(missing_ok=True)
            raise

    await asyncio.to_thread(_copy_check_and_publish)
    _rotate_snapshots(dest_dir, keep)
    return dest_path


def _sqlite_sidecars(path: Path) -> list[Path]:
    """Fichiers annexes que SQLite peut créer à côté de `path`.

    Une source en WAL donne une copie marquée WAL : `integrity_check` y crée
    alors `-wal` et `-shm`, que seul un `close()` normal retire.
    """
    return [Path(f"{path}{suffix}") for suffix in ("-journal", "-wal", "-shm")]


def _fsync_file(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_dir(path: Path) -> None:
    """Rend durable un renommage dans `path` (sans effet si non supporté)."""
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


_SNAPSHOT_NAME = re.compile(r"^fontsync-(\d{8}-\d{6})(?:-(\d+))?\.db$")


def _rotate_snapshots(dest_dir: Path, keep: int) -> None:
    """Ne garde que les `keep` instantanés les plus récents.

    L'horodatage est dans le nom (`fontsync-YYYYMMDD-HHMMSS[-n].db`). Le tri
    se fait sur `(horodatage, n)` et non sur le nom brut : en ordre
    lexicographique, `X-1.db` passerait avant `X.db`. Les temporaires
    orphelins d'une passe interrompue (`*.db.tmp` et ses `-journal`, `-wal`,
    `-shm`) sont retirés.
    """
    for orphan in dest_dir.glob("fontsync-*.db.tmp*"):
        orphan.unlink(missing_ok=True)
    if keep <= 0:
        return
    snapshots = []
    for path in dest_dir.glob("fontsync-*.db"):
        match = _SNAPSHOT_NAME.match(path.name)
        if match:
            snapshots.append(((match.group(1), int(match.group(2) or 0)), path))
    snapshots.sort()
    for _, stale in snapshots[:-keep]:
        stale.unlink(missing_ok=True)


@dataclass(frozen=True)
class MirrorResult:
    """Bilan d'une passe de miroir des polices."""

    copied: int = 0
    repaired: int = 0
    failed: int = 0


def mirror_blobs(source_dir: Path, dest_dir: Path) -> MirrorResult:
    """Miroir incrémental des polices : copie ce qui manque, répare ce qui est tronqué.

    Les fichiers sont nommés par empreinte (`<sha256>.<ext>`) et jamais
    réécrits une fois posés (`backend/services/storage.py`) : une copie de
    même taille est tenue pour bonne et n'est pas relue. Une copie de taille
    différente (passe précédente interrompue) est recopiée — seulement si la
    source correspond bien à son empreinte : une source elle-même abîmée
    (écriture en cours, disque corrompu) n'écrase jamais une bonne copie.
    Chaque copie passe par un `.tmp` synchronisé puis renommé. Pas de
    suppression, jamais — un vidage de corbeille en prod ne doit pas se
    propager à la sauvegarde, c'est tout l'intérêt d'en avoir une. Un fichier
    ou un dossier illisible est journalisé et compté, sans arrêter la passe.

    Bloquant (I/O fichier en masse) : à appeler via `asyncio.to_thread`.
    """
    if not source_dir.is_dir():
        return MirrorResult()
    copied = repaired = failed = 0

    def _unreadable_dir(error: OSError) -> None:
        nonlocal failed
        logger.warning("Miroir : dossier illisible, ignoré : %s", error)
        failed += 1

    files = (
        root / name
        for root, _dirs, names in source_dir.walk(on_error=_unreadable_dir)
        for name in names
    )
    for path in files:
        try:
            if not path.is_file():
                continue
            dest_path = dest_dir / path.relative_to(source_dir)
            repairing = False
            if dest_path.exists():
                if dest_path.stat().st_size == path.stat().st_size:
                    continue
                if _sha256(path) != path.stem:
                    logger.warning(
                        "Miroir : source non conforme à son empreinte, "
                        "copie existante conservée : %s",
                        path,
                    )
                    failed += 1
                    continue
                repairing = True
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = dest_path.with_name(dest_path.name + ".tmp")
            try:
                shutil.copy2(path, tmp_path)
                _fsync_file(tmp_path)
                os.replace(tmp_path, dest_path)
            except BaseException:
                tmp_path.unlink(missing_ok=True)
                raise
            if repairing:
                repaired += 1
            else:
                copied += 1
        except OSError:
            logger.warning(
                "Miroir : fichier non copié, passe poursuivie : %s", path, exc_info=True
            )
            failed += 1
    return MirrorResult(copied=copied, repaired=repaired, failed=failed)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def run_database_backup_loop() -> None:
    """Boucle de sauvegarde de la base : au démarrage, puis chaque jour.

    Ne démarre pas si `BACKUP_DIR` est vide (défaut) ou si le backend n'est
    pas SQLite (rien à instantanéiser hors WAL local). Une erreur ne tue
    jamais la boucle — le serveur d'un NAS tourne des mois d'affilée.
    """
    if not settings.backup_dir:
        logger.info("Sauvegarde automatique désactivée (BACKUP_DIR non défini).")
        return
    url = make_url(settings.database_url)
    if url.get_backend_name() != "sqlite":
        logger.info(
            "Sauvegarde automatique de la base non applicable (backend %s, pas SQLite).",
            url.get_backend_name(),
        )
        return

    source_path = Path(url.database)
    dest_dir = Path(settings.backup_dir)
    logger.info(
        "Sauvegarde automatique de la base activée : %s → %s (quotidienne, %d conservés).",
        source_path,
        dest_dir,
        BACKUP_KEEP,
    )
    while True:
        try:
            snapshot = await backup_database(source_path, dest_dir, keep=BACKUP_KEEP)
            logger.info("Base sauvegardée : %s", snapshot)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Sauvegarde automatique de la base échouée (la boucle continue)"
            )
        await asyncio.sleep(BACKUP_DB_INTERVAL_SECONDS)


async def run_blob_backup_loop() -> None:
    """Boucle de miroir des polices : au démarrage, puis chaque semaine.

    Ne démarre pas si `BACKUP_DIR` est vide, ou si le stockage n'est pas
    filesystem (S3 est déjà durable côté fournisseur — rien à miroiter ici).
    """
    if not settings.backup_dir:
        return
    if settings.storage_backend != "filesystem":
        logger.info(
            "Miroir des polices non applicable (stockage %s).", settings.storage_backend
        )
        return

    source_dir = Path(settings.font_storage_path)
    dest_dir = Path(settings.backup_dir) / "fonts"
    logger.info(
        "Miroir des polices activé : %s → %s (hebdomadaire).", source_dir, dest_dir
    )
    while True:
        try:
            result = await asyncio.to_thread(mirror_blobs, source_dir, dest_dir)
            logger.info(
                "Miroir des polices : %d copié(s), %d réparé(s), %d en échec.",
                result.copied,
                result.repaired,
                result.failed,
            )
            if result.failed:
                logger.warning(
                    "Miroir des polices incomplet : %d fichier(s) non copié(s) "
                    "(voir les avertissements ci-dessus).",
                    result.failed,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Miroir des polices échoué (la boucle continue)")
        await asyncio.sleep(BACKUP_BLOBS_INTERVAL_SECONDS)
