from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./dev.db"
    replicate_api_token: str = ""
    storage_dir: Path = Path("storage")
    max_upload_mb: int = 25


settings = Settings()
