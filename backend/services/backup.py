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
import logging
import shutil
import sqlite3
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

    Returns:
        Le chemin de l'instantané écrit.

    Raises:
        RuntimeError: si `integrity_check` ne renvoie pas `ok`.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest_path = dest_dir / f"fontsync-{stamp}.db"
    suffix = 1
    while dest_path.exists():
        dest_path = dest_dir / f"fontsync-{stamp}-{suffix}.db"
        suffix += 1

    def _copy_and_check() -> None:
        src = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
        dst = sqlite3.connect(str(dest_path))
        try:
            src.backup(dst)
        finally:
            src.close()
        try:
            verdict = dst.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            dst.close()
        if verdict != "ok":
            dest_path.unlink(missing_ok=True)
            raise RuntimeError(f"integrity_check sur la copie : {verdict}")

    await asyncio.to_thread(_copy_and_check)
    _rotate_snapshots(dest_dir, keep)
    return dest_path


def _rotate_snapshots(dest_dir: Path, keep: int) -> None:
    """Ne garde que les `keep` instantanés les plus récents.

    L'horodatage est dans le nom (`fontsync-YYYYMMDD-HHMMSS[-n].db`) : l'ordre
    lexicographique coïncide avec l'ordre chronologique, pas besoin de
    `stat()`.
    """
    if keep <= 0:
        return
    snapshots = sorted(dest_dir.glob("fontsync-*.db"))
    for stale in snapshots[:-keep]:
        stale.unlink(missing_ok=True)


def mirror_blobs(source_dir: Path, dest_dir: Path) -> int:
    """Miroir incrémental des polices : copie ce qui manque, un point c'est tout.

    Les fichiers sont nommés par empreinte et jamais réécrits une fois posés
    (`backend/services/storage.py`) : un fichier déjà présent côté miroir n'a
    donc aucune raison d'être relu. Pas de suppression non plus, jamais — un
    vidage de corbeille en prod ne doit pas se propager à la sauvegarde,
    c'est tout l'intérêt d'en avoir une.

    Bloquant (I/O fichier en masse) : à appeler via `asyncio.to_thread`.

    Returns:
        Nombre de fichiers copiés.
    """
    if not source_dir.is_dir():
        return 0
    copied = 0
    for path in source_dir.rglob("*"):
        if not path.is_file():
            continue
        dest_path = dest_dir / path.relative_to(source_dir)
        if dest_path.exists():
            continue
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest_path)
        copied += 1
    return copied


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
            copied = await asyncio.to_thread(mirror_blobs, source_dir, dest_dir)
            logger.info(
                "Miroir des polices : %d nouveau(x) fichier(s) copié(s).", copied
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Miroir des polices échoué (la boucle continue)")
        await asyncio.sleep(BACKUP_BLOBS_INTERVAL_SECONDS)
