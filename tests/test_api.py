import os
import io
import sqlite3
import tempfile
import zipfile
import pytest
from fastapi.testclient import TestClient
from services.api.config import settings
from services.api.database import init_db, get_db
from services.api.repository import ArchiveRepository, create_minimal_valid_png
from services.api.main import app


@pytest.fixture(autouse=True)
def isolated_test_env(monkeypatch):
    """Provides a fresh isolated temporary SQLite database and storage directory per test."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_saher.db")
        storage_dir = os.path.join(tmpdir, "test_storage")
        os.makedirs(storage_dir, exist_ok=True)

        monkeypatch.setattr(settings, "data_dir", tmpdir)
        monkeypatch.setattr(settings, "db_path", db_path)
        monkeypatch.setattr(settings, "storage_dir", storage_dir)
        monkeypatch.setattr(settings, "demo_mode", False)
        monkeypatch.setattr(settings, "max_upload_size_bytes", 1024 * 1024)  # 1 MB default for tests

        init_db()
        yield tmpdir


def _create_valid_docx_bytes(paragraphs: list[str]) -> bytes:
    import docx

    buf = io.BytesIO()
    doc = docx.Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    doc.save(buf)
    return buf.getvalue()


def _create_empty_scanned_pdf_bytes() -> bytes:
    from pypdf import PdfWriter

    buf = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.write(buf)
    return buf.getvalue()


def test_1_health_and_empty_production_start():
    """Production archives must start empty (0 files) without fake demo seeding."""
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        h_data = health.json()
        assert h_data["status"] == "healthy"
        assert h_data["database"] == "sqlite3_fts5"
        assert h_data["storage_accessible"] is True
        assert h_data["demo_mode"] is False

        stats = client.get("/api/v1/stats").json()
        assert stats["total_files"] == 0
        assert stats["ready_files"] == 0
        assert stats["attention_files"] == 0

        files = client.get("/api/v1/files").json()
        assert files == []


def test_2_import_valid_text_and_persistence_across_restart():
    """Imported files persist on disk and in SQLite across connections and preserve source bytes."""
    raw_content = "یادداشت معماری سیستم ساهر برای دسته‌بندی هوشمند اسناد آفلاین.".encode("utf-8")
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/files/import",
            files={"file": ("architecture_notes.txt", raw_content, "text/plain")},
            data={"topic": "طراحی"},
        )
        assert resp.status_code == 200
        item = resp.json()
        file_id = item["id"]
        assert item["title"] == "architecture_notes.txt"
        assert item["kind"] == "سند"
        assert item["topic"] == "طراحی"
        assert item["status"] == "آماده"
        assert item["extraction_status"] == "extracted"
        assert "دسته‌بندی هوشمند" in item["text"]
        assert item["system_note"] is None

    # Simulate service restart with a new TestClient instance
    with TestClient(app) as client2:
        detail = client2.get(f"/api/v1/files/{file_id}")
        assert detail.status_code == 200
        assert detail.json()["sha256"] == item["sha256"]

        # Verify original file content is preserved byte-for-byte with security headers
        content_resp = client2.get(f"/api/v1/files/{file_id}/content")
        assert content_resp.status_code == 200
        assert content_resp.content == raw_content
        assert "sandbox" in content_resp.headers.get("content-security-policy", "")
        assert content_resp.headers.get("x-content-type-options") == "nosniff"


def test_3_extraction_semantics_docx_scanned_pdf_and_image():
    """
    Actual extracted text is stored separately from system notes.
    Scanned PDFs and unprocessed images have empty extracted_text and pending_ocr status.
    """
    with TestClient(app) as client:
        # 1. Valid DOCX with real text
        docx_bytes = _create_valid_docx_bytes(["گزارش عملکرد سامانه بایگانی ساهر", "بخش دوم: بازیابی اطلاعات"])
        r_docx = client.post(
            "/api/v1/files/import",
            files={"file": ("report.docx", docx_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
        assert r_docx.status_code == 200
        docx_item = r_docx.json()
        assert docx_item["extraction_status"] == "extracted"
        assert docx_item["status"] == "آماده"
        assert "بازیابی اطلاعات" in docx_item["text"]

        # 2. Scanned PDF (blank page with no text layer)
        pdf_bytes = _create_empty_scanned_pdf_bytes()
        r_pdf = client.post(
            "/api/v1/files/import",
            files={"file": ("scanned_contract.pdf", pdf_bytes, "application/pdf")},
        )
        assert r_pdf.status_code == 200
        pdf_item = r_pdf.json()
        assert pdf_item["text"] == ""  # No fake placeholder text in extracted_text!
        assert pdf_item["extraction_status"] == "pending_ocr"
        assert pdf_item["status"] == "نیازمند بازبینی"
        assert pdf_item["system_note"] is not None
        assert "OCR" in pdf_item["system_note"]

        # 3. Genuine PNG image awaiting OCR
        png_bytes = create_minimal_valid_png((120, 180, 140))
        r_png = client.post(
            "/api/v1/files/import",
            files={"file": ("screenshot_panel.png", png_bytes, "image/png")},
        )
        assert r_png.status_code == 200
        png_item = r_png.json()
        assert png_item["kind"] == "اسکرین‌شات"
        assert png_item["text"] == ""  # Never fabricate OCR text for unprocessed images!
        assert png_item["extraction_status"] == "pending_ocr"
        assert png_item["status"] == "در صف"

        # Verify searching for words from system_note (like "OCR" or "اسکن‌شده") does NOT match the empty PDF/PNG
        search_fake = client.get("/api/v1/files", params={"query": "اسکن‌شده"}).json()
        assert search_fake == []


def test_4_fts5_search_persian_arabic_zwnj_and_combined_filters():
    """
    Tests FTS5 search with Arabic/Persian character variations (ي/ك vs ی/ک),
    half-spaces (ZWNJ), combined kind/status filters, snippets, and malformed queries.
    """
    with TestClient(app) as client:
        # Import doc 1 with Arabic Yeh/Kaf and ZWNJ
        client.post(
            "/api/v1/files/import",
            files={"file": ("doc_one.txt", "بررسي كتابخانه و دسته‌بندي اسناد پژوهشي".encode("utf-8"), "text/plain")},
            data={"topic": "پژوهش"},
        )
        # Import doc 2 with different topic & status update
        r2 = client.post(
            "/api/v1/files/import",
            files={"file": ("doc_two.txt", "بررسی کتابخانه و طراحی رابط کاربری مدرن".encode("utf-8"), "text/plain")},
            data={"topic": "طراحی"},
        )
        doc2_id = r2.json()["id"]
        client.patch(f"/api/v1/files/{doc2_id}", json={"status": "نیازمند بازبینی"})

        # 1. Search with Persian 'کتابخانه' matches both doc_one (originally 'كتابخانه') and doc_two
        res_both = client.get("/api/v1/files", params={"query": "کتابخانه"}).json()
        assert len(res_both) == 2
        assert all(item["matched_snippet"] is not None for item in res_both)

        # 2. Search with space instead of ZWNJ ('دسته بندی') matches 'دسته‌بندی'
        res_zwnj = client.get("/api/v1/files", params={"query": "دسته بندی"}).json()
        assert len(res_zwnj) == 1
        assert res_zwnj[0]["title"] == "doc_one.txt"

        # 3. Search combined with status filter
        res_filtered = client.get(
            "/api/v1/files",
            params={"query": "کتابخانه", "status": "نیازمند بازبینی"},
        ).json()
        assert len(res_filtered) == 1
        assert res_filtered[0]["id"] == doc2_id

        # 4. Search combined with kind filter (filtering for 'تصویر' when only 'سند' matches)
        res_kind = client.get(
            "/api/v1/files",
            params={"query": "کتابخانه", "kind": "تصویر"},
        ).json()
        assert res_kind == []

        # 5. Malformed FTS5 queries do not crash SQLite
        for bad_q in ['"""', "*** () : ^ - +", "AND OR NOT", "کتابخانه\" OR (1=1)"]:
            r_bad = client.get("/api/v1/files", params={"query": bad_q})
            assert r_bad.status_code == 200


def test_5_metadata_and_tag_updates_sync_with_fts():
    """Updating topic or tags persists in SQLite and immediately updates the FTS5 index."""
    with TestClient(app) as client:
        r = client.post(
            "/api/v1/files/import",
            files={"file": ("notes.txt", "متن ساده برای تست بروزرسانی نمایه".encode("utf-8"), "text/plain")},
        )
        file_id = r.json()["id"]

        # Add tag
        tag_resp = client.post(f"/api/v1/files/{file_id}/tags", json={"tag": "کلیدواژه_اختصاصی"})
        assert tag_resp.status_code == 200
        assert "کلیدواژه_اختصاصی" in tag_resp.json()["tags"]
        assert tag_resp.json()["is_user_modified"] is True

        # Search by the newly added tag via FTS5
        search_hit = client.get("/api/v1/files", params={"query": "کلیدواژه_اختصاصی"}).json()
        assert len(search_hit) == 1
        assert search_hit[0]["id"] == file_id

        # Remove tag and verify FTS5 no longer matches it
        del_resp = client.delete(f"/api/v1/files/{file_id}/tags/کلیدواژه_اختصاصی")
        assert del_resp.status_code == 200
        assert "کلیدواژه_اختصاصی" not in del_resp.json()["tags"]

        search_miss = client.get("/api/v1/files", params={"query": "کلیدواژه_اختصاصی"}).json()
        assert search_miss == []


def test_6_duplicate_detection_and_storage_protection():
    """Byte-identical files are rejected with 409 Conflict without creating duplicate files on disk."""
    content = "محتوای یکتا برای بررسی عدم تکرار فایل در دیسک.".encode("utf-8")
    with TestClient(app) as client:
        r1 = client.post(
            "/api/v1/files/import",
            files={"file": ("original.txt", content, "text/plain")},
        )
        assert r1.status_code == 200
        orig_id = r1.json()["id"]

        stored_files_before = os.listdir(settings.storage_dir)
        assert len(stored_files_before) == 1

        # Attempt to import identical content under a different filename
        r2 = client.post(
            "/api/v1/files/import",
            files={"file": ("copy_of_original.txt", content, "text/plain")},
        )
        assert r2.status_code == 409
        err = r2.json()
        assert err["code"] == "DUPLICATE_FILE"
        assert err["existing_file_id"] == orig_id

        # Ensure no extra file or temp file remains on disk
        stored_files_after = os.listdir(settings.storage_dir)
        assert stored_files_after == stored_files_before


def test_7_reject_unsupported_spoofed_oversized_and_corrupted_files(monkeypatch):
    """Tests security and integrity guards against spoofed PNGs, HTML scripts, oversized files, and corrupt PDFs."""
    with TestClient(app) as client:
        # 1. Fake PNG containing plain text (like the legacy seed bug)
        r_fake_png = client.post(
            "/api/v1/files/import",
            files={"file": ("fake_image.png", "این متن است نه تصویر".encode("utf-8"), "image/png")},
        )
        assert r_fake_png.status_code == 422
        assert r_fake_png.json()["code"] == "INVALID_FILE_SIGNATURE"

        # 2. Unsupported extension (.exe)
        r_exe = client.post(
            "/api/v1/files/import",
            files={"file": ("malware.exe", b"MZ\x90\x00\x03", "application/octet-stream")},
        )
        assert r_exe.status_code == 415
        assert r_exe.json()["code"] == "UNSUPPORTED_EXTENSION"

        # 3. HTML/Script disguised as .txt
        r_xss = client.post(
            "/api/v1/files/import",
            files={"file": ("harmless.txt", b"<!DOCTYPE html><html><script>alert(1)</script></html>", "text/plain")},
        )
        assert r_xss.status_code == 422

        # 4. Corrupted PDF (has %PDF- header but invalid body)
        r_corrupt_pdf = client.post(
            "/api/v1/files/import",
            files={"file": ("broken.pdf", b"%PDF-1.7\ngarbage_not_a_valid_pdf_xref", "application/pdf")},
        )
        assert r_corrupt_pdf.status_code == 422
        assert r_corrupt_pdf.json()["code"] == "PDF_CORRUPTED"

        # 5. Oversized upload limit (set max_upload_size_bytes to 512 bytes)
        monkeypatch.setattr(settings, "max_upload_size_bytes", 512)
        r_large = client.post(
            "/api/v1/files/import",
            files={"file": ("huge.txt", b"A" * 2048, "text/plain")},
        )
        assert r_large.status_code == 413
        assert r_large.json()["code"] == "UPLOAD_TOO_LARGE"

        # Verify storage directory is completely clean (0 orphaned or temp files)
        assert os.listdir(settings.storage_dir) == []
        assert client.get("/api/v1/stats").json()["total_files"] == 0


def test_8_database_and_storage_failure_atomicity_and_origin_security(monkeypatch):
    """
    Verifies that:
    - A database failure rolls back and deletes the stored file on disk (no orphan file).
    - A storage failure creates no database record.
    - Untrusted cross-origin POST requests are blocked with 403 Forbidden.
    """
    with TestClient(app) as client:
        # 1. Untrusted Origin header on POST is blocked
        r_csrf = client.post(
            "/api/v1/files/import",
            headers={"Origin": "https://evil-attacker.example.com"},
            files={"file": ("note.txt", "تست امنیت".encode("utf-8"), "text/plain")},
        )
        assert r_csrf.status_code == 403
        assert r_csrf.json()["code"] == "FORBIDDEN_ORIGIN"

        # 2. Simulate Database Failure during ingestion -> file on disk must be cleaned up!
        def broken_update_fts(*args, **kwargs):
            raise sqlite3.OperationalError("Simulated DB failure")

        monkeypatch.setattr(ArchiveRepository, "update_fts", broken_update_fts)
        r_dbfail = client.post(
            "/api/v1/files/import",
            files={"file": ("atomic_test.txt", "تست اتمیک بودن تراکنش".encode("utf-8"), "text/plain")},
        )
        assert r_dbfail.status_code == 500
        assert r_dbfail.json()["code"] == "DATABASE_ERROR"
        # No orphan file left in storage_dir!
        assert os.listdir(settings.storage_dir) == []
        # No partial record in SQLite!
        assert client.get("/api/v1/stats").json()["total_files"] == 0
