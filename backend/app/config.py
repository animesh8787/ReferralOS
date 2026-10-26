from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = f"sqlite:///{(ROOT / 'data' / 'referralos.db').as_posix()}"
    data_dir: Path = ROOT / "data"
    app_kek: str = ""  # base64 32-byte key-encryption key; dev falls back to data/.kek
    cookie_secure: bool = False
    session_hours: int = 24 * 7
    tasks_inline: bool = False  # tests/dev: run background tasks synchronously
    adapter_mode: str = "mock"  # mock | real
    google_client_id: str = ""  # Gmail OAuth app (optional; unset = mock mode only)
    google_client_secret: str = ""
    cors_origins: list[str] = ["http://localhost:3000"]
    require_email_verification: bool = True
    # hard maximums for outbound email, below the published Gmail limits
    hard_max_daily_emails: int = 100
    hard_max_per_company_daily: int = 20


@lru_cache
def get_settings() -> Settings:
    return Settings()
