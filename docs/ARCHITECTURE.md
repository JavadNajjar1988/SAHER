# معماری سیستم ساهر (SAHER System Architecture)

این سند معماری پیاده‌سازی‌شده و تأییدشدهٔ سامانه ساهر تا پایان **مایلستون ۲ (موتور پردازش پایدار و کارگرهای پس‌زمینه — Durable Processing Engine & Background Workers)** را شرح می‌دهد.

---

## ۱. ساختار کلان (Modular Monolith)

```text
├── apps/
│   └── web/                        # واسط کاربری فارسی (React 19 + TypeScript 5.7 + Vite 6)
│       ├── vite.config.ts          # پروکسی توسعه (/api و /health به FastAPI روی 127.0.0.1:8000)
│       └── src/
│           ├── components/         # قطعات رابط کاربری (Sidebar, Preview, FileDetailModal, ImportDialog, ProcessingQueueView)
│           ├── services/           # کلاینت ارتباطی نوع‌داده‌دار (بدون بازگشت پنهان به localStorage)
│           │   ├── apiClient.ts
│           │   └── apiClient.test.ts
│           ├── types/              # تعاریف مدل‌های داده، وضعیت استخراج، کارهای پایدار و حالت‌های منابع
│           └── main.tsx            # ریشهٔ برنامه، پایش زندهٔ صف پردازش و مدیریت حالت عملیاتی
├── scripts/
│   └── dev_runner.mjs              # راه‌انداز چندسکویی (Windows 11 / Linux / macOS) بدون وابستگی به نحو شل یونیکس
├── services/
│   ├── api/                        # وب‌سرویس محلی (Python 3.10+ + FastAPI)
│   │   ├── config.py               # تنظیمات سقف آپلود، فهرست مجاز صریح Origin، توکن نشست و تنظیمات کارگر
│   │   ├── database.py             # اتصال SQLite با WAL، مهاجرت‌های نسخه‌دار غیرمخرب و جداول صف پایدار
│   │   ├── migrations.py           # مدیر مهاجرت ایمن: پیش‌نمایش Dry-Run، تهیهٔ پشتیبان تأییدشده، تأیید صریح و بازیابی
│   │   ├── repository.py           # الگوی مخزن با دریافت جریانی، ثبت اتمیک کار پایدار و FTS5
│   │   ├── schemas.py              # قراردادهای داده Pydantic برای فایل‌ها، کارها، کارگرها و مهاجرت‌ها
│   │   └── main.py                 # اندپوینت‌های REST نسخه ۱ (/api/v1)، مدیریت کارها، بازپردازش و محافظت امنیتی
│   ├── ingestion/                  # موتور اعتبارسنجی باینری، نرمال‌سازی فارسی و استخراج متن
│   │   └── extractor.py            # بررسی Magic Bytes، نرمال‌سازی ي/ك و نیم‌فاصله، استخراج TXT/PDF/DOCX
│   └── worker/                     # موتور پردازش پایدار و کارگرهای مستقل پایتون (Milestone 2)
│       ├── lifecycle.py            # وضعیت‌های چرخهٔ حیات کار، مراحل پردازش، پروفایل‌های منابع و محاسبهٔ Backoff
│       ├── queue.py                # صف تراکنشی SQLite، دریافت اتمیک کار (BEGIN IMMEDIATE) و بازیابی Lease
│       ├── handlers.py             # اجرای مرحله‌به‌مرحلهٔ استخراج، نمایه‌سازی FTS5 و حفظ ویرایش‌های کاربر
│       └── runner.py               # ناظر کارگر پس‌زمینه با استخر نخ قابل تنظیم، ضربان قلب و اجرای مستقل
├── tests/
│   ├── test_api.py                 # آزمون‌های یکپارچگی مایلستون ۱.۵ (آپلود، امنیت، FTS5 و اتمیک بودن)
│   └── test_worker_and_jobs.py     # آزمون‌های مایلستون ۲ (صف پایدار، هم‌زمانی کارگرها، بازیابی کرش، بازپردازش و مهاجرت ایمن)
└── pyproject.toml                  # مشخصات تکرارپذیر وابستگی‌های پایتون و تنظیمات pytest
```

---

## ۲. مدل دادهٔ کار پایدار (Durable Job Model)

در مایلستون ۲، جداول زیر از طریق مهاجرت نسخه‌دار و غیرمخرب (`002_milestone_2_durable_jobs`) به پایگاه‌داده SQLite افزوده شده‌اند:

1. **`jobs` (جدول کارهای پردازشی پایدار)**:
   - `id`: شناسهٔ یکتای کار (UUID)
   - `archive_id` و `file_id`: کلیدهای خارجی به آرشیو و فایل مرتبط
   - `job_type`: نوع کار (`FILE_INGESTION`، `REANALYZE`، `STAGE_REPROCESS`)
   - `target_stage` و `processing_stage`: مرحلهٔ هدف و مرحلهٔ جاری پردازش
   - `state`: وضعیت چرخهٔ حیات کار (`QUEUED`, `RUNNING`, `PAUSED`, `COMPLETED`, `FAILED`, `CANCELLED`)
   - `priority`: اولویت اجرا (عدد بزرگ‌تر = اولویت بالاتر؛ پیش‌فرض `50` برای واردسازی و `60` برای بازپردازش)
   - `attempt_count` و `max_retries`: شمارندهٔ تلاش‌های انجام‌شده و سقف تلاش مجدد
   - `progress` و `progress_message`: درصد پیشرفت واقعی مرحله‌ای (`0.0` تا `100.0`) و توضیح مرحله
   - `error_code`, `error_message`, `is_retryable`: کد و پیام خطای ساخت‌یافته و قابلیت تلاش مجدد
   - `worker_id`, `lease_expires_at`, `heartbeat_at`: مالکیت کارگر و زمان انقضای Lease برای تشخیص کرش
   - `next_run_at`: زمان اجرای بعدی (برای پیاده‌سازی تأخیر نمایی تلاش مجدد)
   - `processing_version` و `checkpoint_json`: نسخهٔ پردازش و متادیتای نقطهٔ بازیابی (Checkpoint)
   - `created_at`, `started_at`, `updated_at`, `completed_at`: زمان‌بندی‌های کامل چرخهٔ حیات

2. **`job_events` (تاریخچهٔ تلاش‌ها و رویدادهای اجرای کار)**:
   - ثبت تمام تغییر وضعیت‌ها (`CREATED`, `CLAIMED`, `STAGE_TRANSITION`, `PAUSED`, `RESUMED`, `RETRY_SCHEDULED`, `RECOVERED_LEASE`, `COMPLETED`, `FAILED`, `CANCELLED`) به تفکیک شمارهٔ تلاش (`attempt_number`) و شناسهٔ کارگر (`worker_id`).

3. **`worker_registry` (ثبت وضعیت کارگرها و منابع)**:
   - نگهداری شناسهٔ کارگر، حالت منابع (`Eco`, `Balanced`, `Performance`)، تعداد هم‌زمانی، تعداد کارهای فعال و آخرین ضربان قلب (`last_heartbeat_at`).

---

## ۳. چرخهٔ حیات کار و مراحل پردازش (Job States & Processing Stages)

### الف) انتقال وضعیت‌های مجاز (Job State Transitions)
- `QUEUED` $\rightarrow$ `RUNNING` (دریافت اتمیک توسط کارگر)، `PAUSED` (توقف توسط کاربر)، `CANCELLED` (لغو توسط کاربر)
- `RUNNING` $\rightarrow$ `COMPLETED` (اتمام موفق)، `QUEUED` (زمان‌بندی تلاش مجدد یا بازیابی Lease منقضی)، `FAILED` (خطای دائمی یا اتمام سقف تلاش)، `PAUSED`، `CANCELLED`
- `PAUSED` $\rightarrow$ `QUEUED` (ادامه توسط کاربر)، `CANCELLED`
- `FAILED` $\rightarrow$ `QUEUED` (تلاش مجدد دستی)، `CANCELLED`
- `CANCELLED` $\rightarrow$ `QUEUED` (تلاش مجدد دستی)

### ب) مراحل پردازش مستقل از وضعیت فایل (Processing Stages)
1. `DISCOVERY`: بررسی رکورد فایل و وجود فیزیکی در مخزن دیسک (`10%`)
2. `VALIDATION`: بررسی یکپارچگی هش `SHA-256` روی دیسک و امضای باینری (`25%`)
3. `EXTRACTION`: استخراج متن واقعی از `TXT/MD/CSV/JSON/PDF/DOCX` یا تشخیص تصویر/PDF اسکن‌شده (`55%`)
4. `OCR_PENDING` / `ANALYSIS_PENDING`: برای تصاویر و اسناد PDF اسکن‌شده؛ کار مایلستون ۲ بدون جعل متن OCR در این مرحله ثبت شده و وضعیت استخراج فایل `pending_ocr` باقی می‌ماند.
5. `INDEXING`: بروزرسانی جدول `documents`، صفحات `pages` و نمایهٔ تمام‌متن `files_fts` به‌صورت تکرارناپذیر (Idempotent) (`80%`)
6. `FINALIZATION`: ثبت `processing_version` و تکمیل کار (`100%`)

---

## ۴. سیاست بازیابی، تلاش مجدد و تکرارناپذیری (Recovery, Retry & Idempotency Policy)

- **دریافت اتمیک کار (Atomic Claiming)**: کارگرها با تراکنش `BEGIN IMMEDIATE` در SQLite کار آماده را انتخاب و هم‌زمان `state = 'RUNNING'`، `worker_id` و `lease_expires_at` را ثبت می‌کنند تا دو کارگر هم‌زمان هرگز یک کار واحد را اجرا نکنند.
- **بازیابی خودکار کرش کارگر (Crash & Lease Recovery)**: در صورت توقف ناگهانی کارگر یا ری‌استارت برنامه، کارهای در وضعیت `RUNNING` که زمان `lease_expires_at` آن‌ها گذشته است توسط `recover_expired_leases()` شناسایی شده و در صورت نرسیدن به سقف `max_retries` با حفظ `checkpoint_json` به وضعیت `QUEUED` بازگردانده می‌شوند.
- **تأخیر نمایی (Exponential Backoff)**: خطاهای موقت (`RetryableJobError` یا قفل موقت SQLite) با فرمول $\min(60, \text{base} \times 2^{\text{attempt}-1})$ زمان‌بندی مجدد می‌شوند، در حالی که خطاهای دائمی (`PermanentJobError` مانند PDF رمزدار یا امضای باینری نامعتبر) بلافاصله به وضعیت `FAILED` می‌روند.
- **حفظ ویرایش‌های کاربر و داده‌های معتبر قبلی**: در زمان بازپردازش (`REANALYZE`)، اگر کاربر موضوع، برچسب‌ها یا وضعیت فایل را دستی تغییر داده باشد (`is_user_modified = 1`)، کارگر آن‌ها را بازنویسی نمی‌کند. همچنین در صورت بروز خطا در بازپردازش، متن معتبر قبلی در `documents` و `files_fts` حفظ می‌شود.

---

## ۵. مدیریت منابع (Resource Modes)

| حالت منابع | هم‌زمانی کارگر (`concurrency`) | فاصلهٔ پایش (`poll_interval`) | کاربرد پیشنهادی |
|---|---|---|---|
| **Eco (کم‌مصرف)** | ۱ کارگر | `0.8s` | کار در پس‌زمینه روی لپ‌تاپ با حداقل مصرف پردازنده |
| **Balanced (متعادل)** | ۲ کارگر | `0.35s` | حالت پیش‌فرض برای کاربری روزمره در ویندوز ۱۱ |
| **Performance (حداکثر توان)** | ۴ کارگر | `0.15s` | واردسازی و نمایه‌سازی دسته‌ای اسناد پرحجم |

---

## ۶. اندپوینت‌های API نسخه ۱ (`/api/v1`)

- `GET /health` — وضعیت سلامت سرویس، پایگاه‌داده، فضای ذخیره‌سازی و کارگر پس‌زمینه
- `GET /api/v1/auth/session` — تبادل اطلاعات نشست امنیتی محلی
- `GET /api/v1/stats` — آمار کلی فایل‌ها و شمارنده‌های صف پردازش
- `GET /api/v1/files` و `GET /api/v1/files/{file_id}` — فهرست، جست‌وجوی FTS5 و جزئیات فایل به همراه آخرین وضعیت کار
- `POST /api/v1/files/import` — واردسازی جریانی فایل و ثبت کار پایدار (پشتیبانی از `async_mode=true` برای بازگشت فوری و اجرای پس‌زمینه)
- `POST /api/v1/files/{file_id}/reanalyze` — ثبت کار بازپردازش کنترل‌شده (با جلوگیری از ایجاد کار تکراری فعال)
- `GET /api/v1/jobs` و `GET /api/v1/jobs/{job_id}` — فهرست کارهای صف (با فیلتر وضعیت و مرحله) و دریافت جزئیات به همراه تاریخچهٔ `events`
- `POST /api/v1/jobs/{job_id}/pause` — توقف موقت کار
- `POST /api/v1/jobs/{job_id}/resume` — ادامهٔ کار متوقف‌شده
- `POST /api/v1/jobs/{job_id}/cancel` — لغو کار
- `POST /api/v1/jobs/{job_id}/retry` — تلاش مجدد کار خطادار یا لغوشده
- `POST /api/v1/workers/config` — تغییر حالت منابع (`Eco` / `Balanced` / `Performance`) و هم‌زمانی کارگرها
- `GET /api/v1/migrations/legacy-preview` — گزارش پیش‌نمایش غیرمخرب (Dry-Run) رکوردهای قدیمی
- `POST /api/v1/migrations/legacy-cleanup` — پاک‌سازی رکوردهای نمونهٔ قدیمی صرفاً با تأیید صریح کاربر و پس از تهیهٔ نسخهٔ پشتیبان تأییدشده
- `POST /api/v1/migrations/restore/{backup_id}` — بازیابی کامل رکوردها و فایل‌ها از نسخهٔ پشتیبان مهاجرت
