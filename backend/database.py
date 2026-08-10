from collections.abc import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.config import settings

# Attente maximale d'un verrou d'écriture SQLite, en secondes. Le défaut de
# pysqlite est de 5 s : trop court dès que deux appareils postent leur delta en
# même temps (`broadcast_sync` réveille tous les abonnés SSE d'un coup, il n'y a
# pas de fenêtre calme). WAL sérialise les écrivains, et un `database is locked`
# remonte à l'agent en HTTPStatusError — hors de ses erreurs réessayables
# (`agent/sync_client.py`), donc la sync échoue sèchement jusqu'au prochain
# déclenchement launchd. 30 s coûtent une attente, pas un échec.
SQLITE_BUSY_TIMEOUT_SECONDS = 30

_connect_args: dict[str, object] = {}
if make_url(settings.database_url).get_backend_name() == "sqlite":
    _connect_args["timeout"] = SQLITE_BUSY_TIMEOUT_SECONDS

engine = create_async_engine(
    settings.database_url, echo=False, connect_args=_connect_args
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


if engine.dialect.name == "sqlite":

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record) -> None:
        """Activer les PRAGMA SQLite (clés étrangères + WAL) à chaque connexion."""
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
        finally:
            cursor.close()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session
