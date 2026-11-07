import pytest
import os
import tempfile
from fastapi.testclient import TestClient
from services.api.config import settings

# Override test database path
temp_dir = tempfile.mkdtemp()
settings.data_dir = temp_dir
settings.db_path = os.path.join(temp_dir, "test_saher.db")
settings.storage_dir = os.path.join(temp_dir, "test_storage")
os.makedirs(settings.storage_dir, exist_ok=True)

from services.api.main import app
from services.api.database import init_db

@pytest.fixture(autouse=True)
def setup_test_db():
    init_db()

def test_health_endpoint():
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["database"] == "sqlite3_fts5"

def test_initial_seed_and_stats():
    with TestClient(app) as client:
        response = client.get("/api/v1/stats")
        assert response.status_code == 200
        stats = response.json()
        assert stats["total_files"] >= 6
        assert stats["ready_files"] >= 3
        assert stats["attention_files"] >= 2

def test_list_and_search_files():
    with TestClient(app) as client:
        # 1. List all
        resp = client.get("/api/v1/files")
        assert resp.status_code == 200
        files = resp.json()
        assert len(files) >= 6

        # 2. Search query via FTS5
        search_resp = client.get("/api/v1/files?query=طراحی")
        assert search_resp.status_code == 200
        search_results = search_resp.json()
        assert len(search_results) >= 1
        assert any("طراحی" in f["title"] or "طراحی" in f["text"] for f in search_results)

def test_import_real_file_persistence_and_extraction():
    with TestClient(app) as client:
        file_content = "این یک سند آزمایشی برای بررسی پایداری پایگاه‌داده ساهر است. واژهٔ کلیدی: جستجوی_فوری".encode("utf-8")
        response = client.post(
            "/api/v1/files/import",
            files={"file": ("test_doc.txt", file_content, "text/plain")},
            data={"topic": "پژوهش"}
        )
        assert response.status_code == 200
        imported = response.json()
        file_id = imported["id"]
        assert imported["title"] == "test_doc.txt"
        assert "جستجوی_فوری" in imported["text"]
        assert imported["topic"] == "پژوهش"

        # Verify file persisted on disk and in database
        detail_resp = client.get(f"/api/v1/files/{file_id}")
        assert detail_resp.status_code == 200
        persisted = detail_resp.json()
        assert persisted["id"] == file_id
        assert persisted["sha256"] != ""

        # Test Tagging and Topic Update
        update_resp = client.patch(f"/api/v1/files/{file_id}", json={"topic": "فناوری", "status": "آماده"})
        assert update_resp.status_code == 200
        assert update_resp.json()["topic"] == "فناوری"

        tag_resp = client.post(f"/api/v1/files/{file_id}/tags", json={"tag": "برچسب_تست"})
        assert tag_resp.status_code == 200
        assert "برچسب_تست" in tag_resp.json()["tags"]
