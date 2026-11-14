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

def _resolve_test_font_path() -> Path:
    repo_root = Path(__file__).resolve().parent.parent
    primary = repo_root / "data" / "models" / "fonts" / "Vazirmatn.ttf"
    bundled = repo_root / "apps" / "web" / "public" / "fonts" / "Vazirmatn.woff2"
    if bundled.is_file():
        try:
            primary.parent.mkdir(parents=True, exist_ok=True)
            primary.write_bytes(bundled.read_bytes())
            return primary
        except Exception:
            return bundled
    if primary.is_file():
        return primary
    for sys_cand in (
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf"),
    ):
        if sys_cand.is_file():
            try:
                primary.parent.mkdir(parents=True, exist_ok=True)
                primary.write_bytes(sys_cand.read_bytes())
                return primary
            except Exception:
                return sys_cand
    return primary


FONT_PATH = _resolve_test_font_path()



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
    actual_height = max(height, 96 + len(lines) * 76)
    img = Image.new("RGB", (width, actual_height), color=(255, 255, 255))
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


def test_m3_image_folder_analysis_and_word_report_export():
    """Verify:
    1. Uploading a folder of multiple screenshots/images (POST /api/v1/images/analyze-folder) classifies each image
       in two priority levels:
       - Priority 1: Username and Account ID (account_id, account_username, account_label, platform_source)
       - Priority 2: The 12 thematic categories (اجتماعی، اقتصادی، امنیتی، جاسوسی، دفاعی (نظامی، کویر و مرز)،
         دین و روحانیت، رزمایش، سایبری، سیاسی، علم و فناوری، فرهنگی، هواگرد (پهپاد، ریزپرنده، جنگنده و ...))
    2. Exporting the analyzed images to Word (POST /api/v1/images/export-word) and single-file Word
       (GET /api/v1/files/{id}/export-word) produces a valid .docx document containing the Priority-1 -> Priority-2
       hierarchy table, overview table, and per-image analytical sections with embedded thumbnails.
    """
    import json
    import docx

    # Image 1: Screenshot with @aero_watch_ir handle about drones/UAVs -> هواگرد (پهپاد، ریزپرنده، جنگنده و ...)
    pil_aerospace = _render_persian_page_image([
        "کانال رسمی پایش هوافضا @aero_watch_ir",
        "پرواز آزمایشی پهپاد شناسایی و ریزپرنده رزمی بر فراز منطقه",
    ])
    buf_aero = io.BytesIO()
    pil_aerospace.save(buf_aero, format="PNG")
    img_aerospace = buf_aero.getvalue()

    # Image 2: Screenshot from @aero_watch_ir about military desert/border exercise -> دفاعی (نظامی، کویر و مرز) or رزمایش
    pil_defense = _render_persian_page_image([
        "آیدی: @aero_watch_ir",
        "پایش مرز و کویر توسط یگان زرهی و پدافند نظامی مرزبانی",
    ])
    buf_def = io.BytesIO()
    pil_defense.save(buf_def, format="PNG")
    img_defense = buf_def.getvalue()

    # Image 3: Screenshot from @econ_daily_ir about financial invoice / inflation -> اقتصادی
    pil_economy = _render_persian_page_image([
        "t.me/econ_daily_ir",
        "فاکتور رسمی فروش و صورتحساب مالی بازار ارز و تورم بانکی",
    ])
    buf_econ = io.BytesIO()
    pil_economy.save(buf_econ, format="PNG")
    img_economy = buf_econ.getvalue()

    # Image 4: Screenshot from @cyber_sec_ir about cyber attack & hacking -> سایبری
    pil_cyber = _render_persian_page_image([
        "نام کاربری: cyber_sec_ir",
        "هشدار حمله سایبری، بدافزار باج‌افزار و نفوذ هکرها به سرور شبکه",
    ])
    buf_cyb = io.BytesIO()
    pil_cyber.save(buf_cyb, format="PNG")
    img_cyber = buf_cyb.getvalue()

    with TestClient(app) as client:
        rel_paths = json.dumps([
            "screenshots/@aero_watch_ir/uav_flight_01.png",
            "screenshots/@aero_watch_ir/border_desert_02.png",
            "screenshots/@econ_daily_ir/invoice_03.png",
            "screenshots/@cyber_sec_ir/ransomware_04.png",
        ])
        resp = client.post(
            "/api/v1/images/analyze-folder",
            files=[
                ("files", ("uav_flight_01.png", img_aerospace, "image/png")),
                ("files", ("border_desert_02.png", img_defense, "image/png")),
                ("files", ("invoice_03.png", img_economy, "image/png")),
                ("files", ("ransomware_04.png", img_cyber, "image/png")),
            ],
            data={
                "folder_name": "پوشه اسکرین‌شات‌های آزمایشی دو سطحی",
                "relative_paths": rel_paths,
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["folder_name"] == "پوشه اسکرین‌شات‌های آزمایشی دو سطحی"
        assert data["total_images"] == 4
        items = data["items"]
        assert len(items) == 4

        # Verify Priority 1 (Username & ID) extraction
        assert items[0]["account_id"] == "@aero_watch_ir"
        assert items[1]["account_id"] == "@aero_watch_ir"
        assert items[2]["account_id"] == "@econ_daily_ir"
        assert items[3]["account_id"] == "@cyber_sec_ir"

        # Verify Priority 2 (12 Thematic Categories) classification
        assert items[0]["thematic_category"] == "هواگرد (پهپاد، ریزپرنده، جنگنده و ...)"
        assert items[0]["detected_topic"] == "هواگرد (پهپاد، ریزپرنده، جنگنده و ...)"

        assert items[1]["thematic_category"] == "دفاعی (نظامی، کویر و مرز)"
        assert items[1]["detected_topic"] == "دفاعی (نظامی، کویر و مرز)"

        assert items[2]["thematic_category"] == "اقتصادی"
        assert items[2]["detected_topic"] == "اقتصادی"

        assert items[3]["thematic_category"] == "سایبری"
        assert items[3]["detected_topic"] == "سایبری"

        # Verify Priority-1 account_breakdown and two-level account_category_tree
        assert "account_breakdown" in data
        assert "account_category_tree" in data
        aero_label = items[0]["account_label"]
        assert data["account_breakdown"][aero_label] == 2
        assert data["account_category_tree"][aero_label]["هواگرد (پهپاد، ریزپرنده، جنگنده و ...)"] == 1
        assert data["account_category_tree"][aero_label]["دفاعی (نظامی، کویر و مرز)"] == 1

        # Now export all 4 analyzed screenshots to a single Word (.docx) file
        file_ids = [it["file_id"] for it in items]
        word_resp = client.post(
            "/api/v1/images/export-word",
            json={
                "file_ids": file_ids,
                "folder_name": "پوشه اسکرین‌شات‌های آزمایشی دو سطحی",
            },
        )
        assert word_resp.status_code == 200
        assert (
            word_resp.headers["content-type"]
            == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        assert len(word_resp.content) > 5000

        # Parse the generated .docx with python-docx and verify Priority 1, Priority 2, and embedded pictures
        doc = docx.Document(io.BytesIO(word_resp.content))
        all_paragraphs_text = "\n".join(p.text for p in doc.paragraphs)
        all_tables_text = "\n".join(
            cell.text for table in doc.tables for row in table.rows for cell in row.cells
        )
        combined_text = all_paragraphs_text + "\n" + all_tables_text
        assert "پوشه اسکرین‌شات‌های آزمایشی دو سطحی" in combined_text
        assert "اولویت اول دسته‌بندی (نام کاربری و آیدی)" in combined_text
        assert "اولویت دوم دسته‌بندی (۱۲ سرفصل موضوعی)" in combined_text
        assert "@aero_watch_ir" in combined_text
        assert "هواگرد (پهپاد، ریزپرنده، جنگنده و ...)" in combined_text
        assert "دفاعی (نظامی، کویر و مرز)" in combined_text
        assert "اقتصادی" in combined_text
        assert "سایبری" in combined_text

        # Verify all 4 images are embedded as inline shapes in the Word document
        assert len(doc.inline_shapes) == 4
        # Verify 1 hierarchical tree table + 1 overview table + 4 per-image specification tables = 6 tables
        assert len(doc.tables) == 6

        # Verify single-file Word export endpoint as well
        single_word = client.get(f"/api/v1/files/{file_ids[0]}/export-word")
        assert single_word.status_code == 200
        single_doc = docx.Document(io.BytesIO(single_word.content))
        assert len(single_doc.inline_shapes) == 1

        # Verify that non-Cultural/Social categories (هواگرد، دفاعی، اقتصادی، سایبری) do NOT activate the template
        for it in items:
            assert it["template_applicable"] is False
            assert it["formatted_template_text"] == ""


def test_m3_cultural_and_social_instagram_template_completion_and_word_export():
    """Verify:
    For Cultural (فرهنگی) and Social (اجتماعی) categories ONLY, the system extracts and completes
    both structured report templates (قواره‌های فرهنگی و اجتماعی) from the screenshots and Instagram URL:
    1) Cultural template (قواره فرهنگی):
      نام و نام خانوادگی: ...
      کدملی: ...
      شماره تماس: ...
      شغل: ...
      تخلف: ترویج ابتذال
      درخواست مسدودی سیم کارت
      https://www.instagram.com/mira_rjbpr?stkn=YzM4MWNpN3Y2a3Vy

      #ابتذال
      #خراسان_رضوی
      #شهرستان_کاشمر

    2) Social blocking template (قواره اجتماعی):
      〰️〰️〰️〰️〰️〰️〰️〰️〰️
      #مسدودسازی
      #اینستاگرام

      ✅نام و نام خانوادگی:
      ✅کدملی:
      ✅ شماره تماس/حساب:
      ✅ تاریخ ارشاد:
      ✅ آیدی عددی:
      ✅ آدرس اینترنتی:
      @mira_rjbpr
      توضیحات:

      #کاشمر
      〰️〰️〰️〰️〰️〰️〰️〰️〰️
    """
    import json
    import docx

    ig_url = "https://www.instagram.com/mira_rjbpr?stkn=YzM4MWNpN3Y2a3Vy"

    # Screenshot 1 of @mira_rjbpr: Instagram profile bio + occupation + cultural keywords
    pil_shot1 = _render_persian_page_image([
        "نام و نام خانوادگی: میرا رجب‌پور",
        "شغل: بلاگر و مدلینگ استوری اینستاگرام",
        "تخلف: ترویج ابتذال در فضای مجازی شهرستان کاشمر",
    ])
    buf1 = io.BytesIO()
    pil_shot1.save(buf1, format="PNG")
    img_shot1 = buf1.getvalue()

    # Screenshot 2 of @mira_rjbpr: Social blocking info (National ID, Phone/Account, Guidance Date, Numeric ID)
    pil_shot2 = _render_persian_page_image([
        "کدملی: 0921456789",
        "شماره تماس/حساب: 09153456789",
        "تاریخ ارشاد: 1405/08/14",
        "آیدی عددی: 583920147",
        "استان خراسان رضوی شهرستان کاشمر درخواست مسدودی سیم کارت",
    ])
    buf2 = io.BytesIO()
    pil_shot2.save(buf2, format="PNG")
    img_shot2 = buf2.getvalue()

    with TestClient(app) as client:
        rel_paths = json.dumps([
            "instagram/@mira_rjbpr/profile_shot_01.png",
            "instagram/@mira_rjbpr/identity_shot_02.png",
        ])
        resp = client.post(
            "/api/v1/images/analyze-folder",
            files=[
                ("files", ("profile_shot_01.png", img_shot1, "image/png")),
                ("files", ("identity_shot_02.png", img_shot2, "image/png")),
            ],
            data={
                "folder_name": "پرونده فرهنگی و اجتماعی کاشمر",
                "relative_paths": rel_paths,
                "source_url": ig_url,
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["total_images"] == 2
        items = data["items"]

        # Both screenshots belong to @mira_rjbpr and classify into فرهنگی or اجتماعی
        for it in items:
            assert it["account_id"] == "@mira_rjbpr"
            assert it["thematic_category"] in ("فرهنگی", "اجتماعی")
            assert it["template_applicable"] is True
            tf = it["template_fields"]
            assert tf is not None
            # Merged across both screenshots of @mira_rjbpr:
            assert "0921456789" in tf["national_id"]
            assert "09153456789" in tf["phone_number"]
            assert "1405/08/14" in tf["guidance_date"]
            assert "583920147" in tf["numeric_id"]
            assert tf["account_handle"] == "@mira_rjbpr"
            assert tf["city_hashtag"] == "#کاشمر"
            assert tf["occupation"] != ""
            assert "ترویج ابتذال" in tf["violation"]
            assert tf["action_request"] == "درخواست مسدودی سیم کارت"
            assert tf["profile_url"] == ig_url
            assert "#ابتذال" in tf["hashtags"]
            assert "#خراسان_رضوی" in tf["hashtags"]
            assert "#شهرستان_کاشمر" in tf["hashtags"]

            tpl_text = it["formatted_template_text"]
            # Check Cultural Template (قواره فرهنگی)
            assert "نام و نام خانوادگی:" in tpl_text
            assert "کدملی: 0921456789" in tpl_text
            assert "شماره تماس: 09153456789" in tpl_text
            assert "تخلف: ترویج ابتذال" in tpl_text
            assert "درخواست مسدودی سیم کارت" in tpl_text
            assert ig_url in tpl_text
            assert "#ابتذال" in tpl_text
            assert "#خراسان_رضوی" in tpl_text
            assert "#شهرستان_کاشمر" in tpl_text

            # Check Social Blocking Template (قواره اجتماعی)
            assert "〰️〰️〰️〰️〰️〰️〰️〰️〰️" in tpl_text
            assert "#مسدودسازی" in tpl_text
            assert "#اینستاگرام" in tpl_text
            assert "✅نام و نام خانوادگی:" in tpl_text
            assert "✅کدملی: 0921456789" in tpl_text
            assert "✅ شماره تماس/حساب: 09153456789" in tpl_text
            assert "✅ تاریخ ارشاد: 1405/08/14" in tpl_text
            assert "✅ آیدی عددی: 583920147" in tpl_text
            assert "✅ آدرس اینترنتی:" in tpl_text
            assert "@mira_rjbpr" in tpl_text
            assert "توضیحات:" in tpl_text
            assert "#کاشمر" in tpl_text

        # Export to Word (.docx) and verify both completed Cultural & Social templates are inside the Word report
        file_ids = [it["file_id"] for it in items]
        word_resp = client.post(
            "/api/v1/images/export-word",
            json={
                "file_ids": file_ids,
                "folder_name": "پرونده فرهنگی و اجتماعی کاشمر",
                "source_url": ig_url,
            },
        )
        assert word_resp.status_code == 200
        doc = docx.Document(io.BytesIO(word_resp.content))
        doc_text = "\n".join(p.text for p in doc.paragraphs)
        assert "قوارهٔ تکمیل‌شده ویژهٔ دسته‌بندی" in doc_text
        assert "کدملی: 0921456789" in doc_text
        assert "شماره تماس: 09153456789" in doc_text
        assert "تخلف: ترویج ابتذال" in doc_text
        assert "درخواست مسدودی سیم کارت" in doc_text
        assert ig_url in doc_text
        assert "#ابتذال" in doc_text
        assert "#خراسان_رضوی" in doc_text
        assert "#شهرستان_کاشمر" in doc_text
        assert "〰️〰️〰️〰️〰️〰️〰️〰️〰️" in doc_text
        assert "#مسدودسازی" in doc_text
        assert "#اینستاگرام" in doc_text
        assert "✅ شماره تماس/حساب: 09153456789" in doc_text
        assert "✅ تاریخ ارشاد: 1405/08/14" in doc_text
        assert "✅ آیدی عددی: 583920147" in doc_text
        assert "@mira_rjbpr" in doc_text
        assert "#کاشمر" in doc_text


def test_m3_paddleocr_engine_integration_and_dark_mode_screenshot():
    """Verify:
    1. `PaddlePaddle/PaddleOCR` repository (`vendor/PaddleOCR`) and its Persian (`fa_dict.txt`),
       Arabic (`ppocrv5_arabic_dict.txt`), and English (`en_dict.txt`) dictionaries are loaded.
    2. `POST /api/v1/ocr/engine` switches between `paddleocr`, `hybrid`, and `tesseract`.
    3. `PaddleOCREngine` accurately extracts Persian/English text and `@handle` from a dark-mode
       social media screenshot (white text on dark #14171A background) via PP-OCR auto-inversion.
    """
    from services.ocr import PaddleOCREngine, get_paddleocr_repo_metadata, set_ocr_engine

    meta = get_paddleocr_repo_metadata()
    assert meta["repo_present"] is True
    assert "fa_dict.txt" in meta["dictionaries_loaded"]
    assert meta["dictionaries_loaded"]["fa_dict.txt"] > 100
    assert meta["total_charset_size"] > 120

    # Render a dark-mode Instagram/Telegram screenshot (light text on dark #14171A background)
    dark_img = Image.new("RGB", (1000, 420), color=(20, 23, 26))
    draw = ImageDraw.Draw(dark_img)
    font = ImageFont.truetype(str(FONT_PATH), 34)
    y = 48
    for line in [
        "نام کاربری: @paddle_cyber_ir",
        "هشدار امنیتی و تحلیل بدافزار سایبری در شبکه",
        "کدملی: 0931122334",
    ]:
        draw.text((60, y), line, font=font, fill=(242, 245, 248))
        y += 76

    paddle_engine = PaddleOCREngine(hybrid_mode=False)
    st = paddle_engine.inspect_status()
    assert st.ready is True
    assert st.engine_name == "paddleocr"
    assert "fa_ppocr" in st.installed_languages

    res = paddle_engine.recognize_image(dark_img, page_number=1)
    assert res.status == "extracted"
    assert res.engine_name == "paddleocr"
    assert "paddle_cyber_ir" in res.normalized_text or "سایبری" in res.normalized_text
    assert "0931122334" in res.normalized_text

    with TestClient(app) as client:
        # Switch engine via API to paddleocr
        sw_resp = client.post("/api/v1/ocr/engine", json={"engine_name": "paddleocr"})
        assert sw_resp.status_code == 200
        sw_data = sw_resp.json()
        assert sw_data["engine_name"] == "paddleocr"
        assert sw_data["ready"] is True
        assert sw_data["paddleocr_metadata"]["repo_present"] is True
        assert len(sw_data["available_engines"]) == 3

        # Switch back to tesseract and verify
        sw_tess = client.post("/api/v1/ocr/engine", json={"engine_name": "tesseract"})
        assert sw_tess.status_code == 200
        assert sw_tess.json()["engine_name"] == "tesseract"
        set_ocr_engine(None)


def test_m3_multi_axis_classification_judicial_and_identity_profiles():
    """Verify all 7 newly requested capabilities:
    1. Capture source classification (اسکرین‌شات موبایل، عکس با دوربین، عکس سوژه و ...)
    2. Subject ID, location name, and GPS coordinates (`35.2384, 58.4656`)
    3. Exact title & written text analysis + Legal/Judicial criminal assessment (`criminal_assessment`)
    4. Personal folder -> 12 thematic categories classification (`جاسوسی`, `فرهنگی`, etc.)
    5. Personal & Civil Identity Dossiers CRUD + auto-sync + Word (.docx) export (`/api/v1/profiles`)
    """
    import json
    import docx

    # Image 1: Espionage / Classified Document with coordinates & identity info
    pil_espionage = _render_persian_page_image([
        "آیدی: @spy_network_ir",
        "نام و نام خانوادگی: بهرام کاظمی",
        "نام پدر: منصور",
        "کدملی: 0945566778",
        "شماره شناسنامه: 4512",
        "شماره موبایل: 09159998877",
        "تلفن ثابت: 05155223344",
        "آدرس: خراسان رضوی، کاشمر، خیابان امام خمینی، پلاک ۱۲",
        "مختصات: 35.2384, 58.4656",
        "افشای اسناد فوق محرمانه و جاسوسی برای سرویس بیگانه",
    ])
    b_esp = io.BytesIO()
    pil_espionage.save(b_esp, format="PNG")

    # Image 2: Camera photo of drone/military site (filename IMG_2045_camera.png)
    pil_cam = _render_persian_page_image([
        "عکسبرداری با دوربین از آشیانه پهپاد شاهد و سایت راداری مرزی",
        "موقعیت مکانی: استان خراسان رضوی شهرستان کاشمر",
    ])
    b_cam = io.BytesIO()
    pil_cam.save(b_cam, format="PNG")

    with TestClient(app) as client:
        rel_paths = json.dumps([
            "پوشه_بهرام_کاظمی/@spy_network_ir/classified_doc_01.png",
            "عکاسی_میدانی/IMG_2045_camera.png",
        ])
        resp = client.post(
            "/api/v1/images/analyze-folder",
            files=[
                ("files", ("classified_doc_01.png", b_esp.getvalue(), "image/png")),
                ("files", ("IMG_2045_camera.png", b_cam.getvalue(), "image/png")),
            ],
            data={
                "folder_name": "پرونده چندبعدی قضایی و هویتی",
                "relative_paths": rel_paths,
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["total_images"] == 2
        assert data["criminal_count"] >= 1
        assert "source_type_breakdown" in data
        assert "location_breakdown" in data

        it1, it2 = data["items"][0], data["items"][1]
        # Verify Personal Folder & 12-category classification
        assert "پوشهٔ شخصی" in it1["personal_folder"]
        assert it1["thematic_category"] == "جاسوسی"
        assert "35.2384, 58.4656" in it1["gps_coordinates"]
        assert "کاشمر" in it1["location_name"]

        # Verify Criminal & Judicial Assessment
        crim1 = it1["criminal_assessment"]
        assert crim1["has_criminal_indicator"] is True
        assert "بحرانی" in crim1["risk_level"]
        assert any("۵۰۱" in art or "جاسوسی" in art for art in crim1["legal_articles"] + crim1["criminal_charges"])

        # Verify Personal Identity extraction
        pid1 = it1["personal_identity"]
        assert pid1["has_identity_data"] is True
        assert pid1["national_id"] == "0945566778"
        assert pid1["mobile_phone"] == "09159998877"

        # Verify Camera Photo source classification on Image 2
        assert "دوربین" in it2["capture_source_category"]

        # Verify Identity Profiles API auto-synced the extracted dossier
        prof_list = client.get("/api/v1/profiles")
        assert prof_list.status_code == 200
        profs = prof_list.json()["items"]
        assert any(p["national_id"] == "0945566778" and p["mobile_phone"] == "09159998877" for p in profs)

        # Create a new manual identity profile via POST /api/v1/profiles
        create_resp = client.post(
            "/api/v1/profiles",
            json={
                "first_name": "سارا",
                "last_name": "احمدی",
                "full_name": "سارا احمدی",
                "father_name": "رضا",
                "national_id": "0912345678",
                "birth_certificate_no": "1890",
                "birth_date": "1376/02/15",
                "birth_place": "مشهد",
                "occupation": "طراح لباس",
                "mobile_phone": "09151112233",
                "landline_phone": "05138889900",
                "province": "خراسان رضوی",
                "city": "مشهد",
                "address": "مشهد، بلوار وکیل‌آباد، پلاک ۴۵",
                "postal_code": "9188812345",
                "account_handle": "@sara_design_ir",
                "thematic_category": "فرهنگی",
                "judicial_notes": "ماده ۱۴ قانون جرایم رایانه‌ای",
            },
        )
        assert create_resp.status_code == 201
        created_prof = create_resp.json()
        assert created_prof["full_name"] == "سارا احمدی"

        # Export Identity Profiles to Persian Word (.docx)
        word_prof_resp = client.post(
            "/api/v1/profiles/export-word",
            json={"profile_ids": [created_prof["id"]]},
        )
        assert word_prof_resp.status_code == 200
        prof_doc = docx.Document(io.BytesIO(word_prof_resp.content))
        prof_doc_txt = "\n".join(
            cell.text for t in prof_doc.tables for r in t.rows for cell in r.cells
        )
        assert "سارا احمدی" in prof_doc_txt
        assert "09151112233" in prof_doc_txt
        assert "بلوار وکیل‌آباد" in prof_doc_txt


def test_m3_user_activity_report_6_tabs_and_exports():
    """Verify the 6-tab User Activity Report ('گزارش جامع کاربر') seeded from
    `public/assets/aistudio/890046190_8b7aba55.html` as well as custom report creation,
    HTML export, and Persian Word (.docx) export.
    """
    import docx

    with TestClient(app) as client:
        # 1. Verify auto-seeded report from 890046190_8b7aba55.html
        list_resp = client.get("/api/v1/user-reports")
        assert list_resp.status_code == 200, list_resp.text
        reports = list_resp.json()["items"]
        assert len(reports) >= 1

        ashouri = next((r for r in reports if "890046190" in r["national_id"] or "آشوری" in r["full_name"]), None)
        assert ashouri is not None
        assert ashouri["full_name"] == "علی اکبر آشوری"
        assert ashouri["username"] == "mostafa_1368a"
        assert ashouri["telegram_id"] == "250556017"
        assert ashouri["province"] == "خراسان رضوی"
        assert ashouri["final_status"] == "سیاه"
        assert ashouri["total_charges"] == 15
        assert ashouri["total_groups"] == 3
        assert ashouri["total_messages"] == 500

        # 2. Verify full 6-tab detail payload
        detail_resp = client.get(f"/api/v1/user-reports/{ashouri['id']}")
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        assert len(detail["virtual_data"]) == 3
        assert len(detail["real_data"]) == 10
        assert len(detail["personality_analysis"]) == 7
        assert len(detail["charges"]) == 15
        assert len(detail["groups"]) == 3
        assert len(detail["messages"]) == 500

        # Check specific charge and group details from 890046190_8b7aba55.html
        first_charge = detail["charges"][0]
        assert "توهین به مقدسات" in first_charge["title"]
        assert first_charge["count"] == 19
        assert len(first_charge["evidences"]) == 19

        group_names = [g["name"] for g in detail["groups"]]
        assert "وفاداران به ملی گرایان مردم گرا" in group_names
        assert "حزب نافرمانی مدنی ایران" in group_names

        # 3. Verify standalone HTML export matches the 6-tab template structure
        html_resp = client.get(f"/api/v1/user-reports/{ashouri['id']}/export-html")
        assert html_resp.status_code == 200
        html_text = html_resp.text
        assert "گزارش کاربر: علی اکبر آشوری" in html_text
        assert "🌐 دیتای فضای مجازی" in html_text
        assert "👤 دیتای حقیقی" in html_text
        assert "🧠 تحلیل شخصیت" in html_text
        assert "⚖️ عناوین اتهامی (15)" in html_text
        assert "👥 گروه‌های کاربر (3)" in html_text
        assert "💬 پیام‌های کاربر (500)" in html_text

        # 4. Verify Persian Word (.docx) export of the 6-tab user report
        word_resp = client.get(f"/api/v1/user-reports/{ashouri['id']}/export-word")
        assert word_resp.status_code == 200
        doc = docx.Document(io.BytesIO(word_resp.content))
        doc_txt = "\n".join(p.text for p in doc.paragraphs) + "\n" + "\n".join(
            cell.text for t in doc.tables for r in t.rows for cell in r.cells
        )
        assert "علی اکبر آشوری" in doc_txt
        assert "mostafa_" in doc_txt
        assert "۸۹۰۰۴۶۱۹۰" in doc_txt or "890046190" in doc_txt
        assert "توهین به مقدسات" in doc_txt
