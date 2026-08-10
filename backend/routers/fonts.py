"""Router pour la gestion des fonts."""

import logging
import math
import uuid
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import asc, delete, desc, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from backend.database import get_db
from backend.models.device import Device
from backend.models.device_font import DeviceFont
from backend.models.font import (
    DELETION_MANUAL,
    DELETION_PENDING,
    DELETION_QUARANTINE,
    Font,
    deletion_confirmed_clause,
    deletion_unconfirmed_clause,
    is_deletion_confirmed,
)
from backend.models.font_family import FontFamilyMember
from backend.schemas.font import (
    ConfirmDeletionsResponse,
    DuplicateFaceGroup,
    DuplicateFacesResponse,
    FontDeviceStatus,
    FontListResponse,
    FontResponse,
    FontSortField,
    FontUpdate,
    FontUploadResponse,
    PurgeResponse,
    ResolveDuplicatesRequest,
    ResolveDuplicatesResponse,
    SortOrder,
    TrashListResponse,
)
from backend.services.duplicate_faces import (
    DuplicateGroup,
    decode_key,
    encode_key,
    find_duplicate_faces,
    resolve_duplicate_faces,
)
from backend.services.font_importer import FontImportError, import_font
from backend.services.storage import StorageBackend, get_storage_backend
from backend.services.trash import purge_font
from backend.services.ws_manager import ws_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/fonts", tags=["fonts"])


def get_storage() -> StorageBackend:
    return get_storage_backend()


# ---------- Upload ----------


@router.post("/upload", response_model=FontUploadResponse)
async def upload_fonts(
    files: list[UploadFile],
    db: AsyncSession = Depends(get_db),
    storage: StorageBackend = Depends(get_storage),
) -> FontUploadResponse:
    """Upload un ou plusieurs fichiers de fonts."""
    imported: list[FontResponse] = []
    duplicates: list[FontResponse] = []
    errors: list[dict] = []

    for file in files:
        filename = file.filename or "unknown"
        try:
            file_data = await file.read()
            font, is_duplicate = await import_font(
                filename=filename,
                file_data=file_data,
                storage=storage,
                db=db,
            )
            font_response = FontResponse.model_validate(font)
            if is_duplicate:
                duplicates.append(font_response)
            else:
                imported.append(font_response)
        except FontImportError as e:
            errors.append({"filename": e.filename, "detail": e.detail})
        except Exception:
            logger.exception("Erreur inattendue lors de l'import de %s", filename)
            errors.append(
                {"filename": filename, "detail": "Erreur interne du serveur."}
            )

    # Notification temps réel aux clients frontend (une font.added par import).
    for font_resp in imported:
        await ws_manager.broadcast_to_clients(
            {
                "type": "font.added",
                "data": font_resp.model_dump(mode="json", by_alias=True),
            }
        )

    # Propagation réactive vers les agents : un signal SSE « re-sync ». Le canal
    # WS legacy (`broadcast_to_agents`) est mort depuis la bascule de l'agent en
    # SSE — d'où l'absence de propagation après upload (B2). Comme `/sync/push`
    # et `/restore`, on signale les process `listen` ; un seul signal suffit,
    # l'agent re-synchronise et pulle toutes les nouvelles fonts.
    if imported:
        await ws_manager.broadcast_sync()

    return FontUploadResponse(
        imported=imported,
        duplicates=duplicates,
        errors=errors,
    )


# ---------- Liste paginée avec filtres ----------


@router.get("", response_model=FontListResponse)
async def list_fonts(
    search: str | None = None,
    classification: str | None = None,
    file_format: str | None = Query(None, alias="format"),
    scripts: list[str] | None = Query(None),
    is_variable: bool | None = None,
    weight_min: int | None = None,
    weight_max: int | None = None,
    family_id: uuid.UUID | None = None,
    orphan: bool | None = None,
    sort: FontSortField = FontSortField.created_at,
    order: SortOrder = SortOrder.desc,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> FontListResponse:
    """Liste paginée des fonts avec filtres."""
    query = select(Font).where(Font.deleted_at.is_(None))

    # Filtre recherche textuelle
    if search:
        pattern = f"%{search}%"
        query = query.where(
            or_(
                Font.family_name.ilike(pattern),
                Font.full_name.ilike(pattern),
                Font.postscript_name.ilike(pattern),
                Font.original_filename.ilike(pattern),
                Font.designer.ilike(pattern),
            )
        )

    # Filtres exacts
    if classification:
        query = query.where(Font.classification == classification)
    if file_format:
        query = query.where(Font.file_format == file_format)
    if is_variable is not None:
        query = query.where(Font.is_variable == is_variable)

    # Filtre scripts (contient tous les scripts demandés)
    if scripts:
        query = query.where(Font.supported_scripts.contains(scripts))

    # Filtre weight range
    if weight_min is not None:
        query = query.where(Font.weight_class >= weight_min)
    if weight_max is not None:
        query = query.where(Font.weight_class <= weight_max)

    # Filtre famille
    if family_id is not None:
        query = query.join(FontFamilyMember, Font.id == FontFamilyMember.font_id).where(
            FontFamilyMember.family_id == family_id
        )
    elif orphan is True:
        # Fonts sans famille
        member_ids = select(FontFamilyMember.font_id)
        query = query.where(Font.id.notin_(member_ids))

    # Compte total
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Tri — `name` (specs §5.1) n'a pas de colonne dédiée : on trie sur full_name.
    sort_column = (
        Font.full_name if sort == FontSortField.name else getattr(Font, sort.value)
    )
    order_func = desc if order == SortOrder.desc else asc
    query = query.order_by(order_func(sort_column))

    # Pagination
    offset = (page - 1) * per_page
    query = query.offset(offset).limit(per_page)

    result = await db.execute(query)
    fonts = result.scalars().all()

    return FontListResponse(
        items=[FontResponse.model_validate(f) for f in fonts],
        total=total,
        page=page,
        per_page=per_page,
        pages=math.ceil(total / per_page) if total > 0 else 0,
    )


# ---------- Doublons de face ----------
#
# Déclarées **avant** `/{font_id}`, pour la même raison que la corbeille.


@router.get("/duplicates", response_model=DuplicateFacesResponse)
async def list_duplicate_faces(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> DuplicateFacesResponse:
    """Faces présentes en plusieurs exemplaires, groupe par groupe.

    Le recensement porte sur `(famille typographique, style)` — l'identité
    réelle d'une face — là où la déduplication à l'import ne compare que des
    empreintes de fichier. Trois noms différents pour une seule face donnent
    trois empreintes : par hash, aucun de ces doublons n'est visible.

    Lecture pure. Les totaux décrivent l'ensemble du recensement, pas la page :
    c'est sur eux que porte le geste de résolution.
    """
    groups = await find_duplicate_faces(db)
    scanned = await db.execute(
        select(func.count()).select_from(Font).where(Font.deleted_at.is_(None))
    )

    start = (page - 1) * per_page
    return DuplicateFacesResponse(
        items=[_to_group_schema(g) for g in groups[start : start + per_page]],
        total_groups=len(groups),
        total_redundant=sum(len(g.redundant) for g in groups),
        bytes_freed=sum(f.file_size for g in groups for f in g.redundant),
        scanned=scanned.scalar() or 0,
        page=page,
        per_page=per_page,
        pages=math.ceil(len(groups) / per_page) if groups else 0,
    )


def _to_group_schema(group: DuplicateGroup) -> DuplicateFaceGroup:
    return DuplicateFaceGroup(
        family=group.family,
        subfamily=group.subfamily,
        key=encode_key(group.key),
        keeper=FontResponse.model_validate(group.keeper),
        redundant=[FontResponse.model_validate(f) for f in group.redundant],
        also_kept=[FontResponse.model_validate(f) for f in group.also_kept],
        bytes_freed=sum(f.file_size for f in group.redundant),
    )


@router.post("/duplicates/resolve", response_model=ResolveDuplicatesResponse)
async def resolve_duplicate_faces_endpoint(
    body: ResolveDuplicatesRequest,
    db: AsyncSession = Depends(get_db),
) -> ResolveDuplicatesResponse:
    """Envoie à la corbeille les fichiers en trop. Un seul « oui » pour tout.

    Réviser 918 groupes un par un se compte en heures ; ce que l'utilisateur
    révise ici, c'est le **résultat de la règle** — un gardé par face, le plus
    complet, choisi par un classement total donc reproductible. La corbeille est
    ce qui rend le geste en bloc acceptable : rien n'est effacé, tout se
    restaure, et les fichiers ne quittent le stockage qu'au vidage.

    `dry_run` compte sans rien déplacer, pour confirmer le chiffre avant de le
    déclencher. Sans `keys`, toutes les faces recensées y passent.
    """
    keys: set[tuple[str, str]] | None = None
    if body.keys is not None:
        decoded = [decode_key(raw) for raw in body.keys]
        if any(k is None for k in decoded):
            raise HTTPException(
                status_code=400, detail="Identité de face malformée dans `keys`."
            )
        keys = {k for k in decoded if k is not None}

    if body.dry_run:
        groups = await find_duplicate_faces(db)
        if keys is not None:
            groups = [g for g in groups if g.key in keys]
        return ResolveDuplicatesResponse(
            groups=len(groups),
            trashed=sum(len(g.redundant) for g in groups),
            bytes_freed=sum(f.file_size for g in groups for f in g.redundant),
            dry_run=True,
        )

    outcome = await resolve_duplicate_faces(db, keys=keys)
    await db.commit()

    for font in outcome.trashed:
        await ws_manager.broadcast_to_clients(
            {"type": "font.deleted", "data": {"id": str(font.id)}}
        )
    if outcome.trashed:
        # Les appareils qui propagent les suppressions doivent les appliquer ;
        # ils l'apprendront au prochain delta, qu'on déclenche tout de suite.
        await ws_manager.broadcast_sync()

    return ResolveDuplicatesResponse(
        groups=outcome.groups,
        trashed=len(outcome.trashed),
        bytes_freed=outcome.bytes_freed,
        dry_run=False,
    )


# ---------- Corbeille ----------
#
# Ces routes sont déclarées **avant** `/{font_id}` : FastAPI résout dans l'ordre
# de déclaration, et `/trash` serait sinon capté comme un identifiant de police
# (échec de parsing UUID → 422).


@router.get("/trash", response_model=TrashListResponse)
async def list_trash(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> TrashListResponse:
    """Polices supprimées **et encore restaurables**, les plus récentes d'abord.

    Une ligne dont le fichier a été retiré du stockage (`purged_at`) n'est plus
    une entrée de corbeille : c'est une pierre tombale. Elle reste en base — son
    empreinte est ce qui empêche la police de revenir au push suivant — mais
    l'afficher ne proposait qu'un bouton grisé et une explication. Elle sort donc
    de la vue, sans sortir de la base.
    """
    query = select(Font).where(Font.deleted_at.is_not(None), Font.purged_at.is_(None))

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar() or 0

    # Même clause de visibilité : annoncer « N en attente d'arbitrage » au-dessus
    # d'une liste qui ne les contient pas offrirait un seul bouton — celui qui
    # propage la désinstallation de polices que l'utilisateur ne peut plus voir.
    pending_result = await db.execute(
        select(func.count())
        .select_from(Font)
        .where(
            Font.deleted_at.is_not(None),
            Font.purged_at.is_(None),
            Font.deleted_reason == DELETION_PENDING,
        )
    )

    result = await db.execute(
        query.order_by(desc(Font.deleted_at))
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    fonts = result.scalars().all()

    return TrashListResponse(
        items=[FontResponse.model_validate(f) for f in fonts],
        total=total,
        page=page,
        per_page=per_page,
        pages=math.ceil(total / per_page) if total > 0 else 0,
        pending_confirmation=pending_result.scalar() or 0,
    )


@router.post("/trash/empty", response_model=PurgeResponse)
async def empty_trash(
    db: AsyncSession = Depends(get_db),
    storage: StorageBackend = Depends(get_storage),
) -> PurgeResponse:
    """Vide la corbeille : retire les fichiers du stockage, garde les empreintes.

    Garder la ligne n'est pas une demi-mesure. Sans elle, la police reviendrait
    au premier push d'une machine qui détient encore le fichier — et une purge
    au jour 30 la ferait réapparaître au jour 31, indéfiniment.

    Les suppressions **non confirmées** sont épargnées : retirer leur fichier les
    rendrait irrécupérables alors qu'elles attendent précisément un arbitrage. On
    les compte et on le dit — un vidage qui laisse des lignes sans l'expliquer
    passe pour un bug.
    """
    retained_result = await db.execute(
        select(func.count())
        .select_from(Font)
        .where(
            Font.deleted_at.is_not(None),
            Font.purged_at.is_(None),
            deletion_unconfirmed_clause(),
        )
    )
    retained = retained_result.scalar() or 0

    result = await db.execute(
        select(Font).where(
            Font.deleted_at.is_not(None),
            Font.purged_at.is_(None),
            deletion_confirmed_clause(),
        )
    )
    purged = 0
    for font in result.scalars().all():
        if await purge_font(font, storage, db):
            purged += 1
    await db.commit()
    logger.info(
        "Corbeille vidée : %d fichier(s) retiré(s) du stockage, "
        "%d suppression(s) retenue(s) faute de confirmation.",
        purged,
        retained,
    )
    return PurgeResponse(purged=purged, retained=retained)


@router.post("/trash/confirm", response_model=ConfirmDeletionsResponse)
async def confirm_pending_deletions(
    db: AsyncSession = Depends(get_db),
) -> ConfirmDeletionsResponse:
    """Confirme les quarantaines retenues par le seuil : elles se propagent.

    Ces polices sont déjà hors de la bibliothèque ; ce qui était suspendu, c'est
    leur **désinstallation sur les autres machines**. Confirmer lève cette
    suspension — c'est la seule action de tout ce module qui peut faire
    disparaître un fichier ailleurs, d'où le geste explicite.
    """
    # `deleted_at IS NOT NULL` n'est pas redondant. Le motif est aujourd'hui le
    # seul filtre, et il le restera d'autant moins que le verrou deviendra un
    # booléen partagé par toutes les polices vivantes : sans cette clause, un
    # clic sur « Confirmer et propager » porterait sur la bibliothèque entière.
    result = await db.execute(
        select(Font).where(
            Font.deleted_at.is_not(None),
            Font.deleted_reason == DELETION_PENDING,
        )
    )
    fonts = list(result.scalars().all())
    for font in fonts:
        font.deleted_reason = DELETION_QUARANTINE
    await db.commit()

    if fonts:
        logger.info(
            "%d quarantaine(s) confirmée(s) : la propagation reprend.", len(fonts)
        )
        await ws_manager.broadcast_sync()
    return ConfirmDeletionsResponse(confirmed=len(fonts))


# ---------- Détail ----------


async def _get_font_or_404(
    font_id: uuid.UUID, db: AsyncSession, *, include_deleted: bool = False
) -> Font:
    """Récupère une font par ID ou lève 404."""
    query = select(Font).where(Font.id == font_id)
    if not include_deleted:
        query = query.where(Font.deleted_at.is_(None))
    result = await db.execute(query)
    font = result.scalar_one_or_none()
    if font is None:
        raise HTTPException(status_code=404, detail="Font non trouvée.")
    return font


@router.get("/{font_id}", response_model=FontResponse)
async def get_font(
    font_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> FontResponse:
    """Détail complet d'une font."""
    font = await _get_font_or_404(font_id, db)
    resp = FontResponse.model_validate(font)

    # Résoudre la famille d'appartenance (pour les onglets de graisses côté front)
    family_result = await db.execute(
        select(FontFamilyMember.family_id).where(FontFamilyMember.font_id == font.id)
    )
    resp.family_id = family_result.scalar_one_or_none()

    # Résoudre le nom du device source
    if font.source_device_id:
        device_result = await db.execute(
            select(Device.name).where(Device.id == font.source_device_id)
        )
        resp.source_device_name = device_result.scalar_one_or_none()

    return resp


# ---------- Téléchargement fichier ----------


MIME_TYPES: dict[str, str] = {
    "ttf": "font/ttf",
    "otf": "font/otf",
    "woff": "font/woff",
    "woff2": "font/woff2",
    "ttc": "font/collection",
}


@router.get("/{font_id}/file")
async def download_font_file(
    font_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    storage: StorageBackend = Depends(get_storage),
) -> Response:
    """Télécharge le fichier binaire de la font."""
    font = await _get_font_or_404(font_id, db)
    try:
        data = await storage.retrieve(font.file_hash, font.file_format)
    except FileNotFoundError:
        raise HTTPException(
            status_code=404, detail="Fichier introuvable dans le stockage."
        )
    content_type = MIME_TYPES.get(font.file_format, "application/octet-stream")
    encoded = quote(font.original_filename, safe="")
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded}",
        },
    )


# ---------- Preview (pour @font-face) ----------


@router.get("/{font_id}/preview")
async def preview_font_file(
    font_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    storage: StorageBackend = Depends(get_storage),
) -> Response:
    """Fichier pour @font-face (preview dans le navigateur)."""
    font = await _get_font_or_404(font_id, db)
    try:
        data = await storage.retrieve(font.file_hash, font.file_format)
    except FileNotFoundError:
        raise HTTPException(
            status_code=404, detail="Fichier introuvable dans le stockage."
        )
    content_type = MIME_TYPES.get(font.file_format, "application/octet-stream")
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=31536000, immutable",
        },
    )


# ---------- Modification ----------


@router.patch("/{font_id}", response_model=FontResponse)
async def update_font(
    font_id: uuid.UUID,
    body: FontUpdate,
    db: AsyncSession = Depends(get_db),
) -> FontResponse:
    """Modifie les métadonnées d'une font."""
    font = await _get_font_or_404(font_id, db)
    update_data = body.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="Aucun champ à modifier.")
    for field, value in update_data.items():
        setattr(font, field, value)
    font.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(font)
    response = FontResponse.model_validate(font)
    await ws_manager.broadcast_to_clients(
        {
            "type": "font.updated",
            "data": response.model_dump(mode="json", by_alias=True),
        }
    )
    return response


# ---------- Statut par appareil ----------


@router.get("/{font_id}/devices", response_model=list[FontDeviceStatus])
async def get_font_device_status(
    font_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> list[FontDeviceStatus]:
    """Retourne le statut d'installation de cette font sur chaque appareil."""
    await _get_font_or_404(font_id, db)

    # Tous les devices
    devices_result = await db.execute(select(Device).order_by(Device.name))
    devices = devices_result.scalars().all()

    # Associations device_fonts pour cette font
    df_result = await db.execute(
        select(DeviceFont).where(DeviceFont.font_id == font_id)
    )
    device_fonts = {df.device_id: df for df in df_result.scalars().all()}

    # Présence = une connexion SSE `listen` ouverte. `connected_agents` est le
    # registre du canal WebSocket agent, que plus aucun agent n'ouvre depuis la
    # refonte stateless : il est vide en permanence, donc tout appareil était
    # annoncé hors ligne et le bouton « Installer » grisé pour toujours.
    online_ids = set(ws_manager.connected_sse_devices)

    statuses = []
    for device in devices:
        df = device_fonts.get(device.id)
        statuses.append(
            FontDeviceStatus(
                device_id=device.id,
                device_name=device.name,
                hostname=device.hostname,
                is_online=str(device.id) in online_ids,
                installed=df is not None,
                activated=df.activated if df else False,
                local_path=df.local_path if df else None,
                installed_at=df.installed_at if df else None,
            )
        )

    return statuses


async def _get_device_or_404(device_id: uuid.UUID, db: AsyncSession) -> Device:
    """Récupère un device par ID ou lève 404."""
    result = await db.execute(select(Device).where(Device.id == device_id))
    device = result.scalar_one_or_none()
    if device is None:
        raise HTTPException(status_code=404, detail="Device non trouvé.")
    return device


# Stop-gap B1 (PLAN-PUBLICATION.md). Depuis la refonte stateless, le sync est un
# *miroir* (l'agent pulle toutes les fonts du serveur selon `auto_pull`) et le
# canal commande UI→agent a disparu. La sélection fine par appareil — n'installer
# QUE cette font, désinstaller, activer/désactiver — suppose un « manifeste désiré »
# par device + une réconciliation côté agent : c'est une vraie fonctionnalité,
# reportée à un redesign dédié. En attendant : « install » déclenche un re-sync de
# l'appareil (pas une commande spécifique), et les actions non encore supportées
# répondent 501 (au lieu d'un 503 trompeur « agent non connecté »).
_B1_DEFERRED = (
    "Le contrôle par appareil (désinstallation, activation/désactivation) est en "
    "cours de refonte (manifeste désiré). Dans cette version, les polices se "
    "synchronisent en miroir selon le réglage « pull automatique » de l'appareil."
)


@router.post("/{font_id}/install/{device_id}", status_code=202)
async def install_font_on_device(
    font_id: uuid.UUID,
    device_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Déclenche un re-sync de l'appareil pour qu'il récupère les fonts du serveur.

    Modèle miroir (stop-gap B1) : on ne pousse pas une commande « installe cette
    font », on signale à l'appareil de se re-synchroniser (SSE) ; il pullera les
    fonts manquantes selon son réglage `auto_pull`. Best-effort : si aucun process
    `listen` n'est abonné, le signal est ignoré (l'appareil se resynchronise de
    toute façon périodiquement / sur `WatchPaths`).
    """
    await _get_font_or_404(font_id, db)
    await _get_device_or_404(device_id, db)
    await ws_manager.signal_sync(str(device_id))
    return {"status": "resync_requested"}


@router.post("/{font_id}/uninstall/{device_id}", status_code=501)
async def uninstall_font_on_device(
    font_id: uuid.UUID,
    device_id: uuid.UUID,
) -> dict:
    """Désinstallation par appareil — reportée au redesign « manifeste désiré » (B1)."""
    raise HTTPException(status_code=501, detail=_B1_DEFERRED)


@router.post("/{font_id}/activate/{device_id}", status_code=501)
async def activate_font_on_device(
    font_id: uuid.UUID,
    device_id: uuid.UUID,
) -> dict:
    """Activation par appareil — reportée au redesign « manifeste désiré » (B1)."""
    raise HTTPException(status_code=501, detail=_B1_DEFERRED)


@router.post("/{font_id}/deactivate/{device_id}", status_code=501)
async def deactivate_font_on_device(
    font_id: uuid.UUID,
    device_id: uuid.UUID,
) -> dict:
    """Désactivation par appareil — reportée au redesign « manifeste désiré » (B1)."""
    raise HTTPException(status_code=501, detail=_B1_DEFERRED)


# ---------- Soft delete ----------


@router.delete("/{font_id}", status_code=204)
async def delete_font(
    font_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Soft delete d'une font — une **intention**, pas une absence constatée.

    Le motif `manual` est ce qui rend la suppression durable : sans lui,
    `deleted_at` seul ne dit pas si la police a été supprimée ou si elle est
    simplement absente, et la première machine qui détient encore le fichier la
    ressuscite au push suivant.
    """
    font = await _get_font_or_404(font_id, db)
    font.deleted_at = datetime.now(timezone.utc)
    font.deleted_reason = DELETION_MANUAL
    font.updated_at = datetime.now(timezone.utc)
    # Les associations « cet appareil détient cette police » tombent avec elle.
    # Les garder ferait re-quarantiner la police au premier sync suivant une
    # restauration : elle serait de nouveau active, toujours associée à un
    # appareil qui l'a désinstallée entre-temps, donc lue comme disparue. La
    # liste `to_uninstall` se calcule de toute façon sur ce que l'appareil
    # déclare, pas sur ces associations.
    await db.execute(delete(DeviceFont).where(DeviceFont.font_id == font.id))
    await db.commit()
    await ws_manager.broadcast_to_clients(
        {
            "type": "font.deleted",
            "data": {"id": str(font_id)},
        }
    )
    # Les appareils qui propagent les suppressions doivent la désinstaller : ils
    # l'apprendront à leur prochain delta, qu'on déclenche tout de suite.
    await ws_manager.broadcast_sync()


@router.post("/{font_id}/purge", status_code=204)
async def purge_font_file(
    font_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    storage: StorageBackend = Depends(get_storage),
) -> None:
    """Retire du stockage le fichier d'une font supprimée. La ligne est gardée.

    Refuse une font active : on ne supprime pas le fichier d'une police que la
    bibliothèque référence encore. Refuse aussi une suppression non confirmée :
    elle attend un arbitrage, retirer son fichier le trancherait sans le dire.
    """
    font = await _get_font_or_404(font_id, db, include_deleted=True)
    if font.deleted_at is None:
        raise HTTPException(
            status_code=400,
            detail="Cette font n'est pas dans la corbeille.",
        )
    if not is_deletion_confirmed(font):
        raise HTTPException(
            status_code=409,
            detail=(
                "Cette suppression attend une confirmation. Confirmez-la ou "
                "restaurez la police avant de retirer son fichier."
            ),
        )
    await purge_font(font, storage, db)
    await db.commit()


# ---------- Restauration ----------


@router.post("/{font_id}/restore", response_model=FontResponse)
async def restore_font(
    font_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> FontResponse:
    """Restaure une font supprimée (soft delete).

    Impossible si la corbeille a été vidée : le fichier n'existe plus, seule
    l'empreinte subsiste. Ré-uploader le même fichier depuis l'interface
    reconstitue tout (l'upload est le seul chemin autorisé à réveiller une
    pierre tombale, cf. `import_font(revive_deleted=...)`).
    """
    font = await _get_font_or_404(font_id, db, include_deleted=True)
    if font.deleted_at is None:
        raise HTTPException(status_code=400, detail="Cette font n'est pas supprimée.")
    if font.purged_at is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Le fichier de cette font a été retiré du stockage lors du vidage "
                "de la corbeille. Ré-importez-le pour la retrouver."
            ),
        )
    font.deleted_at = None
    font.deleted_reason = None
    font.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(font)
    response = FontResponse.model_validate(font)
    # La font redevient disponible → event frontend + signal SSE « re-sync ».
    await ws_manager.broadcast_to_clients(
        {
            "type": "font.updated",
            "data": response.model_dump(mode="json", by_alias=True),
        }
    )
    await ws_manager.broadcast_sync()
    return response
