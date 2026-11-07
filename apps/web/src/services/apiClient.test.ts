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
