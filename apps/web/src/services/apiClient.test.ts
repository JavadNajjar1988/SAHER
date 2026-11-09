import test from "node:test";
import assert from "node:assert/strict";
import { ArchiveApiClient, ApiClientError } from "./apiClient";

test("ArchiveApiClient never silently falls back to localStorage on network outage", async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async () => {
      throw new TypeError("Failed to fetch");
    };

    await assert.rejects(
      async () => {
        await ArchiveApiClient.listFiles();
      },
      (err: unknown) => {
        assert.ok(err instanceof ApiClientError);
        assert.equal(err.isNetworkError, true);
        assert.equal(err.code, "NETWORK_UNREACHABLE");
        return true;
      },
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("ArchiveApiClient surfaces structured FastAPI HTTP 409 duplicate errors", async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async () =>
      new Response(
        JSON.stringify({
          detail: "این فایل قبلاً در آرشیو ثبت شده است.",
          code: "DUPLICATE_FILE",
          existing_file_id: "abc-123",
          existing_title: "report.pdf",
        }),
        {
          status: 409,
          headers: { "Content-Type": "application/json" },
        },
      );

    await assert.rejects(
      async () => {
        await ArchiveApiClient.getStats();
      },
      (err: unknown) => {
        assert.ok(err instanceof ApiClientError);
        assert.equal(err.status, 409);
        assert.equal(err.code, "DUPLICATE_FILE");
        assert.equal(err.existingFileId, "abc-123");
        assert.equal(err.existingTitle, "report.pdf");
        return true;
      },
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("ArchiveApiClient lists durable jobs with filters and executes pause/resume/retry/cancel/reanalyze controls", async () => {
  const originalFetch = globalThis.fetch;
  const calledRequests: { url: string; method: string }[] = [];

  try {
    globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method || "GET";
      calledRequests.push({ url, method });

      if (url.startsWith("/api/v1/jobs?")) {
        return new Response(
          JSON.stringify({
            total: 1,
            limit: 50,
            offset: 0,
            stats: {
              queued: 1,
              running: 0,
              paused: 0,
              completed: 2,
              failed: 0,
              cancelled: 0,
              total: 3,
            },
            workers: [
              {
                worker_id: "worker-1",
                resource_mode: "Balanced",
                concurrency: 2,
                active_jobs: 0,
                status: "ONLINE",
              },
            ],
            resource_mode: "Balanced",
            worker_concurrency: 2,
            items: [
              {
                id: "job-101",
                archive_id: "default",
                file_id: "file-55",
                file_title: "architecture.pdf",
                file_kind: "سند",
                file_status: "در صف",
                job_type: "FILE_INGESTION",
                processing_stage: "EXTRACTION",
                state: "QUEUED",
                priority: 50,
                attempt_count: 1,
                max_retries: 3,
                progress: 55,
                is_retryable: true,
                processing_version: 1,
                created_at: "2026-11-07T00:00:00Z",
              },
            ],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }

      if (url.endsWith("/pause") || url.endsWith("/resume") || url.endsWith("/cancel") || url.endsWith("/retry")) {
        const action = url.split("/").pop();
        const newState =
          action === "pause"
            ? "PAUSED"
            : action === "cancel"
              ? "CANCELLED"
              : "QUEUED";
        return new Response(
          JSON.stringify({
            id: "job-101",
            archive_id: "default",
            file_id: "file-55",
            file_title: "architecture.pdf",
            file_kind: "سند",
            file_status: "در صف",
            job_type: "FILE_INGESTION",
            processing_stage: "EXTRACTION",
            state: newState,
            priority: 50,
            attempt_count: 1,
            max_retries: 3,
            progress: 55,
            is_retryable: true,
            processing_version: 1,
            created_at: "2026-11-07T00:00:00Z",
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }

      if (url.endsWith("/reanalyze")) {
        return new Response(
          JSON.stringify({
            created_new: true,
            message: "کار بازپردازش جدید در صف قرار گرفت.",
            job: {
              id: "job-102",
              archive_id: "default",
              file_id: "file-55",
              file_title: "architecture.pdf",
              file_kind: "سند",
              file_status: "آماده",
              job_type: "STAGE_REPROCESS",
              target_stage: "EXTRACTION",
              processing_stage: "EXTRACTION",
              state: "QUEUED",
              priority: 60,
              attempt_count: 0,
              max_retries: 3,
              progress: 0,
              is_retryable: true,
              processing_version: 2,
              created_at: "2026-11-07T00:05:00Z",
            },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }

      throw new Error(`Unexpected URL: ${url}`);
    };

    const listResp = await ArchiveApiClient.listJobs({ state: "QUEUED", stage: "EXTRACTION" });
    assert.equal(listResp.stats.queued, 1);
    assert.equal(listResp.items[0].id, "job-101");

    const paused = await ArchiveApiClient.pauseJob("job-101");
    assert.equal(paused.state, "PAUSED");

    const resumed = await ArchiveApiClient.resumeJob("job-101");
    assert.equal(resumed.state, "QUEUED");

    const cancelled = await ArchiveApiClient.cancelJob("job-101");
    assert.equal(cancelled.state, "CANCELLED");

    const retried = await ArchiveApiClient.retryJob("job-101");
    assert.equal(retried.state, "QUEUED");

    const reanalyzed = await ArchiveApiClient.reanalyzeFile("file-55", "EXTRACTION");
    assert.equal(reanalyzed.created_new, true);
    assert.equal(reanalyzed.job.processing_version, 2);
    assert.equal(calledRequests.length, 6);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("ArchiveApiClient supports Milestone 3 page-level OCR inspection, manual page edits, and preview URLs", async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method || "GET";

      if (url === "/api/v1/ocr/status") {
        return new Response(
          JSON.stringify({
            available: true,
            engine_name: "tesseract",
            engine_version: "5.3.0",
            model_dir: "/app/data/models/tessdata",
            languages: ["fas", "eng"],
            installed_models: ["fas.traineddata", "eng.traineddata"],
            missing_models: [],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }

      if (url === "/api/v1/files/file-55/pages" && method === "GET") {
        return new Response(
          JSON.stringify([
            {
              file_id: "file-55",
              page_number: 1,
              raw_text: "گزارش مالی ساهر",
              normalized_text: "گزارش مالی ساهر",
              char_count: 15,
              extraction_method: "ocr_pdf_page",
              page_status: "ready",
              ocr_confidence: 92.4,
              width: 1000,
              height: 480,
              is_user_modified: false,
              bboxes: [{ text: "گزارش", x: 60, y: 48, width: 110, height: 36, confidence: 93.1, line_num: 1, block_num: 1 }],
            },
          ]),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }

      if (url === "/api/v1/files/file-55/pages/1" && method === "PATCH") {
        return new Response(
          JSON.stringify({
            file_id: "file-55",
            page_number: 1,
            raw_text: "متن اصلاح‌شده صفحه اول",
            normalized_text: "متن اصلاح شده صفحه اول",
            char_count: 22,
            extraction_method: "user_edit",
            page_status: "ready",
            is_user_modified: true,
            bboxes: [],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }

      throw new Error(`Unexpected URL: ${url}`);
    };

    const ocrStatus = await ArchiveApiClient.getOcrStatus();
    assert.equal(ocrStatus.available, true);
    assert.equal(ocrStatus.engine_name, "tesseract");

    const pages = await ArchiveApiClient.getFilePages("file-55");
    assert.equal(pages.length, 1);
    assert.equal(pages[0].page_number, 1);
    assert.equal(pages[0].bboxes.length, 1);

    const edited = await ArchiveApiClient.updatePageText("file-55", 1, "متن اصلاح‌شده صفحه اول");
    assert.equal(edited.is_user_modified, true);

    const previewUrl = ArchiveApiClient.getPagePreviewUrl("file-55", 2);
    assert.equal(previewUrl, "/api/v1/files/file-55/pages/2/preview");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("ArchiveApiClient analyzes image folders and exports Word (.docx) reports", async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method || "GET";

      if (url === "/api/v1/images/analyze-folder" && method === "POST") {
        return new Response(
          JSON.stringify({
            folder_name: "پوشه فاکتورها",
            total_images: 1,
            topic_breakdown: { "مالی و حسابداری": 1 },
            nature_breakdown: { "فاکتور، رسید یا صورت‌حساب مالی": 1 },
            items: [
              {
                file_id: "img-101",
                title: "invoice_scan.png",
                relative_path: "invoices/invoice_scan.png",
                mime_type: "image/png",
                file_size: 24500,
                width: 1000,
                height: 700,
                orientation: "افقی (Landscape)",
                aspect_ratio: 1.43,
                color_profile_label: "روشن با پس‌زمینهٔ سفید (سند اسکن‌شده یا برگهٔ اداری)",
                dominant_color_hex: "#f8f9fa",
                mean_brightness: 240.2,
                contrast_std: 34.1,
                image_nature: "فاکتور، رسید یا صورت‌حساب مالی",
                detected_topic: "مالی و حسابداری",
                suggested_tags: ["مالی و حسابداری", "فاکتور و صورت‌حساب", "دارای متن فارسی/انگلیسی"],
                has_text: true,
                ocr_word_count: 18,
                ocr_char_count: 95,
                ocr_confidence: 91.5,
                ocr_excerpt: "فاکتور رسمی فروش کالا و خدمات",
                analysis_summary: "این فایل با عنوان «invoice_scan.png» از نظر ماهیت بصری و ساختاری یک «فاکتور، رسید یا صورت‌حساب مالی» تشخیص داده شد.",
                key_findings: ["ماهیت تشخیص‌داده‌شده: فاکتور، رسید یا صورت‌حساب مالی"],
              },
            ],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }

      if (url === "/api/v1/images/export-word" && method === "POST") {
        return new Response(new Uint8Array([0x50, 0x4b, 0x03, 0x04]), {
          status: 200,
          headers: {
            "Content-Type":
              "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
          },
        });
      }

      throw new Error(`Unexpected URL: ${url}`);
    };

    const dummyFile = new File([new Uint8Array([137, 80, 78, 71])], "invoice_scan.png", {
      type: "image/png",
    });
    const folderRes = await ArchiveApiClient.analyzeImageFolder(
      [dummyFile],
      "پوشه فاکتورها",
      "https://www.instagram.com/mira_rjbpr?stkn=YzM4MWNpN3Y2a3Vy",
    );
    assert.equal(folderRes.total_images, 1);
    assert.equal(folderRes.items[0].detected_topic, "مالی و حسابداری");
    assert.equal(folderRes.items[0].image_nature, "فاکتور، رسید یا صورت‌حساب مالی");

    const wordBlob = await ArchiveApiClient.downloadImagesWordReport(
      ["img-101"],
      "پوشه فاکتورها",
      {
        sourceUrl: "https://www.instagram.com/mira_rjbpr?stkn=YzM4MWNpN3Y2a3Vy",
      },
    );
    assert.ok(wordBlob.size > 0);

    const singleWordUrl = ArchiveApiClient.getSingleFileWordUrl("img-101");
    assert.equal(singleWordUrl, "/api/v1/files/img-101/export-word");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

