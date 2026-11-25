"""Connexion, premier admin, sessions et invitations (`/api/auth`).

Les routes listées dans `backend.auth.PUBLIC_API_PATHS` sont servies sans
identité ; toutes les autres exigent `require_auth`, comme le reste de l'API.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import (
    SESSION_COOKIE,
    Principal,
    _bearer,
    require_auth,
    resolve_principal,
)
from backend.config import settings
from backend.database import get_db
from backend.models.device import Device
from backend.models.user import (
    ROLE_ADMIN,
    SESSION_DEVICE,
    SESSION_WEB,
    AuthSession,
    Invitation,
    User,
)
from backend.schemas.auth import (
    AuthStatus,
    DeviceLoginRequest,
    DeviceLoginResponse,
    InvitationAccept,
    InvitationInfo,
    InvitationLookup,
    LoginRequest,
    MeResponse,
    PasswordChange,
    SessionResponse,
    SetupRequest,
    UserResponse,
)
from backend.services.accounts import (
    _aware,
    adopt_orphan_devices,
    count_users,
    create_session,
    create_user,
    get_user_by_email,
    hash_password,
    hash_token,
    login_rate_limiter,
    normalize_email,
    revoke_user_sessions,
    utcnow,
    verify_password,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Un seul process sert la base : ce verrou suffit à ce que deux « premier
# admin » simultanés ne passent pas tous les deux le test « aucun compte ».
_setup_lock = asyncio.Lock()

_BAD_CREDENTIALS = "Email ou mot de passe incorrect."


# ---------- Utilitaires ----------


def user_response(user: User, *, devices: int = 0, sessions: int = 0) -> UserResponse:
    resp = UserResponse.model_validate(user, from_attributes=True)
    resp.device_count = devices
    resp.session_count = sessions
    return resp


def _is_https(request: Request) -> bool:
    proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
    return request.url.scheme == "https" or proto.lower() == "https"


def set_session_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.web_session_days * 86400,
        httponly=True,
        samesite="strict",
        secure=_is_https(request),
        path="/",
    )


def _client_label(request: Request) -> str:
    agent = request.headers.get("user-agent", "")
    return agent[:200] or "Navigateur"


def _limit_keys(request: Request, email: str) -> tuple[str, str]:
    host = request.client.host if request.client else "?"
    return f"ip:{host}", f"email:{normalize_email(email)}"


async def _check_credentials(
    request: Request, db: AsyncSession, email: str, password: str
) -> User:
    keys = _limit_keys(request, email)
    if login_rate_limiter.blocked(*keys):
        raise HTTPException(
            status_code=429,
            detail="Trop de tentatives. Réessayez dans une minute.",
        )
    user = await get_user_by_email(db, email)
    ok = await verify_password(user.password_hash if user else None, password)
    if not ok or user is None or user.disabled_at is not None:
        login_rate_limiter.record_failure(*keys)
        raise HTTPException(status_code=401, detail=_BAD_CREDENTIALS)
    login_rate_limiter.reset(*keys)
    return user


async def _me(db: AsyncSession, principal: Principal) -> MeResponse:
    user = await db.get(User, principal.user_id) if principal.user_id else None
    return MeResponse(
        kind=principal.kind,
        role=principal.role,
        user=user_response(user) if user else None,
        device_id=principal.device_id,
    )


# ---------- Public ----------


@router.get("/status", response_model=AuthStatus)
async def auth_status(
    request: Request, db: AsyncSession = Depends(get_db)
) -> AuthStatus:
    """État de l'instance pour l'écran d'accueil : faut-il créer l'admin, et
    qui suis-je (si une identité valide accompagne la requête)."""
    principal = await resolve_principal(
        db,
        bearer=_bearer(request.headers.get("authorization")),
        cookie=request.cookies.get(SESSION_COOKIE),
    )
    no_users = await count_users(db) == 0
    return AuthStatus(
        setup_required=no_users,
        me=await _me(db, principal) if principal else None,
    )


@router.post("/setup", response_model=MeResponse, status_code=201)
async def setup_admin(
    body: SetupRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> MeResponse:
    """Crée le premier compte, administrateur. Refusé dès qu'un compte existe.

    La première personne à ouvrir la page devient l'admin : à faire dès
    l'installation (ou par `FONTSYNC_ADMIN_EMAIL`/`_PASSWORD`). Les appareils
    existants sont rattachés à ce compte.
    """
    async with _setup_lock:
        if await count_users(db) > 0:
            raise HTTPException(
                status_code=409, detail="Un administrateur existe déjà."
            )
        user = await create_user(
            db, email=body.email, password=body.password, role=ROLE_ADMIN
        )
        adopted = await adopt_orphan_devices(db, user)
        token = await create_session(
            db, user, kind=SESSION_WEB, label=_client_label(request)
        )
        await db.commit()
    logger.info("Premier admin créé (%d appareil(s) rattaché(s)).", adopted)
    set_session_cookie(response, request, token)
    return MeResponse(kind=SESSION_WEB, role=user.role, user=user_response(user))


@router.post("/login", response_model=MeResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> MeResponse:
    """Connexion navigateur : pose le cookie de session."""
    user = await _check_credentials(request, db, body.email, body.password)
    token = await create_session(
        db, user, kind=SESSION_WEB, label=_client_label(request)
    )
    await db.commit()
    set_session_cookie(response, request, token)
    return MeResponse(kind=SESSION_WEB, role=user.role, user=user_response(user))


@router.post("/logout", status_code=204)
async def logout(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    """Révoque la session du cookie (s'il y en a une) et efface le cookie."""
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        result = await db.execute(
            select(AuthSession).where(
                AuthSession.token_hash == hash_token(cookie),
                AuthSession.kind == SESSION_WEB,
            )
        )
        session = result.scalar_one_or_none()
        if session is not None and session.revoked_at is None:
            session.revoked_at = utcnow()
            await db.commit()
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.post("/device-login", response_model=DeviceLoginResponse, status_code=201)
async def device_login(
    body: DeviceLoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> DeviceLoginResponse:
    """Connexion d'un Mac : rend un jeton d'appareil (sans expiration).

    Le jeton se lie à l'appareil au premier `POST /api/devices/register` qui le
    présente. Le mot de passe n'est jamais conservé côté Mac.
    """
    user = await _check_credentials(request, db, body.email, body.password)
    token = await create_session(
        db, user, kind=SESSION_DEVICE, label=body.device_name or "Appareil"
    )
    await db.commit()
    return DeviceLoginResponse(token=token, user=user_response(user))


async def _live_invitation(db: AsyncSession, token: str) -> Invitation:
    result = await db.execute(
        select(Invitation).where(Invitation.token_hash == hash_token(token))
    )
    invitation = result.scalar_one_or_none()
    if (
        invitation is None
        or invitation.used_at is not None
        or invitation.revoked_at is not None
        or _aware(invitation.expires_at) <= utcnow()
    ):
        raise HTTPException(status_code=404, detail="Invitation invalide ou expirée.")
    return invitation


@router.post("/invitations/lookup", response_model=InvitationInfo)
async def lookup_invitation(
    body: InvitationLookup, db: AsyncSession = Depends(get_db)
) -> InvitationInfo:
    """Ce que l'invitation propose (affiché avant de choisir son mot de passe).

    Le jeton voyage dans le corps, jamais dans l'URL : les journaux d'accès
    enregistrent les chemins."""
    invitation = await _live_invitation(db, body.token)
    return InvitationInfo(email=invitation.email, role=invitation.role)


@router.post("/invitations/accept", response_model=MeResponse, status_code=201)
async def accept_invitation(
    body: InvitationAccept,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> MeResponse:
    """Crée le compte de l'invité avec l'email et le mot de passe qu'il choisit,
    et le connecte."""
    invitation = await _live_invitation(db, body.token)
    email = invitation.email or body.email
    if not email:
        raise HTTPException(status_code=422, detail="Email requis.")
    email = normalize_email(email)
    if await get_user_by_email(db, email) is not None:
        raise HTTPException(
            status_code=409, detail="Un compte existe déjà pour cet email."
        )
    user = await create_user(
        db, email=email, password=body.password, role=invitation.role
    )
    invitation.used_at = utcnow()
    token = await create_session(
        db, user, kind=SESSION_WEB, label=_client_label(request)
    )
    await db.commit()
    set_session_cookie(response, request, token)
    return MeResponse(kind=SESSION_WEB, role=user.role, user=user_response(user))


# ---------- Authentifié ----------


@router.get("/me", response_model=MeResponse)
async def me(
    principal: Principal = Depends(require_auth), db: AsyncSession = Depends(get_db)
) -> MeResponse:
    return await _me(db, principal)


@router.post("/me/password", status_code=204)
async def change_password(
    body: PasswordChange,
    principal: Principal = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Change son mot de passe. Les AUTRES sessions du compte sont révoquées
    (un mot de passe changé par crainte d'une fuite doit couper l'intrus)."""
    if principal.user_id is None or principal.kind == SESSION_DEVICE:
        raise HTTPException(status_code=403, detail="Connectez-vous avec votre compte.")
    user = await db.get(User, principal.user_id)
    if user is None or not await verify_password(
        user.password_hash, body.current_password
    ):
        raise HTTPException(status_code=400, detail="Mot de passe actuel incorrect.")
    user.password_hash = await hash_password(body.new_password)
    await revoke_user_sessions(db, user.id, keep=principal.session_id)
    await db.commit()


@router.get("/sessions", response_model=list[SessionResponse])
async def list_sessions(
    all: bool = False,  # noqa: A002 — nom du paramètre de requête
    principal: Principal = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> list[SessionResponse]:
    """Sessions vivantes : les siennes, ou toutes (`?all=true`, admin)."""
    if all and not principal.is_admin:
        raise HTTPException(status_code=403, detail="Réservé aux administrateurs.")
    if not all and principal.user_id is None:
        return []
    now = utcnow()
    stmt = (
        select(AuthSession, User.email)
        .join(User, User.id == AuthSession.user_id)
        .where(AuthSession.revoked_at.is_(None))
        .order_by(AuthSession.last_used_at.desc())
    )
    if not all:
        stmt = stmt.where(AuthSession.user_id == principal.user_id)
    rows = (await db.execute(stmt)).all()
    out: list[SessionResponse] = []
    for session, email in rows:
        expires = _aware(session.expires_at)
        if expires is not None and expires <= now:
            continue
        out.append(
            SessionResponse(
                id=session.id,
                kind=session.kind,
                label=session.label,
                device_id=session.device_id,
                user_id=session.user_id,
                user_email=email,
                created_at=session.created_at,
                last_used_at=session.last_used_at,
                expires_at=session.expires_at,
                current=session.id == principal.session_id,
            )
        )
    return out


@router.delete("/sessions/{session_id}", status_code=204)
async def revoke_session(
    session_id: uuid.UUID,
    principal: Principal = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Révoque une session : la sienne, ou n'importe laquelle pour un admin."""
    session = await db.get(AuthSession, session_id)
    if session is None or (
        session.user_id != principal.user_id and not principal.is_admin
    ):
        raise HTTPException(status_code=404, detail="Session introuvable.")
    if session.revoked_at is None:
        session.revoked_at = datetime.now(timezone.utc)
        await db.commit()


async def device_counts(db: AsyncSession) -> dict[uuid.UUID, int]:
    rows = await db.execute(
        select(Device.owner_user_id, func.count())
        .where(Device.deleted_at.is_(None), Device.owner_user_id.is_not(None))
        .group_by(Device.owner_user_id)
    )
    return dict(rows.all())
