import os
import secrets
from typing import List
from pydantic import BaseModel, Field


def _parse_origins_env() -> List[str]:
    default_origins = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:8765",
        "http://127.0.0.1:8765",
        "app://.",
    ]
    raw_env = os.environ.get("SAHER_ALLOWED_ORIGINS", "")
    if raw_env.strip():
        for item in raw_env.split(","):
            cleaned = item.strip().rstrip("/")
            if cleaned and cleaned not in default_origins:
                default_origins.append(cleaned)

    for env_key in ("APP_URL", "SHARED_APP_URL", "VITE_API_BASE_URL"):
        val = os.environ.get(env_key, "").strip().rstrip("/")
        if val and val not in default_origins:
            default_origins.append(val)

    return default_origins


class Settings(BaseModel):
    app_name: str = "SAHER Offline Archive API"
    app_version: str = "0.3.0"
    api_prefix: str = "/api/v1"

    # Operational mode: production archives start empty unless demo_mode is explicitly enabled
    demo_mode: bool = Field(
        default_factory=lambda: os.environ.get("SAHER_DEMO_MODE", "false").lower() in ("1", "true", "yes")
    )

    # Storage settings
    base_dir: str = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    data_dir: str = os.path.join(base_dir, "data")
    db_path: str = os.path.join(data_dir, "saher.db")
    storage_dir: str = os.path.join(data_dir, "storage")
    backup_dir: str = os.path.join(data_dir, "backups")

    # Offline OCR Engine & Model Bundle settings (Milestone 3)
    ocr_engine: str = Field(
        default_factory=lambda: os.environ.get("SAHER_OCR_ENGINE", "tesseract")
    )
    ocr_model_dir: str = Field(
        default_factory=lambda: os.environ.get(
            "SAHER_OCR_MODEL_DIR",
            os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")), "data", "models", "tessdata")
            if os.path.isdir(
                os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")), "data", "models", "tessdata")
            )
            else "/usr/share/tesseract-ocr/5/tessdata",
        )
    )
    ocr_languages: str = Field(
        default_factory=lambda: os.environ.get("SAHER_OCR_LANGUAGES", "fas+eng")
    )
    ocr_render_scale: float = Field(
        default_factory=lambda: float(os.environ.get("SAHER_OCR_RENDER_SCALE", "2.0"))
    )
    pdf_digital_text_min_chars: int = Field(
        default_factory=lambda: int(os.environ.get("SAHER_PDF_MIN_TEXT_CHARS", "15"))
    )

    # Ingestion security & limits
    max_upload_size_bytes: int = Field(
        default_factory=lambda: int(os.environ.get("SAHER_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
    )
    upload_chunk_size: int = 65536
    allowed_extensions: list[str] = [
        ".txt", ".md", ".csv", ".json", ".log",
        ".pdf", ".docx",
        ".png", ".jpg", ".jpeg", ".webp", ".bmp"
    ]
    duplicate_policy: str = "reject"  # 'reject' prevents duplicate physical storage

    # Server & Local Security settings
    host: str = "127.0.0.1"
    port: int = Field(
        default_factory=lambda: int(os.environ.get("SAHER_API_PORT", "8765"))
    )
    cors_origins: list[str] = Field(default_factory=_parse_origins_env)

    # Session authentication for Electron / local desktop backend
    session_auth_required: bool = Field(
        default_factory=lambda: os.environ.get("SAHER_REQUIRE_SESSION_AUTH", "false").lower() in ("1", "true", "yes")
    )
    session_token: str = Field(
        default_factory=lambda: os.environ.get("SAHER_SESSION_TOKEN", "") or secrets.token_urlsafe(32)
    )

    # Durable Processing Engine & Worker settings
    enable_background_worker: bool = Field(
        default_factory=lambda: os.environ.get("SAHER_ENABLE_BACKGROUND_WORKER", "true").lower() in ("1", "true", "yes")
    )
    resource_mode: str = Field(
        default_factory=lambda: os.environ.get("SAHER_RESOURCE_MODE", "Balanced")
    )
    worker_concurrency: int = Field(
        default_factory=lambda: int(os.environ.get("SAHER_WORKER_CONCURRENCY", "2"))
    )
    job_lease_seconds: int = Field(
        default_factory=lambda: int(os.environ.get("SAHER_JOB_LEASE_SECONDS", "30"))
    )
    job_timeout_seconds: int = Field(
        default_factory=lambda: int(os.environ.get("SAHER_JOB_TIMEOUT_SECONDS", "60"))
    )
    job_max_retries: int = Field(
        default_factory=lambda: int(os.environ.get("SAHER_JOB_MAX_RETRIES", "3"))
    )
    worker_poll_interval_seconds: float = Field(
        default_factory=lambda: float(os.environ.get("SAHER_WORKER_POLL_SECONDS", "0.35"))
    )
    worker_heartbeat_ttl_seconds: int = Field(
        default_factory=lambda: int(os.environ.get("SAHER_WORKER_HEARTBEAT_TTL_SECONDS", "45"))
    )

    def ensure_dirs(self) -> None:
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.storage_dir, exist_ok=True)
        os.makedirs(self.backup_dir, exist_ok=True)


settings = Settings()
settings.ensure_dirs()
