"""Gestion des comptes par l'admin : `/api/users` et `/api/invitations`.

Il n'y a pas d'email sortant (un NAS n'a en général pas de SMTP) : l'admin
invite par un lien qu'il copie lui-même, et réinitialise les mots de passe.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import Principal, require_admin
from backend.config import settings
from backend.database import get_db
from backend.models.user import ROLE_ADMIN, AuthSession, Invitation, User
from backend.routers.auth import device_counts, user_response
from backend.schemas.auth import (
    InvitationCreate,
    InvitationCreated,
    InvitationResponse,
    PasswordReset,
    UserCreate,
    UserResponse,
    UserUpdate,
)
from backend.services.accounts import (
    _aware,
    count_active_admins,
    create_user,
    get_user_by_email,
    hash_password,
    hash_token,
    new_token,
    revoke_user_sessions,
    utcnow,
)

users_router = APIRouter(prefix="/api/users", tags=["users"])
invitations_router = APIRouter(prefix="/api/invitations", tags=["users"])


async def _session_counts(db: AsyncSession) -> dict[uuid.UUID, int]:
    now = utcnow()
    rows = await db.execute(
        select(AuthSession.user_id, AuthSession.expires_at).where(
            AuthSession.revoked_at.is_(None)
        )
    )
    counts: dict[uuid.UUID, int] = {}
    for user_id, expires_at in rows.all():
        expires = _aware(expires_at)
        if expires is None or expires > now:
            counts[user_id] = counts.get(user_id, 0) + 1
    return counts


async def _get_user_or_404(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Compte introuvable.")
    return user


@users_router.get("", response_model=list[UserResponse])
async def list_users(
    _admin: Principal = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> list[UserResponse]:
    users = (await db.execute(select(User).order_by(User.created_at))).scalars().all()
    devices = await device_counts(db)
    sessions = await _session_counts(db)
    return [
        user_response(u, devices=devices.get(u.id, 0), sessions=sessions.get(u.id, 0))
        for u in users
    ]


@users_router.post("", response_model=UserResponse, status_code=201)
async def add_user(
    body: UserCreate,
    _admin: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Crée un compte directement, sans invitation. L'admin transmet lui-même le
    mot de passe ; la personne pourra le changer depuis son compte."""
    if await get_user_by_email(db, body.email) is not None:
        raise HTTPException(
            status_code=409, detail="Un compte existe déjà pour cet email."
        )
    user = await create_user(
        db, email=body.email, password=body.password, role=body.role
    )
    await db.commit()
    await db.refresh(user)
    return user_response(user)


@users_router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    admin: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Change le rôle d'un compte ou le (dés)active.

    L'instance garde toujours au moins un admin actif, et un admin ne peut pas
    se rétrograder ni se désactiver lui-même (il se fermerait la porte).
    """
    user = await _get_user_or_404(db, user_id)
    if user.id == admin.user_id and (
        (body.role is not None and body.role != user.role) or body.disabled
    ):
        raise HTTPException(
            status_code=400, detail="Vous ne pouvez pas modifier votre propre accès."
        )
    removes_admin = (
        user.role == ROLE_ADMIN
        and user.disabled_at is None
        and (
            (body.role is not None and body.role != ROLE_ADMIN) or body.disabled is True
        )
    )
    if removes_admin and await count_active_admins(db) <= 1:
        raise HTTPException(
            status_code=400, detail="L'instance doit garder au moins un administrateur."
        )
    if body.role is not None:
        user.role = body.role
    if body.disabled is True and user.disabled_at is None:
        user.disabled_at = utcnow()
        await revoke_user_sessions(db, user.id)
    elif body.disabled is False:
        user.disabled_at = None
    await db.commit()
    await db.refresh(user)
    return user_response(user)


@users_router.post("/{user_id}/password", status_code=204)
async def reset_user_password(
    user_id: uuid.UUID,
    body: PasswordReset,
    _admin: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Définit un nouveau mot de passe et coupe toutes les sessions du compte."""
    user = await _get_user_or_404(db, user_id)
    user.password_hash = await hash_password(body.password)
    await revoke_user_sessions(db, user.id)
    await db.commit()


@invitations_router.get("", response_model=list[InvitationResponse])
async def list_invitations(
    _admin: Principal = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> list[InvitationResponse]:
    """Invitations encore utilisables (ni utilisées, ni révoquées, ni expirées)."""
    now = utcnow()
    rows = (
        await db.execute(
            select(Invitation)
            .where(Invitation.used_at.is_(None), Invitation.revoked_at.is_(None))
            .order_by(Invitation.created_at.desc())
        )
    ).scalars()
    return [
        InvitationResponse.model_validate(i, from_attributes=True)
        for i in rows
        if _aware(i.expires_at) > now
    ]


@invitations_router.post("", response_model=InvitationCreated, status_code=201)
async def create_invitation(
    body: InvitationCreate,
    admin: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> InvitationCreated:
    token = new_token()
    invitation = Invitation(
        role=body.role,
        token_hash=hash_token(token),
        created_by=admin.user_id,
        expires_at=utcnow() + timedelta(days=settings.invitation_days),
    )
    db.add(invitation)
    await db.commit()
    await db.refresh(invitation)
    return InvitationCreated(
        invitation=InvitationResponse.model_validate(invitation, from_attributes=True),
        token=token,
    )


@invitations_router.delete("/{invitation_id}", status_code=204)
async def revoke_invitation(
    invitation_id: uuid.UUID,
    _admin: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> None:
    invitation = await db.get(Invitation, invitation_id)
    if invitation is None:
        raise HTTPException(status_code=404, detail="Invitation introuvable.")
    if invitation.revoked_at is None:
        invitation.revoked_at = utcnow()
        await db.commit()
