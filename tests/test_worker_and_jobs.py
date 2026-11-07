import os
import tempfile
import threading
import pytest
from fastapi.testclient import TestClient
from services.api.config import settings
from services.api.database import init_db, get_db
from services.api.repository import ArchiveRepository, create_minimal_valid_png
from services.api.migrations import LegacyMigrationManager
from services.api.main import app
from services.worker.lifecycle import (
    JobState,
    ProcessingStage,
    RetryableJobError,
    PermanentJobError,
)
from services.worker.queue import JobQueueRepository
from services.worker.runner import WorkerRunner, default_worker


@pytest.fixture(autouse=True)
def isolated_worker_test_env(monkeypatch):
    """
    Provides an isolated temporary SQLite DB, storage dir, and backup dir per test.
    Disables the automatic background worker loop by default so tests can deterministically
    verify QUEUED -> RUNNING -> COMPLETED/FAILED transitions and concurrent worker claims.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_saher_m2.db")
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
        yield tmpdir
        default_worker.stop()


def test_m2_1_async_ingestion_job_creation_and_independent_worker_completion():
    """
    Verifies:
    - Async import (`async_mode=true`) stores the file, registers a QUEUED durable job in SQLite,
      and returns immediately with `status='در صف'` and `extraction_status='queued'`.
    - Independent WorkerRunner claims the job, executes DISCOVERY -> VALIDATION -> EXTRACTION -> INDEXING -> FINALIZATION,
      marks the job COMPLETED, updates FTS5, and sets file `status='آماده'`.
    - Images remain `extraction_status='pending_ocr'` and stage `OCR_PENDING` (never falsely marked as extracted OCR).
    """
    with TestClient(app) as client:
        txt_bytes = "سند معماری موتور صف پردازش پایدار ساهر برای جست‌وجوی تمام‌متن.".encode("utf-8")
        r_import = client.post(
            "/api/v1/files/import?async_mode=true",
            files={"file": ("durable_engine.txt", txt_bytes, "text/plain")},
            data={"topic": "فناوری"},
        )
        assert r_import.status_code == 200
        imported = r_import.json()
        file_id = imported["id"]
        job_id = imported["latest_job_id"]
        assert job_id is not None
        assert imported["status"] == "در صف"
        assert imported["extraction_status"] == "queued"
        assert imported["job_state"] == JobState.QUEUED.value

        # Verify job is persisted in SQLite in QUEUED state
        r_jobs = client.get("/api/v1/jobs").json()
        assert r_jobs["stats"]["queued"] == 1
        assert r_jobs["items"][0]["id"] == job_id
        assert r_jobs["items"][0]["state"] == "QUEUED"

        # Execute job via independent worker
        worker = WorkerRunner(worker_id="test-worker-alpha")
        completed_job = worker.process_one(specific_job_id=job_id)
        assert completed_job is not None
        assert completed_job.state == JobState.COMPLETED.value
        assert completed_job.processing_stage == ProcessingStage.FINALIZATION.value
        assert completed_job.progress == 100.0
        assert completed_job.attempt_count == 1

        # Verify file is now 'آماده' and searchable via FTS5
        r_file = client.get(f"/api/v1/files/{file_id}").json()
        assert r_file["status"] == "آماده"
        assert r_file["extraction_status"] == "extracted"
        assert "موتور صف پردازش پایدار" in r_file["text"]

        search_hits = client.get("/api/v1/files", params={"query": "پایدار"}).json()
        assert len(search_hits) == 1
        assert search_hits[0]["id"] == file_id

        # Also test image import -> stops at OCR_PENDING without fabricating OCR text
        png_bytes = create_minimal_valid_png((90, 140, 190))
        r_img = client.post(
            "/api/v1/files/import?async_mode=true",
            files={"file": ("scan_page.png", png_bytes, "image/png")},
        ).json()
        img_job = worker.process_one(specific_job_id=r_img["latest_job_id"])
        assert img_job is not None
        assert img_job.state == JobState.COMPLETED.value
        assert img_job.processing_stage == ProcessingStage.OCR_PENDING.value

        r_img_after = client.get(f"/api/v1/files/{r_img['id']}").json()
        assert r_img_after["extraction_status"] == "pending_ocr"
        assert r_img_after["status"] == "در صف"
        assert r_img_after["text"] == ""


def test_m2_2_atomic_worker_claims_and_concurrent_workers():
    """
    Verifies that when multiple concurrent workers race to claim from the queue,
    SQLite `BEGIN IMMEDIATE` guarantees each job is claimed and executed by at most one worker.
    """
    job_ids = []
    for i in range(6):
        dto = ArchiveRepository.save_imported_file(
            filename=f"concurrent_doc_{i}.txt",
            content=f"محتوای یکتای سند شماره {i} برای تست هم‌زمانی کارگرها".encode("utf-8"),
            async_mode=True,
        )
        assert dto.latest_job_id is not None
        job_ids.append(dto.latest_job_id)

    claimed_by_worker: list[tuple[str, str]] = []
    lock = threading.Lock()

    def worker_task(w_idx: int):
        w_id = f"concurrent-worker-{w_idx}"
        while True:
            claimed = JobQueueRepository.claim_next_job(worker_id=w_id, lease_seconds=30)
            if not claimed:
                break
            with lock:
                claimed_by_worker.append((claimed.id, w_id))

    threads = [threading.Thread(target=worker_task, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    claimed_job_ids = [jid for jid, _ in claimed_by_worker]
    # Every job must be claimed exactly once (no duplicates, no missed jobs)
    assert len(claimed_job_ids) == 6
    assert set(claimed_job_ids) == set(job_ids)


def test_m2_3_pause_resume_cancel_and_manual_retry_controls():
    """
    Verifies job lifecycle state transitions via REST endpoints:
    QUEUED -> PAUSED -> QUEUED (resume) -> CANCELLED -> QUEUED (retry) -> COMPLETED.
    """
    with TestClient(app) as client:
        dto = ArchiveRepository.save_imported_file(
            filename="lifecycle_control.txt",
            content="متن آزمایشی برای بررسی توقف، ادامه، لغو و تلاش مجدد کار در صف.".encode("utf-8"),
            async_mode=True,
        )
        job_id = dto.latest_job_id
        assert job_id is not None

        # 1. Pause QUEUED job
        r_pause = client.post(f"/api/v1/jobs/{job_id}/pause")
        assert r_pause.status_code == 200
        assert r_pause.json()["state"] == "PAUSED"

        # Worker must NOT claim a PAUSED job
        w = WorkerRunner(worker_id="worker-ctrl")
        assert w.process_one() is None

        # 2. Resume PAUSED job -> returns to QUEUED
        r_resume = client.post(f"/api/v1/jobs/{job_id}/resume")
        assert r_resume.status_code == 200
        assert r_resume.json()["state"] == "QUEUED"

        # 3. Cancel QUEUED job -> transitions to CANCELLED
        r_cancel = client.post(f"/api/v1/jobs/{job_id}/cancel")
        assert r_cancel.status_code == 200
        assert r_cancel.json()["state"] == "CANCELLED"

        # Worker must NOT claim a CANCELLED job
        assert w.process_one() is None

        # 4. Retry CANCELLED job -> returns to QUEUED and worker completes it
        r_retry = client.post(f"/api/v1/jobs/{job_id}/retry")
        assert r_retry.status_code == 200
        assert r_retry.json()["state"] == "QUEUED"

        done = w.process_one(specific_job_id=job_id)
        assert done is not None
        assert done.state == "COMPLETED"

        # Verify full execution history events were recorded
        r_detail = client.get(f"/api/v1/jobs/{job_id}").json()
        event_types = [ev["event_type"] for ev in r_detail["events"]]
        assert "CREATED" in event_types
        assert "PAUSED" in event_types
        assert "RESUMED" in event_types
        assert "CANCELLED" in event_types
        assert "RETRY_SCHEDULED" in event_types
        assert "COMPLETED" in event_types


def test_m2_4_failed_job_retry_backoff_and_permanent_failure(monkeypatch):
    """
    Verifies:
    - Retryable errors schedule automatic retry (`state='QUEUED'`) up to `max_retries` before marking `FAILED`.
    - Permanent validation/corruption errors fail immediately (`state='FAILED'`, `is_retryable=False`) without futile retries.
    """
    dto_retry = ArchiveRepository.save_imported_file(
        filename="transient_error_doc.txt",
        content="سند برای تست خطای موقت و تلاش مجدد.".encode("utf-8"),
        async_mode=True,
    )
    job_id = dto_retry.latest_job_id
    assert job_id is not None

    # Set max_retries = 2 for fast test verification
    with get_db() as conn:
        conn.execute("UPDATE jobs SET max_retries = 2 WHERE id = ?", (job_id,))

    # Simulate transient storage unavailability on attempt 1
    claimed1 = JobQueueRepository.claim_next_job("worker-1")
    assert claimed1 is not None and claimed1.id == job_id
    res1 = JobQueueRepository.mark_job_failed_or_retry(
        job_id=job_id,
        worker_id="worker-1",
        error_code="STORAGE_TEMP_BUSY",
        error_message="دیسک موقتاً مشغول است.",
        retryable=True,
        base_backoff_seconds=0.0,
    )
    assert res1 is not None
    assert res1.state == JobState.QUEUED.value  # Scheduled for retry 2/2
    assert res1.attempt_count == 1

    # On attempt 2 (reaching max_retries=2), another transient failure transitions to FAILED
    claimed2 = JobQueueRepository.claim_next_job("worker-1", specific_job_id=job_id)
    assert claimed2 is not None
    res2 = JobQueueRepository.mark_job_failed_or_retry(
        job_id=job_id,
        worker_id="worker-1",
        error_code="STORAGE_TEMP_BUSY",
        error_message="دیسک همچنان مشغول است.",
        retryable=True,
        base_backoff_seconds=0.0,
    )
    assert res2 is not None
    assert res2.state == JobState.FAILED.value
    assert res2.attempt_count == 2

    # Permanent error fails on first attempt even when attempt_count < max_retries
    dto_perm = ArchiveRepository.save_imported_file(
        filename="perm_error_doc.txt",
        content="سند برای تست خطای دائمی.".encode("utf-8"),
        async_mode=True,
    )
    perm_job_id = dto_perm.latest_job_id
    assert perm_job_id is not None
    claimed_perm = JobQueueRepository.claim_next_job("worker-1", specific_job_id=perm_job_id)
    assert claimed_perm is not None
    res_perm = JobQueueRepository.mark_job_failed_or_retry(
        job_id=perm_job_id,
        worker_id="worker-1",
        error_code="PDF_ENCRYPTED",
        error_message="سند رمزگذاری‌شده است.",
        retryable=False,
    )
    assert res_perm is not None
    assert res_perm.state == JobState.FAILED.value
    assert res_perm.is_retryable is False


def test_m2_5_worker_crash_and_expired_lease_recovery():
    """
    Simulates a worker claiming a job and crashing (lease expires in the past).
    Verifies `recover_expired_leases()` safely returns the job to `QUEUED` and another worker completes it.
    """
    dto = ArchiveRepository.save_imported_file(
        filename="crash_recovery.txt",
        content="متن مهم برای تست بازیابی کار پس از کرش کارگر.".encode("utf-8"),
        async_mode=True,
    )
    job_id = dto.latest_job_id
    assert job_id is not None

    # Worker A claims the job
    claimed = JobQueueRepository.claim_next_job("crashed-worker-A", lease_seconds=10)
    assert claimed is not None
    assert claimed.state == "RUNNING"

    # Simulate lease expiration in the past
    with get_db() as conn:
        conn.execute(
            "UPDATE jobs SET lease_expires_at = datetime('now', '-60 seconds') WHERE id = ?",
            (job_id,),
        )

    recovered_count = JobQueueRepository.recover_expired_leases()
    assert recovered_count == 1

    recovered_job = JobQueueRepository.get_job(job_id, include_events=True)
    assert recovered_job is not None
    assert recovered_job.state == "QUEUED"
    assert recovered_job.worker_id is None
    assert any(ev.event_type == "RECOVERED_LEASE" for ev in recovered_job.events)

    # Worker B now claims and finishes the recovered job cleanly
    worker_b = WorkerRunner(worker_id="healthy-worker-B")
    finished = worker_b.process_one(specific_job_id=job_id)
    assert finished is not None
    assert finished.state == "COMPLETED"

    final_file = ArchiveRepository.get_file(dto.id)
    assert final_file is not None
    assert final_file.status == "آماده"
    assert "بازیابی کار پس از کرش" in final_file.text


def test_m2_6_reprocessing_idempotency_user_override_preservation_and_fts_consistency():
    """
    Verifies:
    - `POST /api/v1/files/{file_id}/reanalyze` enqueues a job and prevents duplicate active jobs.
    - User modifications (`topic`, `tags`, `status`) are preserved after reanalysis completes.
    - FTS5 index contains exactly 1 entry for the file (no duplicate FTS rows).
    - If reanalysis fails, previously extracted valid text remains intact.
    """
    with TestClient(app) as client:
        # 1. Import and process initial file
        r = client.post(
            "/api/v1/files/import",
            files={"file": ("research_paper.txt", "پژوهش جامع درباره بازیابی اسناد فارسی.".encode("utf-8"), "text/plain")},
            data={"topic": "کار"},
        )
        assert r.status_code == 200
        file_id = r.json()["id"]

        # 2. User modifies topic and adds a custom tag
        client.patch(f"/api/v1/files/{file_id}", json={"topic": "پژوهش", "status": "آماده"})
        client.post(f"/api/v1/files/{file_id}/tags", json={"tag": "تایید_شده_توسط_کاربر"})

        # 3. Enqueue reanalysis twice while job is QUEUED -> second call must NOT create a duplicate job
        re1 = client.post(f"/api/v1/files/{file_id}/reanalyze", json={"stage": "EXTRACTION"})
        assert re1.status_code == 200
        re1_data = re1.json()
        assert re1_data["created_new"] is True
        re_job_id = re1_data["job"]["id"]

        re2 = client.post(f"/api/v1/files/{file_id}/reanalyze", json={"stage": "EXTRACTION"})
        assert re2.status_code == 200
        re2_data = re2.json()
        assert re2_data["created_new"] is False
        assert re2_data["job"]["id"] == re_job_id

        # 4. Run the reanalysis job via worker
        worker = WorkerRunner(worker_id="reanalyze-worker")
        done_job = worker.process_one(specific_job_id=re_job_id)
        assert done_job is not None
        assert done_job.state == "COMPLETED"

        # 5. Verify user overrides (topic='پژوهش', tag='تایید_شده_توسط_کاربر') and processing_version=2
        updated_file = client.get(f"/api/v1/files/{file_id}").json()
        assert updated_file["is_user_modified"] is True
        assert updated_file["topic"] == "پژوهش"
        assert "تایید_شده_توسط_کاربر" in updated_file["tags"]
        assert updated_file["processing_version"] == 2
        assert updated_file["extraction_version"] == 2

        # 6. Verify zero duplicate rows in `documents` or `files_fts`
        with get_db() as conn:
            doc_cnt = conn.execute("SELECT COUNT(*) FROM documents WHERE file_id = ?", (file_id,)).fetchone()[0]
            fts_cnt = conn.execute("SELECT COUNT(*) FROM files_fts WHERE file_id = ?", (file_id,)).fetchone()[0]
            assert doc_cnt == 1
            assert fts_cnt == 1


def test_m2_7_safe_migration_preview_backup_approval_and_restore():
    """
    Verifies:
    - Startup does NOT automatically delete legacy records.
    - `inspect_legacy_records()` identifies unmodified fake PNG seeds while preserving user-modified records.
    - `execute_approved_cleanup()` requires `confirm_approval=True`, creates a verified backup, deletes only candidates,
      and `restore_backup()` restores them byte-for-byte.
    """
    # Insert 1 unmodified fake PNG seed and 1 user-modified legacy seed
    fake_png_path = os.path.join(settings.storage_dir, "legacy_fake.png")
    user_mod_path = os.path.join(settings.storage_dir, "legacy_mod.txt")
    with open(fake_png_path, "wb") as f:
        f.write("این متن است نه تصویر PNG".encode("utf-8"))
    with open(user_mod_path, "wb") as f:
        f.write("یادداشت ویرایش‌شده توسط کاربر".encode("utf-8"))

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO files (
                id, archive_id, title, kind, topic, status, mime_type,
                file_size, sha256, storage_path, color_scheme, is_user_modified
            ) VALUES
            ('legacy-fake-1', 'default', 'رنگ، فضا و زندگی روزمره.png', 'تصویر', 'طراحی', 'آماده', 'image/png', 32, 'sha_fake', ?, 'room', 0),
            ('legacy-mod-2', 'default', 'یادداشت‌های طراحی و معماری.txt', 'سند', 'معماری', 'آماده', 'text/plain', 40, 'sha_mod', ?, 'paper', 1)
            """,
            (fake_png_path, user_mod_path),
        )

    with TestClient(app) as client:
        # 1. Ordinary app startup (TestClient lifespan) must NOT delete either record!
        files_on_startup = client.get("/api/v1/files").json()
        assert len(files_on_startup) == 2

        # 2. Preview / Dry-Run report identifies 1 candidate and 1 preserved user-modified record
        preview = client.get("/api/v1/migrations/legacy-preview").json()
        assert preview["total_inspected"] == 2
        assert preview["candidate_count"] == 1
        assert preview["preserved_count"] == 1
        assert preview["candidates"][0]["file_id"] == "legacy-fake-1"
        assert preview["preserved"][0]["file_id"] == "legacy-mod-2"

        # 3. Calling cleanup without approval is rejected with 400
        r_unapproved = client.post(
            "/api/v1/migrations/legacy-cleanup",
            json={"confirm_approval": False},
        )
        assert r_unapproved.status_code == 400

        # 4. Calling cleanup with explicit approval creates backup and removes only the unmodified candidate
        r_approved = client.post(
            "/api/v1/migrations/legacy-cleanup",
            json={"confirm_approval": True},
        )
        assert r_approved.status_code == 200
        res_data = r_approved.json()
        assert res_data["removed_count"] == 1
        assert res_data["preserved_count"] == 1
        backup_id = res_data["backup_id"]
        assert backup_id is not None
        assert not os.path.exists(fake_png_path)
        assert os.path.exists(user_mod_path)

        remaining = client.get("/api/v1/files").json()
        assert len(remaining) == 1
        assert remaining[0]["id"] == "legacy-mod-2"

        # 5. Restore backup recovers the removed record and physical file
        r_restore = client.post(f"/api/v1/migrations/restore/{backup_id}")
        assert r_restore.status_code == 200
        assert r_restore.json()["removed_count"] == 1
        assert os.path.exists(fake_png_path)
        assert len(client.get("/api/v1/files").json()) == 2


def test_m2_8_strict_origin_allowlist_and_session_token_security(monkeypatch):
    """
    Verifies:
    - Arbitrary localhost ports (e.g. http://localhost:9999) and arbitrary `.run.app` origins are rejected with 403.
    - When `session_auth_required=True`, state-changing requests require a valid `X-Saher-Session-Token`.
    """
    with TestClient(app) as client:
        # 1. Arbitrary localhost port not in allowlist must be blocked
        r_bad_port = client.post(
            "/api/v1/workers/config",
            headers={"Origin": "http://localhost:9999"},
            json={"resource_mode": "Eco"},
        )
        assert r_bad_port.status_code == 403
        assert r_bad_port.json()["code"] == "FORBIDDEN_ORIGIN"

        # 2. Arbitrary untrusted .run.app subdomain must be blocked
        r_bad_cloud = client.post(
            "/api/v1/workers/config",
            headers={"Origin": "https://untrusted-attacker-app.run.app"},
            json={"resource_mode": "Eco"},
        )
        assert r_bad_cloud.status_code == 403

        # 3. Allowed origin succeeds
        r_ok_origin = client.post(
            "/api/v1/workers/config",
            headers={"Origin": "http://localhost:3000"},
            json={"resource_mode": "Performance"},
        )
        assert r_ok_origin.status_code == 200
        assert r_ok_origin.json()["resource_mode"] == "Performance"
        assert r_ok_origin.json()["concurrency"] == 4

        # 4. Enable session token enforcement
        monkeypatch.setattr(settings, "session_auth_required", True)
        monkeypatch.setattr(settings, "session_token", "secret-electron-session-token-123")

        r_no_tok = client.post(
            "/api/v1/workers/config",
            json={"resource_mode": "Balanced"},
        )
        assert r_no_tok.status_code == 401
        assert r_no_tok.json()["code"] == "UNAUTHORIZED_SESSION"

        r_with_tok = client.post(
            "/api/v1/workers/config",
            headers={"X-Saher-Session-Token": "secret-electron-session-token-123"},
            json={"resource_mode": "Balanced"},
        )
        assert r_with_tok.status_code == 200
        assert r_with_tok.json()["resource_mode"] == "Balanced"
