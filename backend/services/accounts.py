"""Comptes : mots de passe, jetons de session, invitations.

Tout ce qui touche à un secret passe par ici, pour qu'une seule règle vaille
partout :

- mot de passe → argon2id (`argon2-cffi`), calculé hors de la boucle asyncio ;
- jeton (session, appareil, invitation) → 32 octets aléatoires, montrés une
  seule fois au client, stockés en SHA-256. Un jeton volé dans une sauvegarde
  de la base ne sert donc à rien ;
- email → minuscules et espaces retirés, à l'écriture comme à la lecture.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.models.device import Device
from backend.models.user import (
    ROLE_ADMIN,
    SESSION_DEVICE,
    SESSION_WEB,
    AuthSession,
    User,
)

logger = logging.getLogger(__name__)

PASSWORD_MIN_LENGTH = 10
# Au-delà, argon2 hache quand même, mais rien ne justifie d'accepter un corps
# arbitraire à hacher à chaque tentative.
PASSWORD_MAX_LENGTH = 256

# Fréquence maximale d'écriture de `last_used_at` (et du glissement de
# l'expiration web) : une requête sur deux écrirait sinon en base.
TOUCH_INTERVAL = timedelta(minutes=5)

_hasher = PasswordHasher()
# Haché factice : vérifier un email inconnu coûte autant qu'un email connu, ce
# qui ne révèle pas par le temps de réponse quels comptes existent.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def normalize_email(email: str) -> str:
    return email.strip().lower()


def new_token() -> str:
    """Return a fresh random secret (URL-safe, 256 bits)."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """SHA-256 hex digest of a token, as stored in the database."""
    return hashlib.sha256(token.encode("utf-8", "surrogatepass")).hexdigest()


async def hash_password(password: str) -> str:
    return await asyncio.to_thread(_hasher.hash, password)


async def verify_password(password_hash: str | None, password: str) -> bool:
    """Vérifie un mot de passe ; `password_hash=None` simule un compte absent."""

    def _verify() -> bool:
        try:
            return _hasher.verify(password_hash or _DUMMY_HASH, password)
        except (VerificationError, InvalidHashError):
            return False

    ok = await asyncio.to_thread(_verify)
    return ok and password_hash is not None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    """SQLite rend des dates naïves : elles sont en UTC."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


# ---------- Utilisateurs ----------


async def count_users(db: AsyncSession) -> int:
    return (await db.execute(select(func.count()).select_from(User))).scalar_one()


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == normalize_email(email)))
    return result.scalar_one_or_none()


async def count_active_admins(db: AsyncSession) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(User)
        .where(User.role == ROLE_ADMIN, User.disabled_at.is_(None))
    )
    return result.scalar_one()


async def create_user(
    db: AsyncSession, *, email: str, password: str, role: str
) -> User:
    user = User(
        email=normalize_email(email),
        password_hash=await hash_password(password),
        role=role,
    )
    db.add(user)
    await db.flush()
    return user


async def adopt_orphan_devices(db: AsyncSession, user: User) -> int:
    """Rattache au compte les appareils connus d'avant les comptes.

    Appelé à la création du premier admin : un serveur mis à jour garde ses Mac,
    qui continuent de synchroniser avec le token hérité en attendant leur jeton.
    """
    result = await db.execute(
        update(Device)
        .where(Device.owner_user_id.is_(None))
        .values(owner_user_id=user.id)
    )
    return result.rowcount or 0


async def bootstrap_admin_from_env(db: AsyncSession) -> User | None:
    """Crée le premier admin depuis `FONTSYNC_ADMIN_EMAIL`/`_PASSWORD`.

    Sans effet si l'un manque ou si un compte existe déjà : ces variables ne
    servent qu'au tout premier démarrage d'une installation scriptée.
    """
    email = normalize_email(settings.fontsync_admin_email)
    password = settings.fontsync_admin_password
    if not email or not password:
        return None
    if await count_users(db) > 0:
        return None
    if len(password) < PASSWORD_MIN_LENGTH:
        logger.error(
            "FONTSYNC_ADMIN_PASSWORD ignoré : %d caractères minimum.",
            PASSWORD_MIN_LENGTH,
        )
        return None
    user = await create_user(db, email=email, password=password, role=ROLE_ADMIN)
    adopted = await adopt_orphan_devices(db, user)
    await db.commit()
    logger.info(
        "Compte admin créé depuis l'environnement (%d appareil(s) rattaché(s)).",
        adopted,
    )
    return user


# ---------- Sessions ----------


async def create_session(
    db: AsyncSession,
    user: User,
    *,
    kind: str,
    label: str | None = None,
    device_id: uuid.UUID | None = None,
) -> str:
    """Ouvre une session et retourne le jeton en clair (seule fois où il existe)."""
    token = new_token()
    now = utcnow()
    db.add(
        AuthSession(
            user_id=user.id,
            token_hash=hash_token(token),
            kind=kind,
            label=(label or "")[:200] or None,
            device_id=device_id,
            last_used_at=now,
            expires_at=(
                now + timedelta(days=settings.web_session_days)
                if kind == SESSION_WEB
                else None
            ),
        )
    )
    await db.flush()
    return token


@dataclass(frozen=True)
class ResolvedSession:
    session_id: uuid.UUID
    user_id: uuid.UUID
    role: str
    kind: str
    device_id: uuid.UUID | None


async def resolve_session(
    db: AsyncSession, token: str, *, kinds: tuple[str, ...]
) -> ResolvedSession | None:
    """Retrouve une session vivante (non révoquée, non expirée, compte actif).

    Rafraîchit au passage `last_used_at`, et l'expiration d'une session web,
    au plus une fois par `TOUCH_INTERVAL`.
    """
    result = await db.execute(
        select(AuthSession, User)
        .join(User, User.id == AuthSession.user_id)
        .where(
            AuthSession.token_hash == hash_token(token),
            AuthSession.revoked_at.is_(None),
            AuthSession.kind.in_(kinds),
            User.disabled_at.is_(None),
        )
    )
    row = result.first()
    if row is None:
        return None
    session, user = row
    now = utcnow()
    expires_at = _aware(session.expires_at)
    if expires_at is not None and expires_at <= now:
        return None
    last_used = _aware(session.last_used_at)
    if last_used is None or now - last_used >= TOUCH_INTERVAL:
        session.last_used_at = now
        if session.kind == SESSION_WEB:
            session.expires_at = now + timedelta(days=settings.web_session_days)
        await db.commit()
    return ResolvedSession(
        session_id=session.id,
        user_id=user.id,
        role=user.role,
        kind=session.kind,
        device_id=session.device_id,
    )


async def revoke_user_sessions(
    db: AsyncSession, user_id: uuid.UUID, *, keep: uuid.UUID | None = None
) -> int:
    stmt = (
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    if keep is not None:
        stmt = stmt.where(AuthSession.id != keep)
    result = await db.execute(stmt)
    return result.rowcount or 0


SESSION_KINDS = (SESSION_WEB, SESSION_DEVICE)


# ---------- Limite de tentatives ----------


class LoginRateLimiter:
    """Fenêtre glissante d'échecs de connexion, en mémoire.

    Une clé par IP et une par email : bloquer l'IP seule laisse deviner un
    mot de passe depuis plusieurs adresses, bloquer l'email seul laisse une
    adresse essayer tous les comptes. Un serveur, un process : la mémoire
    suffit, et un redémarrage qui remet les compteurs à zéro ne change rien
    d'utile pour un attaquant (5 essais de plus).
    """

    def __init__(self, max_failures: int = 5, window_seconds: float = 60.0) -> None:
        self.max_failures = max_failures
        self.window = window_seconds
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def _recent(self, key: str, now: float) -> deque[float]:
        hits = self._failures[key]
        while hits and now - hits[0] > self.window:
            hits.popleft()
        return hits

    def blocked(self, *keys: str) -> bool:
        now = time.monotonic()
        return any(len(self._recent(k, now)) >= self.max_failures for k in keys)

    def record_failure(self, *keys: str) -> None:
        now = time.monotonic()
        for key in keys:
            self._recent(key, now).append(now)

    def reset(self, *keys: str) -> None:
        for key in keys:
            self._failures.pop(key, None)

    def clear(self) -> None:
        self._failures.clear()


login_rate_limiter = LoginRateLimiter()
