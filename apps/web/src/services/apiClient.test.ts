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
