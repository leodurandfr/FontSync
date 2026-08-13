"""Router pour la synchronisation agent ↔ serveur."""

import logging
import uuid
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from backend.database import get_db
from backend.models.device import Device
from backend.models.font import Font
from backend.schemas.font import FontResponse
from backend.schemas.sync import DeltaSyncRequest, DeltaSyncResponse, PushResponse
from backend.services.deletion_propagation import (
    DeletionDetection,
    detect_local_deletions,
)
from backend.services.font_importer import FontImportError, import_font
from backend.services.harvest import harvest_tombstones
from backend.services.inventory import reconcile_inventory
from backend.services.storage import StorageBackend, get_storage_backend
from backend.services.sync_manager import compute_delta, register_device_font
from backend.services.ws_manager import ws_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sync", tags=["sync"])

MIME_TYPES: dict[str, str] = {
    "ttf": "font/ttf",
    "otf": "font/otf",
    "woff": "font/woff",
    "woff2": "font/woff2",
    "ttc": "font/collection",
}


def get_storage() -> StorageBackend:
    return get_storage_backend()


async def _get_device_or_404(device_id: uuid.UUID, db: AsyncSession) -> Device:
    # Un appareil soft-supprimé (`deleted_at`) est invisible ici comme partout
    # ailleurs : seul `/api/devices/register` sait le ranimer.
    result = await db.execute(
        select(Device).where(Device.id == device_id, Device.deleted_at.is_(None))
    )
    device = result.scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=404, detail="Device non trouvé.")
    return device


@router.post("/delta", response_model=DeltaSyncResponse)
async def delta_sync(
    body: DeltaSyncRequest,
    db: AsyncSession = Depends(get_db),
) -> DeltaSyncResponse:
    """Delta sync : compare les fonts de l'agent avec le serveur.

    L'agent envoie la liste de ses {hash, filename, ingestible}. Le serveur
    retourne :
    - unknown_to_server : hashes à pusher
    - missing_on_device : fonts à puller
    - already_synced : nombre de fonts en commun
    - deleted_on_server / to_uninstall : polices tombées que l'appareil détient
    - to_deactivate : polices que CET appareil a désactivées (`device_fonts.active=False`)

    Quatre temps, dans cet ordre (cf. `docs/PLAN-ETATS-FONTS.md` §3.2) :

    1. **Détection** — INCHANGÉE. Lit le registre avant toute écriture de ce
       sync-ci, pour ne juger que sur l'état d'avant.
    2. **Réconciliation + récolte (aperçu)** — uniquement sur une déclaration
       crédible (ni vide, ni suspecte) : `device_fonts` devient le miroir de ce
       que la machine déclare, et `last_declaration_at` avance. La récolte
       livrée ici ne fait que compter et journaliser (cf. `services/harvest.py`).
    3. **Commit unique**, puis notification des quarantaines.
    4. **Delta** — lecture pure, voit ses propres quarantaines et sa propre
       réconciliation.

    La détection tourne pour **tout** appareil, quel que soit
    `propagate_deletions`. Conditionner l'écoute à ce réglage rendait toute
    suppression locale impossible : le serveur ne concluait rien, la police
    restait dans la bibliothèque, et `auto_pull` la réinstallait au sync suivant
    — mesuré, 31 s entre le geste et son annulation. Or enregistrer une
    disparition n'efface aucun fichier : la police part en corbeille,
    récupérable d'un clic. `propagate_deletions` garde la moitié qui, elle,
    détruit — la désinstallation sur les *autres* machines, arbitrée plus bas
    par `compute_delta`.
    """
    device = await _get_device_or_404(body.device_id, db)
    declared = {entry.hash for entry in body.fonts}

    detection = await detect_local_deletions(device.id, declared, db)

    # Écritures d'inventaire : uniquement sur une déclaration CRÉDIBLE. Une
    # déclaration vide (G1) ou au-delà du seuil de quarantaine (G2, suspecte)
    # ne permet de rien conclure — ni sur les absences, ni sur les présences.
    if declared and not detection.pending:
        await reconcile_inventory(device.id, body.fonts, db)
        device.last_declaration_at = datetime.now(timezone.utc)
        await harvest_tombstones(db)

    await db.commit()
    if detection.total:
        await _notify_quarantined(detection, source_device_id=str(device.id))

    return await compute_delta(
        body.fonts,
        db,
        device_id=device.id,
        propagate_deletions=device.propagate_deletions,
    )


async def _notify_quarantined(
    detection: DeletionDetection, *, source_device_id: str
) -> None:
    """Signale les quarantaines au frontend, et le re-sync aux autres appareils.

    Le device source n'est pas re-signalé : il vient de nous dire qu'il n'a plus
    ces polices, la réponse au delta en cours lui suffit. Une quarantaine en
    attente de confirmation ne déclenche aucun re-sync — c'est tout l'objet du
    seuil : personne d'autre ne touche à ses fichiers avant un oui.
    """
    for font in detection.quarantined + detection.pending:
        await ws_manager.broadcast_to_clients(
            {"type": "font.deleted", "data": {"id": str(font.id)}}
        )
    if detection.quarantined:
        await ws_manager.broadcast_sync(exclude_device_id=source_device_id)


@router.post("/push", response_model=PushResponse)
async def push_font(
    file: UploadFile,
    device_id: uuid.UUID = Form(...),
    local_path: str = Form(""),
    db: AsyncSession = Depends(get_db),
    storage: StorageBackend = Depends(get_storage),
) -> PushResponse:
    """Push d'une font depuis un agent vers le serveur.

    Utilise le pipeline d'import standard, puis enregistre l'association device ↔ font.

    Une font en **pierre tombale** n'est jamais ressuscitée par ce chemin
    (`revive_deleted=False`) : c'est ce réveil-là qui rendait toute suppression
    illusoire. Le refus est signalé explicitement (`refused_deleted`) pour que
    l'agent ne le compte pas en erreur — ce n'en est pas une. En régime normal
    le cas ne se présente pas : le delta ne propose plus de pousser une police
    tombée. Il reste pour les courses (suppression pendant un sync) et pour un
    agent qui pousserait sans delta préalable.
    """
    # Vérifier que le device existe
    device = await _get_device_or_404(device_id, db)

    filename = file.filename or "unknown"
    file_data = await file.read()

    try:
        font, is_duplicate = await import_font(
            filename=filename,
            file_data=file_data,
            storage=storage,
            db=db,
            source="local_scan",
            revive_deleted=False,
        )
    except FontImportError as e:
        raise HTTPException(status_code=400, detail=e.detail)

    if font.deleted_at is not None:
        # Refus : ni association device ↔ font (l'appareil n'a pas à figurer
        # comme détenteur d'une police hors bibliothèque), ni notification.
        logger.info(
            "Push refusé pour %s (font supprimée le %s)",
            filename,
            font.deleted_at,
        )
        return PushResponse(
            font_id=font.id,
            file_hash=font.file_hash,
            is_duplicate=True,
            family_name=font.family_name,
            refused_deleted=True,
        )

    # Mettre à jour source_device_id si c'est une nouvelle font
    if not is_duplicate and font.source_device_id is None:
        font.source_device_id = device.id
        await db.commit()
        await db.refresh(font)

    # Enregistrer l'association device ↔ font
    await register_device_font(
        device_id=device.id,
        font_id=font.id,
        local_path=local_path or filename,
        db=db,
    )
    await db.commit()

    # Notifications WebSocket
    if not is_duplicate:
        font_resp = FontResponse.model_validate(font)
        font_data = font_resp.model_dump(mode="json", by_alias=True)
        # Notifier les clients frontend
        await ws_manager.broadcast_to_clients(
            {
                "type": "font.added",
                "data": font_data,
            }
        )
        # Signal SSE « re-sync » aux process `listen` (sauf le device source,
        # qui possède déjà la font).
        await ws_manager.broadcast_sync(exclude_device_id=str(device.id))

    return PushResponse(
        font_id=font.id,
        file_hash=font.file_hash,
        is_duplicate=is_duplicate,
        family_name=font.family_name,
    )


@router.get("/pull/{font_id}")
async def pull_font(
    font_id: uuid.UUID,
    device_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    storage: StorageBackend = Depends(get_storage),
) -> Response:
    """Retourne le fichier font pour installation par l'agent.

    L'association `device_font` n'est enregistrée qu'après récupération
    réussie du fichier : un échec de stockage ne laisse donc jamais
    d'association « installée » fantôme.
    """
    # Vérifier que le device existe
    await _get_device_or_404(device_id, db)

    result = await db.execute(
        select(Font).where(Font.id == font_id, Font.deleted_at.is_(None))
    )
    font = result.scalar_one_or_none()
    if font is None:
        raise HTTPException(status_code=404, detail="Font non trouvée.")

    try:
        data = await storage.retrieve(font.file_hash, font.file_format)
    except FileNotFoundError:
        raise HTTPException(
            status_code=404, detail="Fichier introuvable dans le stockage."
        )

    # Le fichier est disponible → enregistrer l'association device ↔ font
    await register_device_font(
        device_id=device_id,
        font_id=font.id,
        local_path=font.original_filename,
        db=db,
    )
    await db.commit()

    content_type = MIME_TYPES.get(font.file_format, "application/octet-stream")
    encoded = quote(font.original_filename, safe="")
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded}",
        },
    )
