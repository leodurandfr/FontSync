from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:////data/fontsync.db"
    storage_backend: str = "filesystem"
    font_storage_path: str = "/data/fonts"

    # Token partagé d'instance (P1, PLAN-PUBLICATION.md). Secret unique vérifié
    # sur tout `/api/*`. Vide → un token est généré et loggé au boot (cf.
    # `backend.auth`) pour ne jamais démarrer un serveur ouvert. Pas de comptes
    # utilisateurs (ça reste le mode cloud / Phase 7).
    fontsync_token: str = ""

    # S3 settings (utilisés si storage_backend == "s3")
    s3_endpoint: str = ""
    s3_bucket: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = ""

    model_config = {"env_prefix": ""}


settings = Settings()
