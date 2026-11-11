import io
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from docx import Document

from services.api.config import settings
from services.api.database import init_db, get_db
from services.api.main import app
from services.worker.execution import deadline, check_deadline, execution_lease
from services.worker.queue import JobQueueRepository
from services.worker.lifecycle import PermanentJobError


@pytest.fixture(autouse=True)
def archive(tmp_path, monkeypatch):
    for key, value in {"data_dir": str(tmp_path), "db_path": str(tmp_path / "archive.db"),
                       "storage_dir": str(tmp_path / "files"), "backup_dir": str(tmp_path / "backups"),
                       "enable_background_worker": False, "session_auth_required": False}.items():
        monkeypatch.setattr(settings, key, value)
    settings.ensure_dirs()
    init_db()


def test_card_persistence_and_lossless_persian_word():
    original = "متنِ اصلی با نیم‌فاصله\nABC-123 و ي و ك بدون تغییر"
    with TestClient(app) as client:
        result = client.post("/api/v1/files/import", files={"file": ("source.txt", original.encode(), "text/plain")})
        assert result.status_code == 200
        fid = result.json()["id"]
        card_url = f"/api/v1/files/{fid}/card"
        r = client.put(card_url, json={"folder_path": "مجموعه/اسناد", "subject": "سند آموزشی",
                                    "notes": "یادداشت فارسی", "source_reference": "مرجع اصلی"})
        assert r.status_code == 200
        init_db()  # existing archives migrate without losing saved fields
        assert client.get(card_url).json()["folder_path"] == "مجموعه/اسناد"
        assert len(client.get("/api/v1/files", params={"folder_path": "مجموعه/اسناد"}).json()) == 1
        assert client.get("/api/v1/files", params={"folder_path": "دیگر"}).json() == []
        # Export the reviewed raw text, rather than normalized FTS text.
        text = "اصلاح دستی: ي ك ۱۲۳\nEnglish / فارسی"
        assert client.patch(f"/api/v1/files/{fid}/pages/1", json={"raw_text": text}).status_code == 200
        response = client.get(f"/api/v1/files/{fid}/document-word")
        assert response.status_code == 200
        doc = Document(io.BytesIO(response.content))
        paragraphs = [p.text for p in doc.paragraphs]
        assert all(line in paragraphs for line in text.split("\n"))
        assert any("یادداشت فارسی" in p for p in paragraphs)
        with zipfile.ZipFile(io.BytesIO(response.content)) as package:
            xml = package.read("word/document.xml").decode()
            assert "w:bidi" in xml and "w:szCs" in xml and "w:bidiVisual" in xml


def test_media_evidence_and_manual_override():
    image = Image.new("RGB", (32, 24), "white")
    stream = io.BytesIO()
    image.save(stream, "PNG")
    with TestClient(app) as client:
        r = client.post("/api/v1/files/import?async_mode=true", files={"file": ("Screenshot.png", stream.getvalue(), "image/png")}, data={"folder_path": "تصاویر/آموزش"})
        fid = r.json()["id"]
        url = f"/api/v1/files/{fid}/card"
        assert client.get(url).json()["detected_media_kind"] == "اسکرین‌شات"
        assert client.get(url).json()["folder_path"] == "تصاویر/آموزش"
        r = client.put(url, json={"media_kind": "تصویر گرافیکی"})
        assert r.json()["media_kind"] == "تصویر گرافیکی"
        assert client.put(url, json={"media_kind": "invalid"}).status_code == 422
        assert len(client.get("/api/v1/files", params={"media_kind": "تصویر گرافیکی"}).json()) == 1
        assert client.get("/api/v1/files/missing/card").status_code == 404


def test_expired_deadline_stops_processing():
    token = deadline.set(time.monotonic() - 1)
    try:
        with pytest.raises(PermanentJobError) as error:
            check_deadline()
        assert error.value.code == "JOB_TIMEOUT"
    finally:
        deadline.reset(token)


def test_authentication_for_card_changes(monkeypatch):
    with TestClient(app) as client:
        fid = client.post("/api/v1/files/import", files={"file": ("test.txt", b"test content", "text/plain")}).json()["id"]
        monkeypatch.setattr(settings, "session_auth_required", True)
        url = f"/api/v1/files/{fid}/card"
        assert client.put(url, json={"subject": "test"}).status_code == 401
        token = client.get("/api/v1/auth/session").json()["session_token"]
        assert client.put(url, json={"subject": "test"}, headers={"X-Saher-Session-Token": token}).status_code == 200


def test_lease_renews_during_slow_processing_and_rejects_stale_failure():
    with TestClient(app) as client:
        item = client.post("/api/v1/files/import?async_mode=true", files={"file": ("slow.txt", b"lease test", "text/plain")}).json()
        job = JobQueueRepository.claim_next_job("first", lease_seconds=5, specific_job_id=item["latest_job_id"])
        with execution_lease(job.id, "first", 5, 30):
            time.sleep(6)
            assert JobQueueRepository.recover_expired_leases() == 0
        with get_db() as conn:
            conn.execute("UPDATE jobs SET worker_id = 'second' WHERE id = ?", (job.id,))
        result = JobQueueRepository.mark_job_failed_or_retry(job.id, "first", "OLD", "stale worker")
        assert result.state == "RUNNING" and result.worker_id == "second"
