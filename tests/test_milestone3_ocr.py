from __future__ import annotations

import io
import os
import time
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from services.api.config import settings
from services.api.database import init_db, get_db
from services.api.main import app
from services.ocr import OCRModelMissingError, TesseractOCREngine
from services.worker.queue import JobQueueRepository
from services.worker.runner import WorkerRunner, default_worker

FONT_PATH = Path(__file__).resolve().parent.parent / "data" / "models" / "fonts" / "Vazirmatn.ttf"


@pytest.fixture(autouse=True)
def isolated_m3_test_env(monkeypatch):
    """Provides an isolated temporary SQLite DB, storage dir, and backup dir per Milestone 3 test."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_saher_m3.db")
        storage_dir = os.path.join(tmpdir, "test_storage")
        backup_dir = os.path.join(tmpdir, "test_backups")
        os.makedirs(storage_dir, exist_ok=True)
        os.makedirs(backup_dir, exist_ok=True)

        monkeypatch.setattr(settings, "data_dir", tmpdir)
        monkeypatch.setattr(settings, "db_path", db_path)
        monkeypatch.setattr(settings, "storage_dir", storage_dir)
        monkeypatch.setattr(settings, "backup_dir", backup_dir)
        monkeypatch.setattr(settings, "demo_mode", False)
        monkeypatch.setattr(settings, "enable_background_worker", False)
        monkeypatch.setattr(settings, "session_auth_required", False)

        default_worker.stop()
        init_db()
        yield Path(tmpdir)
        default_worker.stop()


def _render_persian_page_image(lines: list[str], width: int = 1000, height: int = 480) -> Image.Image:
    """Render clean Persian/English text onto a white PIL image using Vazirmatn.ttf.
    Pillow's libraqm layout engine handles Persian glyph shaping and BiDi ordering natively.
    """
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(str(FONT_PATH), 34)
    y = 48
    for line in lines:
        draw.text((60, y), line, font=font, fill=(15, 23, 42))
        y += 72
    return img


def _build_scanned_pdf_bytes(pages_lines: list[list[str]]) -> bytes:
    """Create a multi-page scanned PDF where every page is a rasterized image (no digital text layer)."""
    pil_pages = [_render_persian_page_image(lines) for lines in pages_lines]
    buf = io.BytesIO()
    first, rest = pil_pages[0], pil_pages[1:]
    first.save(buf, format="PDF", resolution=150.0, save_all=True, append_images=rest)
    return buf.getvalue()


def _build_hybrid_pdf_bytes() -> bytes:
    """Create a 3-page hybrid PDF:
    - Page 1: Native digital PDF text layer
    - Page 2: Scanned raster image only (no digital text layer)
    - Page 3: Scanned raster image only (no digital text layer)
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(800, 500))
    c.setFont("Helvetica", 18)

    # Page 1: Digital text layer (>= 15 chars so extractor reads it directly without OCR)
    c.drawString(72, 400, "SAHER-HYBRID-PAGE-1: Digital text layer extracted directly without OCR.")
    c.drawString(72, 350, "Direct digital layer on page one for hybrid archive testing.")
    c.showPage()

    # Page 2: Scanned image only
    img_p2 = _render_persian_page_image([
        "صفحه دوم اسکن شده",
        "قرارداد هوشمندسازی بایگانی اسناد مالی",
        "کد پیگیری: SCAN-PAGE-202",
    ])
    p2_buf = io.BytesIO()
    img_p2.save(p2_buf, format="PNG")
    p2_buf.seek(0)
    c.drawImage(ImageReader(p2_buf), 0, 0, width=800, height=500)
    c.showPage()

    # Page 3: Scanned image only
    img_p3 = _render_persian_page_image([
        "صفحه سوم اسکن شده",
        "صورت‌جلسه کمیته امنیت و حفاظت داده‌ها",
        "کد پیگیری: SCAN-PAGE-303",
    ])
    p3_buf = io.BytesIO()
    img_p3.save(p3_buf, format="PNG")
    p3_buf.seek(0)
    c.drawImage(ImageReader(p3_buf), 0, 0, width=800, height=500)
    c.showPage()

    c.save()
    return buf.getvalue()


def test_m3_sample1_persian_image_ocr_and_search():
    """Sample 1: Upload a Persian + English raster image, run offline OCR via durable queue,
    verify raw_text, normalized_text, bounding boxes, Arabic/Persian character unification,
    and matched_page=1 in search results.
    """
    worker = WorkerRunner(worker_id="worker-m3-img")

    img = _render_persian_page_image([
        "سامانه هوشمند مدیریت آرشیو ساهر",
        "گزارش حسابرسی پروژه پردازش‌اسناد و تصاویر",
        "شناسه سند: SAHER-IMG-101",
    ])
    img_buf = io.BytesIO()
    img.save(img_buf, format="PNG")

    with TestClient(app) as client:
        t0 = time.perf_counter()
        resp = client.post(
            "/api/v1/files/import?async_mode=true",
            files={"file": ("persian_invoice_scan.png", img_buf.getvalue(), "image/png")},
            data={"topic": "مالی"},
        )
        assert resp.status_code == 200, resp.text
        uploaded = resp.json()
        file_id = uploaded["id"]
        assert uploaded["status"] == "در صف"

        processed = worker.process_one()
        assert processed is not None
        assert processed.state == "COMPLETED"
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        assert elapsed_ms > 0

        detail = client.get(f"/api/v1/files/{file_id}").json()
        assert detail["status"] == "آماده"
        assert detail["extraction_status"] == "extracted"
        assert detail["extraction_method"] == "ocr_image"

        pages = client.get(f"/api/v1/files/{file_id}/pages").json()
        assert len(pages) == 1
        p1 = pages[0]
        assert p1["page_number"] == 1
        assert p1["page_status"] == "extracted"
        assert p1["extraction_method"] == "ocr_image"
        assert "گزارش" in p1["raw_text"]
        assert "حسابرسی" in p1["normalized_text"]
        assert "پردازش‌اسناد" in p1["normalized_text"] or "پردازش اسناد" in p1["normalized_text"]
        assert len(p1["bboxes"]) >= 5
        assert p1["bboxes"][0]["width"] > 0 and p1["bboxes"][0]["height"] > 0

        # Search using Arabic character variant (ي) -> must match Persian ی on page 1
        search_resp = client.get("/api/v1/files", params={"query": "گزارش حسابرسي"})
        assert search_resp.status_code == 200
        items = search_resp.json()
        assert len(items) == 1
        assert items[0]["id"] == file_id
        assert items[0]["matched_page"] == 1
        assert 1 in items[0]["matched_pages"]


def test_m3_sample2_multipage_scanned_pdf_and_page_match():
    """Sample 2: Multi-page scanned Persian PDF (no digital text layer).
    Verifies per-page OCR, page preview rendering, and exact matched_page in search results.
    """
    worker = WorkerRunner(worker_id="worker-m3-scanned-pdf")

    pdf_bytes = _build_scanned_pdf_bytes([
        ["صفحه اول سند اسکن شده", "معماری پایگاه داده و نمایه‌سازی متون"],
        ["صفحه دوم سند اسکن شده", "قرارداد پشتیبانی سامانه هوشمند بایگانی"],
        ["صفحه سوم سند اسکن شده", "صورت‌جلسه امنیت اطلاعات سازمان"],
    ])

    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/files/import?async_mode=true",
            files={"file": ("scanned_contract_3pages.pdf", pdf_bytes, "application/pdf")},
        )
        assert resp.status_code == 200
        file_id = resp.json()["id"]

        processed = worker.process_one()
        assert processed is not None
        assert processed.state == "COMPLETED"

        pages = client.get(f"/api/v1/files/{file_id}/pages").json()
        assert len(pages) == 3
        for idx, page in enumerate(pages, start=1):
            assert page["page_number"] == idx
            assert page["extraction_method"] == "ocr_pdf_page"
            assert page["page_status"] == "extracted"
            assert len(page["bboxes"]) >= 3

        # Search for phrase on Page 2
        s_p2 = client.get("/api/v1/files", params={"query": "پشتیبانی سامانه"}).json()
        assert len(s_p2) == 1
        assert s_p2[0]["matched_page"] == 2

        # Search for phrase on Page 3
        s_p3 = client.get("/api/v1/files", params={"query": "امنیت اطلاعات سازمان"}).json()
        assert len(s_p3) == 1
        assert s_p3[0]["matched_page"] == 3

        # Verify page preview image endpoint returns PNG
        preview_resp = client.get(f"/api/v1/files/{file_id}/pages/2/preview")
        assert preview_resp.status_code == 200
        assert preview_resp.headers["content-type"] == "image/png"
        assert preview_resp.content.startswith(b"\x89PNG")


def test_m3_sample3_hybrid_pdf_digital_and_scanned_pages():
    """Sample 3: Hybrid PDF where Page 1 has a usable digital text layer and Pages 2 & 3 are scanned.
    Verifies Page 1 is extracted directly (pdf_text) while Pages 2 & 3 go through OCR (ocr_pdf_page).
    """
    worker = WorkerRunner(worker_id="worker-m3-hybrid")
    hybrid_bytes = _build_hybrid_pdf_bytes()

    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/files/import?async_mode=true",
            files={"file": ("hybrid_report.pdf", hybrid_bytes, "application/pdf")},
        )
        assert resp.status_code == 200
        file_id = resp.json()["id"]

        processed = worker.process_one()
        assert processed is not None
        assert processed.state == "COMPLETED"

        detail = client.get(f"/api/v1/files/{file_id}").json()
        assert detail["status"] == "آماده"
        assert detail["extraction_method"] == "hybrid_pdf_ocr"

        pages = client.get(f"/api/v1/files/{file_id}/pages").json()
        assert len(pages) == 3
        assert pages[0]["page_number"] == 1
        assert pages[0]["extraction_method"] == "pdf_text"
        assert pages[1]["page_number"] == 2
        assert pages[1]["extraction_method"] == "ocr_pdf_page"
        assert pages[2]["page_number"] == 3
        assert pages[2]["extraction_method"] == "ocr_pdf_page"

        # Search Page 1 (digital layer)
        s1 = client.get("/api/v1/files", params={"query": "SAHER-HYBRID-PAGE-1"}).json()
        assert len(s1) == 1
        assert s1[0]["matched_page"] == 1

        # Search Page 2 (OCR layer)
        s2 = client.get("/api/v1/files", params={"query": "بایگانی اسناد"}).json()
        assert len(s2) == 1
        assert s2[0]["matched_page"] == 2


def test_m3_worker_interruption_and_pause_resume_no_duplicates():
    """Verify stopping/crashing a worker mid-OCR (after page 1 is checkpointed) and pause/resume
    recovers cleanly without duplicating page rows or FTS search results.
    """
    pdf_bytes = _build_scanned_pdf_bytes([
        ["صفحه اول آزمایش توقف کارگر", "مستندات فنی پروژه ساهر"],
        ["صفحه دوم آزمایش ادامه کارگر", "بررسی پایداری صف پردازش"],
    ])

    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/files/import?async_mode=true",
            files={"file": ("interrupt_test.pdf", pdf_bytes, "application/pdf")},
        )
        assert resp.status_code == 200
        uploaded = resp.json()
        file_id = uploaded["id"]
        job_id = uploaded["latest_job_id"]

        # Test Pause and Resume via API before worker picks it up
        p_resp = client.post(f"/api/v1/jobs/{job_id}/pause")
        assert p_resp.status_code == 200
        assert p_resp.json()["state"] == "PAUSED"

        r_resp = client.post(f"/api/v1/jobs/{job_id}/resume")
        assert r_resp.status_code == 200
        assert r_resp.json()["state"] == "QUEUED"

        # Simulate worker-1 claiming the job, completing Page 1 OCR, and crashing (lease expired)
        claimed = JobQueueRepository.claim_next_job(worker_id="crashed-worker", lease_seconds=30)
        assert claimed is not None and claimed.id == job_id
        JobQueueRepository.update_stage_and_heartbeat(
            job_id=job_id,
            worker_id="crashed-worker",
            stage="OCR_PENDING",
            progress=45.0,
            progress_message="تکمیل صفحه ۱ از ۲",
            checkpoint_updates={
                "needs_ocr_pages": [1, 2],
                "ocr_completed_pages": {
                    "1": {
                        "page_number": 1,
                        "raw_text": "صفحه اول آزمایش توقف کارگر",
                        "normalized_text": "صفحه اول ازمایش توقف کارگر",
                        "bboxes": [],
                        "extraction_method": "ocr_pdf_page",
                        "page_status": "extracted",
                        "ocr_confidence": 91.0,
                        "width": 1000,
                        "height": 480,
                        "processing_ms": 120.0,
                    }
                },
            },
            lease_seconds=30,
        )
        with get_db() as conn:
            conn.execute(
                "UPDATE jobs SET lease_expires_at = '2000-01-01T00:00:00+00:00' WHERE id = ?",
                (job_id,),
            )
            conn.commit()

        # Recover expired lease and run fresh worker-2 to completion
        recovered = JobQueueRepository.recover_expired_leases()
        assert recovered == 1

        worker2 = WorkerRunner(worker_id="recovery-worker")
        done = worker2.process_one()
        assert done is not None
        assert done.state == "COMPLETED"

        # Verify zero duplicate pages and single search hit for both Page 1 (checkpointed) and Page 2 (resumed)
        pages = client.get(f"/api/v1/files/{file_id}/pages").json()
        assert len(pages) == 2
        assert [p["page_number"] for p in pages] == [1, 2]

        search_p1 = client.get("/api/v1/files", params={"query": "توقف کارگر"}).json()
        assert len(search_p1) == 1
        assert search_p1[0]["matched_page"] == 1

        search_p2 = client.get("/api/v1/files", params={"query": "ادامه کارگر"}).json()
        assert len(search_p2) == 1
        assert search_p2[0]["matched_page"] == 2


def test_m3_page_fault_isolation_reanalysis_and_missing_model(isolated_m3_test_env: Path, monkeypatch):
    """Verify:
    1. Single-page read failure (CORRUPTED_PAGE_STREAM on page 2) records page 2 error with page number
       while keeping healthy text from pages 1 and 3 searchable.
    2. Manual user page edit (PATCH /api/v1/files/{id}/pages/1) is preserved across reanalysis.
    3. Missing model directory raises explicit OCR_MODEL_MISSING with required package names.
    """
    worker = WorkerRunner(worker_id="worker-m3-fault")

    pdf_bytes = _build_scanned_pdf_bytes([
        ["صفحه اول سالم در سند آزمایشی", "اطلاعات معتبر صفحه نخست"],
        ["صفحه دوم دارای خطای جریان تصویر"],
        ["صفحه سوم سالم در سند آزمایشی", "نتایج نهایی صفحه سوم"],
    ])
    import services.ingestion.extractor as extractor_mod
    from services.ocr.base import OCRPageReadError
    orig_render = extractor_mod.render_pdf_page_to_pil

    def faulty_render(path: str, page_number: int, scale: float = 2.0):
        if page_number == 2:
            raise OCRPageReadError(
                page_number=page_number,
                reason=f"خطای خواندن تصویر صفحهٔ {page_number}: جریان دادهٔ صفحه آسیب دیده است (CORRUPTED_PAGE_STREAM).",
                code="PDF_PAGE_STREAM_CORRUPTED",
            )
        return orig_render(path, page_number, scale=scale)

    monkeypatch.setattr("services.worker.handlers.render_pdf_page_to_pil", faulty_render)

    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/files/import?async_mode=true",
            files={"file": ("faulty_doc.pdf", pdf_bytes, "application/pdf")},
        )
        assert resp.status_code == 200
        file_id = resp.json()["id"]

        processed = worker.process_one()
        assert processed is not None
        assert processed.state == "COMPLETED"

        detail = client.get(f"/api/v1/files/{file_id}").json()
        assert detail["failed_pages"] == [2]

        pages = client.get(f"/api/v1/files/{file_id}/pages").json()
        p2 = next(p for p in pages if p["page_number"] == 2)
        assert p2["page_status"] == "failed"
        assert "صفحهٔ 2" in (p2["error_message"] or "")

        # Healthy pages 1 & 3 are still indexed and searchable!
        s3 = client.get("/api/v1/files", params={"query": "نتایج نهایی"}).json()
        assert len(s3) == 1
        assert s3[0]["matched_page"] == 3

        # User manually edits Page 1 text
        patch_resp = client.patch(
            f"/api/v1/files/{file_id}/pages/1",
            json={"raw_text": "متن ویرایش‌شده توسط کاربر در صفحه اول برای حفاظت در بازپردازش"},
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["is_user_modified"] is True

        # Trigger Reanalysis on OCR_PENDING stage
        re_resp = client.post(f"/api/v1/files/{file_id}/reanalyze", json={"stage": "OCR_PENDING"})
        assert re_resp.status_code == 200
        re_done = worker.process_one()
        assert re_done is not None
        assert re_done.state == "COMPLETED"

        # Verify Page 1 manual edit was preserved and Page 3 healthy text remains intact
        pages_after = client.get(f"/api/v1/files/{file_id}/pages").json()
        p1_after = next(p for p in pages_after if p["page_number"] == 1)
        assert p1_after["is_user_modified"] is True
        assert "ویرایش‌شده توسط کاربر" in p1_after["raw_text"]

        # Verify explicit OCR_MODEL_MISSING error when model directory lacks traineddata
        empty_models = isolated_m3_test_env / "empty_tessdata"
        empty_models.mkdir(parents=True, exist_ok=True)
        bad_engine = TesseractOCREngine(model_dir=str(empty_models), languages="fas+eng")
        health = bad_engine.inspect_status()
        assert health.ready is False
        assert health.error_code == "OCR_MODEL_MISSING"
        assert "fas.traineddata" in (health.error_message or "")

        try:
            bad_engine.recognize_image(Image.new("RGB", (64, 64), "white"), page_number=1)
            assert False, "Expected OCRModelMissingError"
        except OCRModelMissingError as exc:
            assert exc.code == "OCR_MODEL_MISSING"
            assert "tesseract-ocr-fas" in exc.message


def test_m3_standalone_worker_health_reporting():
    """Verify /health reports worker_online=True when internal API worker is disabled
    and a standalone worker has an active heartbeat in worker_registry.
    """
    with TestClient(app) as client:
        # Initially no internal worker and no standalone worker -> worker_online is False
        h0 = client.get("/health").json()
        assert default_worker.is_running is False
        assert h0["worker_online"] is False
        assert h0["active_workers_count"] == 0

        # Standalone worker registers heartbeat in SQLite worker_registry
        JobQueueRepository.upsert_worker_heartbeat(
            worker_id="standalone-docker-worker-1",
            resource_mode="Balanced",
            concurrency=2,
            active_jobs=1,
            status="ONLINE",
        )

        h1 = client.get("/health").json()
        assert default_worker.is_running is False
        assert h1["worker_online"] is True
        assert h1["active_workers_count"] >= 1
        assert h1["ocr_ready"] is True
        assert h1["ocr_engine"] == "tesseract"
