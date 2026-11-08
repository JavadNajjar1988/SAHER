# معماری سیستم ساهر (SAHER System Architecture)

این سند معماری پیاده‌سازی‌شده و تأییدشدهٔ سامانه ساهر تا پایان **مایلستون ۳ (تشخیص متن فارسی و انگلیسی آفلاین، اسناد ترکیبی و جست‌وجوی صفحه‌محور — Offline Persian/English OCR, Hybrid PDF & Page-Level Search)** را شرح می‌دهد.

---

## ۱. ساختار کلان (Modular Monolith)

```text
├── apps/
│   └── web/                        # واسط کاربری فارسی (React 19 + TypeScript 5.7 + Vite 6)
│       ├── vite.config.ts          # پروکسی توسعه (/api و /health به FastAPI)
│       └── src/
│           ├── components/         # قطعات رابط کاربری (Sidebar, Preview, FileDetailModal, ImportDialog, ProcessingQueueView)
│           ├── services/           # کلاینت ارتباطی نوع‌داده‌دار (بدون بازگشت پنهان به localStorage)
│           │   ├── apiClient.ts
│           │   └── apiClient.test.ts
│           ├── types/              # تعاریف مدل‌های داده، صفحات، مختصات OCR، کارهای پایدار و حالت‌های منابع
│           └── main.tsx            # ریشهٔ برنامه، پایش زندهٔ صف پردازش، ناوبری مستقیم از جست‌وجو به صفحهٔ منطبق
├── data/
│   └── models/
│       ├── tessdata/               # مدل‌های آفلاین Tesseract 5 LSTM (fas.traineddata, eng.traineddata, osd.traineddata)
│       └── fonts/                  # فونت محلی Vazirmatn.ttf برای رندر پیش‌نمایش برگه‌های آرشیوی
├── scripts/
│   └── dev_runner.mjs              # راه‌انداز چندسکویی (Windows 11 / Linux / macOS)
├── services/
│   ├── api/                        # وب‌سرویس محلی (Python 3.10+ + FastAPI)
│   │   ├── config.py               # تنظیمات سقف آپلود، امنیت، مسیر مدل‌های OCR (SAHER_OCR_MODEL_DIR) و کارگرها
│   │   ├── database.py             # اتصال SQLite با WAL، مهاجرت‌های غیرمخرب (تا نسخه 003) و جداول pages_fts / files_fts
│   │   ├── migrations.py           # مدیر مهاجرت ایمن: پیش‌نمایش Dry-Run، تهیهٔ پشتیبان تأییدشده و بازیابی
│   │   ├── repository.py           # الگوی مخزن با دریافت جریانی، جست‌وجوی صفحه‌محور (matched_page) و ویرایش دستی صفحه
│   │   ├── schemas.py              # قراردادهای داده Pydantic برای فایل‌ها، صفحات، مختصات Bounding Box، کارها و سلامت OCR
│   │   └── main.py                 # اندپوینت‌های REST نسخه ۱ (/api/v1)، پیش‌نمایش تصویری صفحات، ویرایش صفحه و وضعیت OCR
│   ├── ocr/                        # لایهٔ انتزاعی و قابل تعویض تشخیص متن آفلاین (Milestone 3)
│   │   ├── base.py                 # رابط انتزاعی OCREngineAdapter، مدل‌های خروجی و خطاهای OCRModelMissingError / OCRPageReadError
│   │   ├── tesseract_engine.py     # پیاده‌سازی آفلاین Tesseract 5 (fas+eng) با استخراج مختصات کلمات و ترتیب خواندن راست‌به‌چپ
│   │   └── __init__.py             # کارخانهٔ انتخاب موتور OCR (get_ocr_engine)
│   ├── ingestion/                  # موتور اعتبارسنجی باینری، نرمال‌سازی فارسی، تفکیک PDF ترکیبی و رندر صفحات
│   │   └── extractor.py            # بررسی Magic Bytes، نرمال‌سازی ي/ك/نیم‌فاصله/حذف RLM، تفکیک صفحات متنی و اسکن‌شده در PDF
│   └── worker/                     # موتور پردازش پایدار و کارگرهای مستقل پایتون (Milestones 2 & 3)
│       ├── lifecycle.py            # وضعیت‌های چرخهٔ حیات کار، مراحل پردازش، پروفایل‌های منابع و محاسبهٔ Backoff
│       ├── queue.py                # صف تراکنشی SQLite، دریافت اتمیک کار و گزارش وضعیت واقعی کارگرهای مستقل (worker_registry)
│       ├── handlers.py             # اجرای مرحله‌به‌مرحلهٔ استخراج، OCR صفحه‌به‌صفحه با Checkpoint، ایزوله‌سازی خطای صفحه و حفظ ویرایش‌ها
│       └── runner.py               # ناظر کارگر پس‌زمینه با استخر نخ قابل تنظیم، ضربان قلب و اجرای مستقل
├── Dockerfile                      # تصویر داکر آفلاین شامل موتور Tesseract 5 و بسته‌های زبان فارسی و انگلیسی
├── docker-compose.yml              # اجرای جداسازی‌شدهٔ saher-api و کارگر مستقل saher-worker روی شبکهٔ داخلی بدون اینترنت
└── tests/
    ├── test_api.py                 # آزمون‌های یکپارچگی مایلستون ۱.۵
    ├── test_worker_and_jobs.py     # آزمون‌های مایلستون ۲ (صف پایدار، هم‌زمانی کارگرها، بازیابی کرش و مهاجرت ایمن)
    └── test_milestone3_ocr.py      # آزمون‌های پذیرش مایلستون ۳ (OCR تصویر فارسی، PDF اسکن‌شده چندصفحه‌ای، PDF ترکیبی، خطای صفحه و کارگر مستقل)
```

---

## ۲. موتور تشخیص متن آفلاین (Pluggable Offline OCR Engine — Milestone 3)

### ۲.۱ رابط قابل تعویض (`OCREngineAdapter`)
در مسیر `services/ocr/base.py`، کلاس پایهٔ انتزاعی `OCREngineAdapter` تعریف شده است تا منطق صف پردازش و API هیچ وابستگی مستقیمی به کتابخانهٔ خاص OCR نداشته باشند. پیاده‌سازی پیش‌فرض (`TesseractOCREngine` در `services/ocr/tesseract_engine.py`) از طریق متغیر محیطی `SAHER_OCR_ENGINE=tesseract` بارگذاری می‌شود و در آینده می‌توان بدون تغییر در `handlers.py` یا `repository.py`، موتورهای دیگر (مانند PaddleOCR یا Surya) را جایگزین کرد.

### ۲.۲ مشخصات نسخهٔ موتور، مدل‌ها و مسیر فایل‌ها
| مؤلفه | نسخه / مشخصات | مسیر در مخزن / کانتینر |
|---|---|---|
| **موتور باینری** | `tesseract 5.3.0` (مبتنی بر شبکهٔ عصبی LSTM، به همراه `leptonica-1.82.0` و `libraqm0`) | `/usr/bin/tesseract` |
| **مدل زبان فارسی** | `fas.traineddata` (مدل رسمی Tesseract 5 LSTM برای خط فارسی — ۴۲۲ کیلوبایت) | `data/models/tessdata/fas.traineddata` |
| **مدل زبان انگلیسی** | `eng.traineddata` (مدل رسمی Tesseract 5 LSTM برای متون و شناسه‌های لاتین — ۴.۰ مگابایت) | `data/models/tessdata/eng.traineddata` |
| **مدل تشخیص جهت صفحه** | `osd.traineddata` (Orientation & Script Detection — ۱۰.۵ مگابایت) | `data/models/tessdata/osd.traineddata` |
| **مسیر پیکربندی مدل‌ها** | متغیر محیطی `SAHER_OCR_MODEL_DIR` (پیش‌فرض: `<ریشهٔ پروژه>/data/models/tessdata`) | ارسال صریح با فلگ `--tessdata-dir` در زمان اجرا |

### ۲.۳ شیوهٔ نصب و اجرای کاملاً آفلاین
1. **در محیط لینوکس / اوبونتو / دبیان (و ایمیج Docker)**:
   ```bash
   apt-get update && apt-get install -y --no-install-recommends \
       tesseract-ocr tesseract-ocr-fas tesseract-ocr-eng libraqm0
   mkdir -p data/models/tessdata
   cp /usr/share/tesseract-ocr/5/tessdata/{fas,eng,osd}.traineddata data/models/tessdata/
   ```
2. **در محیط ویندوز ۱۱**:
   - نصب باینری Tesseract 5 و قرار دادن فایل‌های `fas.traineddata` و `eng.traineddata` در پوشهٔ `data\models\tessdata`.
3. **تضمین اجرای بدون اینترنت**:
   - موتور `TesseractOCREngine` در زمان اجرا هیچ درخواست شبکه‌ای ارسال نمی‌کند و صرفاً از فایل‌های موجود در `SAHER_OCR_MODEL_DIR` استفاده می‌کند.
4. **گزارش خطای مشخص در صورت نبود مدل (`OCR_MODEL_MISSING`)**:
   - اگر باینری موتور یا هر یک از فایل‌های مدل (`fas.traineddata` یا `eng.traineddata`) در مسیر `SAHER_OCR_MODEL_DIR` موجود نباشد، متد `ensure_ready()` و اندپوینت `GET /api/v1/ocr/status` کد خطای صریح `OCR_MODEL_MISSING` را به همراه نام دقیق فایل‌های مفقود و دستور نصب بستهٔ لازم (`tesseract-ocr-fas` / `tesseract-ocr-eng`) برمی‌گردانند.

---

## ۳. پردازش تصاویر، اسناد اسکن‌شده و اسناد ترکیبی (Hybrid PDF Pipeline)

1. **اسناد متنی دیجیتال (`TXT, MD, CSV, JSON, DOCX`)**:
   - مسیر استخراج مستقیم حفظ شده است (`direct_text` و `docx_text`) و بدون ورود به مرحلهٔ `OCR_PENDING` مستقیماً در `INDEXING` نمایه‌سازی می‌شوند.
2. **تصاویر (`PNG, JPG, WEBP, BMP`)**:
   - تصاویر واقعی در مرحلهٔ `EXTRACTION` شناسایی شده و با `needs_ocr_pages = [1]` وارد مرحلهٔ `OCR_PENDING` در صف پایدار می‌شوند تا متن خام، متن نرمال‌شده و مختصات قطعات متن (`bboxes`) استخراج گردد (`extraction_method = 'ocr_image'`).
3. **اسناد PDF دیجیتال، اسکن‌شده و ترکیبی (Hybrid PDF)**:
   - در مرحلهٔ `EXTRACTION`، هر صفحهٔ PDF به صورت مستقل بررسی می‌شود:
     - اگر صفحه دارای لایهٔ متنی دیجیتال قابل استفاده (`>= 15` نویسهٔ معنادار) باشد، متن آن مستقیماً خوانده شده (`extraction_method = 'pdf_text'`) و وارد لیست OCR نمی‌شود.
     - فقط صفحاتی که فاقد لایهٔ متنی قابل استفاده هستند در فهرست `needs_ocr_pages` قرار می‌گیرند.
   - در مرحلهٔ `OCR_PENDING`، کارگر فقط صفحات موجود در `needs_ocr_pages` را با `pypdfium2` به تصویر رندر کرده و به موتور OCR می‌سپارد (`extraction_method = 'ocr_pdf_page'`).
   - در صورتی که یک سند PDF ترکیبی از صفحات دیجیتال و صفحات اسکن‌شده باشد، روش استخراج کل سند `hybrid_pdf_ocr` ثبت می‌شود.

---

## ۴. ذخیره‌سازی صفحه‌محور، مختصات و جست‌وجوی فارسی (`pages` & `pages_fts`)

در مهاجرت غیرمخرب `003_milestone_3_ocr_and_pages_fts`، ساختار ذخیره‌سازی صفحه‌محور تکمیل شده است:
- **جدول `pages`**:
  - ذخیرهٔ `page_number` (شمارهٔ صفحه از ۱ تا N)، `raw_text` (متن خام استخراج‌شده)، `normalized_text` (متن نرمال‌شده برای جست‌وجو)، `bboxes_json` (آرایهٔ مختصات قطعات متن شامل `text, x, y, width, height, confidence, line_num, block_num, direction`)، `extraction_method`، `page_status` (`extracted`, `failed`, `user_modified`, `empty`)، `error_code`، `error_message` و `is_user_modified`.
- **نرمال‌سازی ویژهٔ زبان فارسی**:
  - یکسان‌سازی نویسه‌های عربی و فارسی (`ي/ى` $\rightarrow$ `ی`، `ك` $\rightarrow$ `ک`، `ة` $\rightarrow$ `ه`، ارقام فارسی/عربی به استاندارد).
  - حذف نویسه‌های کنترلی نامرئی جهت‌دهی (`RLM \u200f` و `LRM \u200e`) که موتورهای OCR در انتهای کلمات فارسی درج می‌کنند تا مرز کلمات در نمایه‌سازی مخدوش نشود.
  - حفظ نیم‌فاصله (`ZWNJ \u200c`) در متن نمایشی و بسط هوشمند کلمات دارای نیم‌فاصله در `normalize_for_fts` به‌گونه‌ای که هم جست‌وجوی عبارات چندکلمه‌ای (حفظ مجاورت کلمات) و هم جست‌وجوی با نیم‌فاصله، با فاصله یا چسبیده نتیجهٔ دقیق برگردانند.
- **جدول مجازی `pages_fts` (FTS5)**:
  - نمایه‌سازی تمام‌متن به تفکیک هر صفحه (`file_id, page_number, normalized_text`).
  - در زمان جست‌وجو (`GET /api/v1/files?query=...`)، علاوه بر تطابق در سطح سند (`files_fts`)، صفحات منطبق از `pages_fts` استخراج شده و شمارهٔ اولین صفحهٔ منطبق (`matched_page`)، فهرست تمام صفحات منطبق (`matched_pages`) و بریدهٔ متن همان صفحه (`matched_snippet`) در نتیجهٔ جست‌وجو بازگردانده می‌شوند.

---

## ۵. ایزوله‌سازی خطای صفحه، حفظ ویرایش‌های کاربر و تکرارناپذیری

- **ایزوله‌سازی خطای خواندن یک صفحه**: اگر در یک سند چندصفحه‌ای، خواندن یا رندر یک صفحهٔ خاص با خطا مواجه شود (مثلاً خرابی جریان تصویر در صفحهٔ ۲: `PDF_PAGE_STREAM_CORRUPTED`)، خطا با ذکر شمارهٔ دقیق همان صفحه (`خطا در خواندن متن صفحهٔ 2: ...`) در رکورد صفحه (`page_status = 'failed'`) و رویداد کار (`PAGE_OCR_ERROR`) ثبت می‌شود، اما متن سالم صفحات دیگر (مثلاً صفحات ۱ و ۳) به‌طور کامل ذخیره و در `pages_fts` و `files_fts` نمایه‌سازی می‌شود و وضعیت فایل `نیازمند بازبینی` به همراه `failed_pages = [2]` ثبت می‌گردد.
- **نقطهٔ بازیابی صفحه‌ای (Per-Page Checkpointing)**: پس از اتمام OCR هر صفحه، نتیجهٔ آن صفحه در `checkpoint_json.ocr_completed_pages` ذخیره می‌شود. در صورت توقف کار (`Pause`)، ادامه (`Resume`) یا کرش و راه‌اندازی مجدد کارگر، صفحات تکمیل‌شده مجدداً OCR نمی‌شوند و در مرحلهٔ `INDEXING`، بازنویسی اتمیک بر اساس کلید `(file_id, page_number)` مانع از ایجاد رکورد تکراری در `pages`، `pages_fts` یا `files_fts` می‌شود.
- **حفظ اصلاح‌های دستی کاربر و متن معتبر قبلی در بازپردازش (`reanalyze`)**:
  - کاربر می‌تواند متن هر صفحه را از طریق جزئیات فایل (`PATCH /api/v1/files/{id}/pages/{page_number}`) ویرایش کند (`pages.is_user_modified = 1`).
  - در زمان بازپردازش (`POST /api/v1/files/{id}/reanalyze`)، صفحاتی که دارای `is_user_modified = 1` هستند دست‌نخورده حفظ می‌شوند. همچنین اگر صفحه‌ای در بازپردازش جدید با خطا مواجه شود ولی از اجرای قبلی دارای متن معتبر باشد، متن معتبر قبلی حفظ می‌گردد.

---

## ۶. بررسی سلامت واقعی کارگر مستقل و اجرای Docker

- **گزارش واقعی وضعیت کارگر مستقل (`/health`)**:
  - در نسخهٔ قبلی، زمانی که کارگر داخلی وب‌سرویس غیرفعال بود (`SAHER_ENABLE_BACKGROUND_WORKER=false`) و کارگر در پردازش یا کانتینر مستقل (`python -m services.worker.runner`) اجرا می‌شد، اندپوینت `/health` صرفاً متغیر درون‌پردازشی `default_worker.is_running` را بررسی می‌کرد و وضعیت کارگر را به اشتباه آفلاین گزارش می‌داد.
  - در مایلستون ۳، متد `JobQueueRepository.get_online_worker_summary()` جدول `worker_registry` را با بررسی پنجرهٔ زمانی ضربان قلب (`worker_heartbeat_ttl_seconds = 45`) پایش می‌کند؛ بنابراین `/health` و `/api/v1/jobs` وضعیت واقعی کارگر مستقل را به‌درستی `worker_online: true` گزارش می‌کنند.
- **اجرای آفلاین با Docker (`Dockerfile` و `docker-compose.yml`)**:
  - سرویس `saher-api` (پورت `8000` با `SAHER_ENABLE_BACKGROUND_WORKER=false`) و سرویس مستقل `saher-worker` (`python -m services.worker.runner`) روی شبکهٔ داخلی `saher_offline_net` (`internal: true` — بدون دسترسی به اینترنت) با اشتراک حجم داده و پوشهٔ مدل‌های `data/models/tessdata` تعریف شده‌اند.
