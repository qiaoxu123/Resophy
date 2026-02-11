"""
Centralized configuration loaded from environment variables.

Supports both Docker (env vars) and local development (.env file).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _env_int(key: str, default: int = 0) -> int:
    raw = os.environ.get(key, "")
    try:
        return int(raw)
    except (ValueError, TypeError):
        return default


def _env_bool(key: str, default: bool = False) -> bool:
    raw = os.environ.get(key, "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default


@dataclass(frozen=True)
class DatabaseConfig:
    """Resophy's own MySQL database."""
    host: str = field(default_factory=lambda: _env("DB_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _env_int("DB_PORT", 3306))
    name: str = field(default_factory=lambda: _env("DB_NAME", "resophy"))
    user: str = field(default_factory=lambda: _env("DB_USER", "resophy"))
    password: str = field(default_factory=lambda: _env("DB_PASSWORD", ""))
    charset: str = "utf8mb4"
    pool_size: int = field(default_factory=lambda: _env_int("DB_POOL_SIZE", 5))

    @property
    def dsn(self) -> str:
        return (
            f"mysql+pymysql://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.name}"
            f"?charset={self.charset}"
        )


@dataclass(frozen=True)
class FlarumConfig:
    """Flarum database connection for user authentication."""
    db_host: str = field(default_factory=lambda: _env("FLARUM_DB_HOST", "127.0.0.1"))
    db_port: int = field(default_factory=lambda: _env_int("FLARUM_DB_PORT", 3306))
    db_name: str = field(default_factory=lambda: _env("FLARUM_DB_NAME", "flarum_kyrfa5"))
    db_user: str = field(default_factory=lambda: _env("FLARUM_DB_USER", ""))
    db_password: str = field(default_factory=lambda: _env("FLARUM_DB_PASSWORD", ""))
    db_prefix: str = field(default_factory=lambda: _env("FLARUM_DB_PREFIX", "flarum_"))
    api_url: str = field(default_factory=lambda: _env("FLARUM_API_URL", ""))

    @property
    def users_table(self) -> str:
        return f"{self.db_prefix}users"


@dataclass(frozen=True)
class AppConfig:
    """Top-level application settings."""
    secret_key: str = field(default_factory=lambda: _env("SECRET_KEY", "dev-only-key"))
    host: str = field(default_factory=lambda: _env("RESOPHY_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: _env_int("RESOPHY_PORT", 7191))
    papers_dir: str = field(default_factory=lambda: _env("PAPERS_DIR", "./papers"))
    debug: bool = field(default_factory=lambda: _env_bool("RESOPHY_DEBUG", False))
    redis_url: str = field(default_factory=lambda: _env("REDIS_URL", ""))

    db: DatabaseConfig = field(default_factory=DatabaseConfig)
    flarum: FlarumConfig = field(default_factory=FlarumConfig)


def load_config() -> AppConfig:
    """Load configuration from environment. Call once at startup."""
    # Try loading .env for local development
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    return AppConfig()
