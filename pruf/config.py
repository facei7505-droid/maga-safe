"""Настройки из переменных окружения. Секреты только из env, в коде их нет."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _env_list(name: str) -> tuple[str, ...]:
    raw = os.environ.get(name, "")
    return tuple(item.strip() for item in raw.split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("PRUF_DATA_DIR", ROOT / "data")))
    model_path: Path = field(default_factory=lambda: Path(os.environ.get("PRUF_MODEL_PATH", ROOT / "models" / "clf.joblib")))
    analyst_token: str = field(default_factory=lambda: os.environ.get("PRUF_ANALYST_TOKEN", ""))
    bank_tokens: tuple[str, ...] = field(default_factory=lambda: _env_list("PRUF_BANK_TOKENS"))
    dev_mode: bool = field(default_factory=lambda: os.environ.get("PRUF_DEV_MODE", "") == "1")
    hmac_key: str = field(default_factory=lambda: os.environ.get("PRUF_HMAC_KEY", ""))
    anthropic_api_key: str = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", ""))
    llm_model: str = field(default_factory=lambda: os.environ.get("PRUF_LLM_MODEL", "claude-opus-5-5"))
    telegram_token: str = field(default_factory=lambda: os.environ.get("TELEGRAM_BOT_TOKEN", ""))
    resolve_links: bool = field(default_factory=lambda: os.environ.get("PRUF_RESOLVE_LINKS", "") == "1")
    max_upload_bytes: int = field(default_factory=lambda: int(os.environ.get("PRUF_MAX_UPLOAD_BYTES", str(8 * 1024 * 1024))))
    rate_limit_per_minute: int = field(default_factory=lambda: int(os.environ.get("PRUF_RATE_LIMIT", "120")))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "pruf.db"

    @property
    def blob_dir(self) -> Path:
        return self.data_dir / "blobs"

    def effective_hmac_key(self) -> bytes:
        if self.hmac_key:
            return self.hmac_key.encode()
        if self.dev_mode:
            return b"pruf-dev-only-key"
        raise RuntimeError("PRUF_HMAC_KEY не задан (или включите PRUF_DEV_MODE=1 для локальной разработки)")


def load_settings() -> Settings:
    return Settings()
