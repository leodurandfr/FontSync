"""Fixtures partagées pour les tests backend.

Les fixtures de fonts « réelles » (`tests/fixtures/*.otf|ttf`) sont des polices
commerciales volontairement non committées (cf. `.gitignore`). Pour que la suite
A6 reste exécutable partout (CI, Docker, clone neuf), on génère ici de **vraies**
fonts TTF valides et parsables avec fontTools : table `name`, `OS/2`, `cmap`
(alphabet latin complet → script « Latin » détecté), glyphes réels.
"""

import io
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from backend import auth
from backend.config import settings
from backend.database import get_db
from backend.main import app

# Importer le package modèles enregistre toutes les tables sur Base.metadata.
from backend.models import Base
from backend.routers import fonts as fonts_router
from backend.routers import sync as sync_router
from backend.services.storage import FilesystemStorage

# Alphabet latin de base (>= 10 codepoints → script « Latin » détecté par
# l'analyzer, seuil `_SCRIPT_MIN_CODEPOINTS = 10`).
_LATIN_CODEPOINTS = (
    list(range(0x41, 0x5B))  # A-Z
    + list(range(0x61, 0x7B))  # a-z
    + list(range(0x30, 0x3A))  # 0-9
    + [0x20]  # espace
)

# fsSelection : bit 6 = REGULAR, bit 0 = ITALIC.
_FS_REGULAR = 1 << 6
_FS_ITALIC = 1 << 0


def build_ttf(
    *,
    family: str = "Test Sans",
    subfamily: str = "Regular",
    weight_class: int = 400,
    width_class: int = 5,
    italic: bool = False,
    monospace: bool = False,
    extra_codepoints: list[int] | None = None,
    variable_axes: list[tuple[str, float, float, float]] | None = None,
) -> bytes:
    """Construit une vraie font TTF en mémoire et retourne ses octets.

    Chaque appel produit un fichier valide (magic ``\\x00\\x01\\x00\\x00``) avec
    des métadonnées parsables. Faire varier ``family``/``subfamily`` change le
    contenu binaire, donc le hash SHA-256 → deux fonts distinctes.

    Args:
        variable_axes: si fourni, ajoute une table ``fvar`` et rend la font
            variable. Chaque entrée est un tuple ``(tag, min, default, max)``,
            par exemple ``[("wght", 100, 400, 900)]``.
    """
    codepoints = sorted(set(_LATIN_CODEPOINTS + (extra_codepoints or [])))
    glyph_names = [".notdef"] + [f"g{cp:04X}" for cp in codepoints]
    cmap = {cp: f"g{cp:04X}" for cp in codepoints}

    fb = FontBuilder(unitsPerEm=1000, isTTF=True)
    fb.setupGlyphOrder(glyph_names)
    fb.setupCharacterMap(cmap)

    empty_glyph = TTGlyphPen(None).glyph()
    fb.setupGlyf({name: empty_glyph for name in glyph_names})
    fb.setupHorizontalMetrics({name: (500, 0) for name in glyph_names})
    fb.setupHorizontalHeader(ascent=800, descent=-200)

    ps_name = f"{family}-{subfamily}".replace(" ", "")
    fb.setupNameTable(
        {
            "familyName": family,
            "styleName": subfamily,
            "uniqueFontIdentifier": ps_name,
            "fullName": f"{family} {subfamily}",
            "psName": ps_name,
            "version": "1.0",
        }
    )
    fb.setupOS2(
        usWeightClass=weight_class,
        usWidthClass=width_class,
        fsSelection=_FS_ITALIC if italic else _FS_REGULAR,
        sTypoAscender=800,
        sTypoDescender=-200,
        sTypoLineGap=0,
    )
    fb.setupPost(isFixedPitch=1 if monospace else 0)

    # `fvar` est ce que l'analyzer regarde pour décider `is_variable` : sa seule
    # présence suffit, les axes en fournissent le détail.
    if variable_axes:
        fb.setupFvar(
            axes=[
                (tag, minimum, default, maximum, f"Axis {tag}")
                for tag, minimum, default, maximum in variable_axes
            ],
            instances=[],
        )

    buffer = io.BytesIO()
    fb.save(buffer)
    return buffer.getvalue()


@pytest.fixture
def font_factory():
    """Retourne le constructeur de fonts (vraies TTF générées à la volée)."""
    return build_ttf


@pytest.fixture
def storage(tmp_path) -> FilesystemStorage:
    """Backend de stockage filesystem isolé dans le tmp_path du test."""
    return FilesystemStorage(base_path=str(tmp_path / "storage"))


@pytest_asyncio.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    """Session SQLite in-memory avec le schéma complet et les FK activées.

    StaticPool partage l'unique connexion in-memory entre `create_all` et la
    session (sinon chaque connexion verrait une base vide). On active aussi
    `PRAGMA foreign_keys=ON` comme en production (cf. `backend/database.py`).
    """
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
    async with session_maker() as session:
        yield session

    await engine.dispose()


# ---------- Client API complet (routeurs montés, auth armée) ----------

API_TOKEN = "test-secret-token"
AUTH_HEADERS = {"Authorization": f"Bearer {API_TOKEN}"}


@pytest.fixture
def _api_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "fontsync_token", API_TOKEN)
    monkeypatch.setattr(auth, "_generated_token", None)


@pytest_asyncio.fixture
async def api_client(tmp_path, _api_token) -> AsyncGenerator[AsyncClient, None]:
    """Client ASGI sur l'app réelle : DB in-memory + stockage isolé.

    Le stockage est surchargé pour les **deux** routeurs qui l'injectent (fonts
    et sync) : un vidage de corbeille écrit par l'un et lu par l'autre doit voir
    le même dossier, sinon les tests de purge passeraient pour de mauvaises
    raisons.
    """
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

    api_storage = FilesystemStorage(base_path=str(tmp_path / "api-storage"))
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[fonts_router.get_storage] = lambda: api_storage
    app.dependency_overrides[sync_router.get_storage] = lambda: api_storage

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    await engine.dispose()
