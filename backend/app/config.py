from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(REPO_DIR / ".env"), str(BACKEND_DIR / ".env")),
        extra="ignore",
    )

    env: str = "dev"  # dev | prod
    app_name: str = "SocialAgent"
    app_base_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:5173"

    database_url: str = f"sqlite+aiosqlite:///{(BACKEND_DIR / 'data' / 'dev.db').as_posix()}"

    jwt_secret: str = "dev-only-jwt-secret-change-me"
    token_encryption_key: str = ""  # Fernet key; generated per process in dev if empty
    media_signing_secret: str = "dev-only-media-secret-change-me"
    internal_shared_secret: str = "dev-only-internal-secret-change-me"
    admin_emails: str = ""

    # LLM providers, tried in this order (only those with keys). "anthropic" uses the native Claude SDK.
    llm_providers: str = "gemini,groq,anthropic"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    groq_vision_model: str = "qwen/qwen3.8-27b"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_whisper_model: str = "whisper-large-v3-turbo"
    transcribe_provider: str = "auto"  # auto (Groq if key, else local) | groq | local

    anthropic_api_key: str = ""
    claude_model: str = "claude-opus-5-5"

    whisper_model: str = "small"
    whisper_compute_type: str = "int8"
    whisper_model_dir: str = ""

    ig_app_id: str = ""
    ig_app_secret: str = ""
    ig_redirect_uri: str = ""
    ig_graph_version: str = ""  # empty = unversioned (app default)
    publish_dry_run: bool = False  # dev only: pretend to publish when Instagram isn't configured

    gateway_url: str = "http://127.0.0.1:3001"
    media_dir: str = str(BACKEND_DIR / "data" / "media")
    static_dir: str = str(BACKEND_DIR / "app" / "static")
    assets_dir: str = str(REPO_DIR / "assets")

    default_timezone: str = "Asia/Karachi"
    render_engine: str = "ffmpeg"  # ffmpeg | hyperframes (falls back to ffmpeg on any error)
    hyperframes_cli: str = ""  # path to node_modules/hyperframes/bin/hyperframes.mjs
    hyperframes_workers: str = "auto"
    max_video_seconds: int = 180
    max_upload_mb: int = 100
    max_revisions: int = 3
    render_concurrency: int = 1

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"

    @property
    def admin_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.admin_emails.split(",") if e.strip()}

    @property
    def instagram_redirect_uri(self) -> str:
        return self.ig_redirect_uri or f"{self.app_base_url.rstrip('/')}/api/instagram/callback"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
