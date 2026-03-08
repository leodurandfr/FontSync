from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://fontsync:fontsync@db:5432/fontsync"
    storage_backend: str = "filesystem"
    font_storage_path: str = "/data/fonts"

    # S3 settings (utilisés si storage_backend == "s3")
    s3_endpoint: str = ""
    s3_bucket: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = ""

    model_config = {"env_prefix": ""}


settings = Settings()
