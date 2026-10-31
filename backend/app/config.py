"""Конфигурация приложения. Секреты — из переменных окружения / .env."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Корень проекта — на два уровня выше этого файла (backend/app -> backend -> root).
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_secret_key: str = "change-me"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    app_managed: bool = False
    app_secrets_dir: str = ""
    app_static_dir: str = ""
    app_installation_id: str = ""
    app_data_dir: str = str(PROJECT_ROOT / "data")
    database_url: str = ""

    # Bootstrap первого администратора (используется только при инициализации).
    app_first_admin_login: str = "admin"
    app_first_admin_password: str = "change-me"
    app_first_admin_name: str = "Administrator"

    # Внешние интеграции (этап 6+; до передачи ключей — моки).
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    ai_gemini_api_key: str = ""
    ai_deepseek_api_key: str = ""
    ai_priority_provider: str = "gemini"
    google_drive_folder_id: str = ""
    fxtunnel_token: str = ""

    def secret_value(self, name: str) -> str:
        if name not in {"operator", "bootstrap_password", "gemini", "telegram"} or not self.app_secrets_dir:
            return ""
        path = Path(self.app_secrets_dir) / name
        return path.read_text(encoding="utf-8").strip() if path.is_file() else ""

    @property
    def data_dir(self) -> Path:
        return Path(self.app_data_dir)

    @property
    def sqlalchemy_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.data_dir / 'hackathon.db').as_posix()}"

    @property
    def is_sqlite(self) -> bool:
        return self.sqlalchemy_url.startswith("sqlite")


settings = Settings()
