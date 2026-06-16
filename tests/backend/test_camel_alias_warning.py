"""Régression : aucun `UnsupportedFieldAttributeWarning` (Pydantic) à l'usage.

Les schémas camelCase (`CamelModel` + `alias_generator`) déclenchaient, sur
certaines combinaisons FastAPI×Pydantic, un flot de
`UnsupportedFieldAttributeWarning` à chaque requête ayant **à la fois** un body
et un `response_model` (ex. `PATCH /api/devices/{id}`). L'aliasing restait
fonctionnel mais polluait la console. Corrigé en alignant les versions
(cf. requirements.txt). Ce test garde le contrat : zéro warning de ce type sur
un aller-retour register → patch, et l'alias camelCase fonctionne toujours.
"""

from __future__ import annotations

import warnings
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend.database import get_db
from backend.main import app
from backend.models.base import Base


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Client HTTP ASGI avec une base SQLite in-memory injectée via override."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _fk_on(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_maker() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_no_unsupported_field_attribute_warning(client: AsyncClient) -> None:
    reg = await client.post(
        "/api/devices/register",
        json={"name": "Mac", "hostname": "h1", "os": "macos"},
    )
    assert reg.status_code == 201
    device_id = reg.json()["id"]

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        # Endpoint avec body (DeviceUpdate) + response_model (DeviceResponse).
        patch = await client.patch(
            f"/api/devices/{device_id}", json={"syncStatus": "idle"}
        )

    assert patch.status_code == 200
    # L'alias camelCase fonctionne toujours (entrée ET sortie).
    assert patch.json()["syncStatus"] == "idle"

    offenders = [
        str(w.message)
        for w in caught
        if type(w.message).__name__ == "UnsupportedFieldAttributeWarning"
    ]
    assert offenders == [], f"Warnings inattendus : {offenders[:3]}"
