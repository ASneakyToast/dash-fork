import os
from dataclasses import dataclass


def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None:
        raise RuntimeError(f"{name} is not set.")
    return value


@dataclass(frozen=True)
class Settings:
    database_url: str
    public_url: str
    redis_url: str
    hermes_base_url: str
    hermes_api_key: str
    hermes_model: str
    nango_url: str
    nango_public_url: str
    nango_connect_url: str
    nango_secret_key: str
    embed_model: str
    extract_model: str
    memory_base_url: str
    memory_api_key: str
    memory_top_k: int

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=_env("DATABASE_URL"),
            public_url=_env("PUBLIC_URL", "").rstrip("/"),
            redis_url=_env("REDIS_URL", "redis://localhost:6379/0"),
            hermes_base_url=_env("HERMES_BASE_URL", "http://localhost:8642/v1").rstrip("/"),
            hermes_api_key=_env("HERMES_API_KEY", ""),
            hermes_model=_env("HERMES_MODEL", "hermes-opus"),
            nango_url=_env("NANGO_URL", "http://localhost:3003").rstrip("/"),
            # Browser-facing addresses. Empty means "same as NANGO_URL".
            nango_public_url=_env("NANGO_PUBLIC_URL", "").rstrip("/"),
            nango_connect_url=_env("NANGO_CONNECT_URL", "").rstrip("/"),
            nango_secret_key=_env("NANGO_SECRET_KEY", ""),
            embed_model=_env("EMBED_MODEL", "amazon.titan-embed-text-v2:0"),
            extract_model=_env("EXTRACT_MODEL", "us.anthropic.claude-haiku-4-5-20251001-v1:0"),
            memory_base_url=_env("MEMORY_BASE_URL", "").rstrip("/"),
            memory_api_key=_env("MEMORY_API_KEY", ""),
            memory_top_k=int(_env("MEMORY_TOP_K", "8")),
        )
