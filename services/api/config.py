import os
from pydantic import BaseModel, Field

class Settings(BaseModel):
    app_name: str = "SAHER Offline Archive API"
    app_version: str = "0.1.5"
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

    # Server settings
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://0.0.0.0:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "app://.",
    ]

    def ensure_dirs(self) -> None:
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.storage_dir, exist_ok=True)

settings = Settings()
settings.ensure_dirs()
