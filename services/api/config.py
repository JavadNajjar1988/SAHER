import os
from pydantic import BaseModel

class Settings(BaseModel):
    app_name: str = "SAHER Offline Archive API"
    app_version: str = "0.1.0"
    api_prefix: str = "/api/v1"
    
    # Storage settings
    base_dir: str = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    data_dir: str = os.path.join(base_dir, "data")
    db_path: str = os.path.join(data_dir, "saher.db")
    storage_dir: str = os.path.join(data_dir, "storage")
    
    # Server settings
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://0.0.0.0:3000",
    ]

settings = Settings()

# Ensure directories exist
os.makedirs(settings.data_dir, exist_ok=True)
os.makedirs(settings.storage_dir, exist_ok=True)
