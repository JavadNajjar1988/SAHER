import os
import re
import json
import zipfile
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# Arabic to Persian character unification map
_CHAR_TRANSLATION = str.maketrans({
    "\u064a": "\u06cc",  # ي -> ی
    "\u0649": "\u06cc",  # ى -> ی
    "\u0643": "\u06a9",  # ك -> ک
    "\u0629": "\u0647",  # ة -> ه
    "\u0624": "\u0648",  # ؤ -> و
    "\u0623": "\u0627",  # أ -> ا
    "\u0625": "\u0627",  # إ -> ا
    "\u06f0": "0",
    "\u06f1": "1",
    "\u06f2": "2",
    "\u06f3": "3",
    "\u06f4": "4",
    "\u06f5": "5",
    "\u06f6": "6",
    "\u06f7": "7",
    "\u06f8": "8",
    "\u06f9": "9",
    "\u0660": "0",
    "\u0661": "1",
    "\u0662": "2",
    "\u0663": "3",
    "\u0664": "4",
    "\u0665": "5",
    "\u0666": "6",
    "\u0667": "7",
    "\u0668": "8",
    "\u0669": "9",
})

_DIACRITICS_RE = re.compile(r"[\u0640\u064b-\u065f\u0670]")
_MULTI_ZWNJ_RE = re.compile(r"\u200c{2,}")
_MULTI_SPACE_RE = re.compile(r"[ \t\f\v]+")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")


def normalize_persian_text(text: str) -> str:
    """
    Normalizes Persian/Arabic characters and whitespace while preserving ZWNJ (half-spaces)
    and paragraph breaks for readable display.
    """
    if not text:
        return ""
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = cleaned.translate(_CHAR_TRANSLATION)
    cleaned = _DIACRITICS_RE.sub("", cleaned)
    cleaned = _MULTI_ZWNJ_RE.sub("\u200c", cleaned)
    cleaned = _MULTI_SPACE_RE.sub(" ", cleaned)
    cleaned = _MULTI_NEWLINE_RE.sub("\n\n", cleaned)
    return cleaned.strip()


def normalize_for_fts(text: str) -> str:
    """
    Produces a normalized string for SQLite FTS5 indexing that supports matching
    Persian words regardless of whether the user types a half-space (ZWNJ), a regular space,
    or joined characters.
    """
    if not text:
        return ""
    norm = normalize_persian_text(text)
    if not norm:
        return ""
    # Expand tokens containing ZWNJ so both space-separated and joined forms are indexed
    expanded_tokens: List[str] = []
    for token in norm.split():
        if "\u200c" in token:
            spaced = token.replace("\u200c", " ").strip()
            joined = token.replace("\u200c", "").strip()
            if spaced:
                expanded_tokens.append(spaced)
            if joined and joined != spaced:
                expanded_tokens.append(joined)
        else:
            expanded_tokens.append(token)
    return " ".join(expanded_tokens)


def sanitize_filename(filename: str) -> str:
    """
    Sanitizes an uploaded filename against path traversal, null bytes, and control chars.
    """
    if not filename:
        return "unnamed_file"
    # Strip any directory components (both POSIX and Windows separators)
    base = filename.replace("\\", "/").split("/")[-1]
    # Remove null bytes and control characters
    base = re.sub(r"[\x00-\x1f\x7f]", "", base).strip()
    # Prevent hidden files or parent traversal
    base = base.lstrip(".")
    if not base or base in (".", ".."):
        return "unnamed_file"
    return base[:200]


def validate_file_signature(file_path: str, filename: str) -> Tuple[bool, str, Optional[str]]:
    """
    Inspects file header bytes and structure to detect actual MIME type,
    prevent spoofed extensions, and reject active/executable content (HTML, scripts, binaries).
    Returns: (is_valid, detected_mime_type, error_message)
    """
    if not os.path.exists(file_path):
        return False, "application/octet-stream", "فایل در مسیر موقت یافت نشد."

    file_size = os.path.getsize(file_path)
    if file_size == 0:
        return False, "application/octet-stream", "فایل انتخاب‌شده خالی (۰ بایت) است."

    ext = os.path.splitext(filename)[1].lower()
    with open(file_path, "rb") as f:
        header = f.read(8192)

    # Block executable binaries regardless of extension
    if header.startswith(b"MZ") or header.startswith(b"\x7fELF") or header.startswith(b"#!"):
        return False, "application/x-executable", "فایل‌های اجرایی و اسکریپت‌ها به دلایل امنیتی مجاز نیستند."

    # 1. PDF validation
    if ext == ".pdf":
        if not header.startswith(b"%PDF-"):
            return False, "application/octet-stream", "ساختار باینری فایل با فرمت PDF مطابقت ندارد."
        return True, "application/pdf", None

    # 2. Image validations
    if ext == ".png":
        if not header.startswith(b"\x89PNG\r\n\x1a\n"):
            return False, "application/octet-stream", "امضای باینری فایل با تصویر PNG معتبر مطابقت ندارد."
        return True, "image/png", None

    if ext in (".jpg", ".jpeg"):
        if not header.startswith(b"\xff\xd8\xff"):
            return False, "application/octet-stream", "امضای باینری فایل با تصویر JPEG معتبر مطابقت ندارد."
        return True, "image/jpeg", None

    if ext == ".webp":
        if not (len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP"):
            return False, "application/octet-stream", "امضای باینری فایل با تصویر WebP معتبر مطابقت ندارد."
        return True, "image/webp", None

    if ext == ".bmp":
        if not header.startswith(b"BM"):
            return False, "application/octet-stream", "امضای باینری فایل با تصویر BMP معتبر مطابقت ندارد."
        return True, "image/bmp", None

    # 3. DOCX validation
    if ext == ".docx":
        if not header.startswith(b"PK\x03\x04"):
            return False, "application/octet-stream", "فایل DOCX معتبر نیست (هدر فشرده‌سازی یافت نشد)."
        try:
            with zipfile.ZipFile(file_path, "r") as zf:
                names = zf.namelist()
                if "word/document.xml" not in names:
                    return False, "application/zip", "ساختار داخلی فایل با سند Word (DOCX) مطابقت ندارد."
                # Reject macro-enabled documents disguised as .docx
                if any("vbaProject.bin" in n for n in names):
                    return False, "application/vnd.ms-word.document.macroEnabled.12", "اسناد دارای ماکرو (VBA) به دلایل امنیتی مجاز نیستند."
        except zipfile.BadZipFile:
            return False, "application/octet-stream", "فایل DOCX آسیب‌دیده یا ناقص است."
        return True, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", None

    # 4. Plain text / structured text formats
    if ext in (".txt", ".md", ".csv", ".json", ".log"):
        if b"\x00" in header:
            return False, "application/octet-stream", "فایل متنی حاوی بایت‌های باینری نامعتبر است."
        lower_head = header[:1024].decode("utf-8", errors="ignore").lstrip().lower()
        if lower_head.startswith("<!doctype html") or lower_head.startswith("<html") or "<script" in lower_head:
            return False, "text/html", "واردسازی فایل‌های HTML یا حاوی اسکریپت مجاز نیست."
        mime_map = {
            ".txt": "text/plain",
            ".md": "text/markdown",
            ".csv": "text/csv",
            ".json": "application/json",
            ".log": "text/plain",
        }
        return True, mime_map.get(ext, "text/plain"), None

    return False, "application/octet-stream", f"فرمت فایل «{ext or 'نامشخص'}» در فهرست فرمت‌های مجاز ساهر قرار ندارد."


@dataclass
class ExtractionResult:
    extracted_text: str = ""
    pages: List[str] = field(default_factory=list)
    page_count: int = 1
    extraction_status: str = "extracted"  # 'extracted' | 'empty' | 'pending_ocr' | 'unsupported' | 'failed'
    extraction_method: str = "direct_text"  # 'direct_text' | 'pdf_text' | 'docx_text' | 'none'
    recommended_file_status: str = "آماده"  # 'آماده' | 'نیازمند بازبینی' | 'در صف' | 'خطا'
    system_note: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None


def extract_document_content(file_path: str, mime_type: str, filename: str = "") -> ExtractionResult:
    """
    Extracts genuine text from supported document types (TXT, MD, CSV, JSON, PDF, DOCX).
    System notes and error details are strictly separated from `extracted_text` so they never
    pollute FTS5 search results or impersonate document content.
    """
    if not os.path.exists(file_path):
        return ExtractionResult(
            extracted_text="",
            pages=[],
            page_count=0,
            extraction_status="failed",
            extraction_method="none",
            recommended_file_status="خطا",
            error_code="FILE_NOT_FOUND",
            error_message="فایل منبع برای استخراج متن در دسترس نیست.",
        )

    ext = os.path.splitext(filename or file_path)[1].lower()

    # 1. Text formats
    if ext in (".txt", ".md", ".csv", ".json", ".log"):
        try:
            with open(file_path, "rb") as f:
                raw_bytes = f.read()
            try:
                raw_text = raw_bytes.decode("utf-8")
            except UnicodeDecodeError:
                raw_text = raw_bytes.decode("utf-8", errors="replace")

            if ext == ".json":
                # Validate JSON integrity
                json.loads(raw_text)

            norm_text = normalize_persian_text(raw_text)
            if not norm_text:
                return ExtractionResult(
                    extracted_text="",
                    pages=[""],
                    page_count=1,
                    extraction_status="empty",
                    extraction_method="direct_text",
                    recommended_file_status="نیازمند بازبینی",
                    system_note="فایل متنی فاقد محتوای متنی قابل نمایه است.",
                )
            return ExtractionResult(
                extracted_text=norm_text,
                pages=[norm_text],
                page_count=1,
                extraction_status="extracted",
                extraction_method="direct_text",
                recommended_file_status="آماده",
                system_note=None,
            )
        except Exception:
            return ExtractionResult(
                extracted_text="",
                pages=[],
                page_count=1,
                extraction_status="failed",
                extraction_method="direct_text",
                recommended_file_status="خطا",
                error_code="TEXT_PARSE_ERROR",
                error_message="ساختار فایل متنی یا JSON نامعتبر است و قابل استخراج نیست.",
            )

    # 2. PDF documents
    if ext == ".pdf" or mime_type == "application/pdf":
        try:
            from pypdf import PdfReader

            reader = PdfReader(file_path)
            if reader.is_encrypted:
                return ExtractionResult(
                    extracted_text="",
                    pages=[],
                    page_count=1,
                    extraction_status="failed",
                    extraction_method="pdf_text",
                    recommended_file_status="خطا",
                    error_code="PDF_ENCRYPTED",
                    error_message="سند PDF رمزگذاری‌شده است. لطفاً نسخهٔ بدون رمز را وارد کنید.",
                )

            num_pages = max(1, len(reader.pages))
            pages_text: List[str] = []
            non_empty_pages: List[str] = []

            for page in reader.pages:
                raw_page = page.extract_text() or ""
                norm_page = normalize_persian_text(raw_page)
                pages_text.append(norm_page)
                if norm_page:
                    non_empty_pages.append(norm_page)

            full_text = "\n\n".join(non_empty_pages)
            if full_text:
                return ExtractionResult(
                    extracted_text=full_text,
                    pages=pages_text,
                    page_count=num_pages,
                    extraction_status="extracted",
                    extraction_method="pdf_text",
                    recommended_file_status="آماده",
                    system_note=None,
                )
            else:
                return ExtractionResult(
                    extracted_text="",
                    pages=pages_text,
                    page_count=num_pages,
                    extraction_status="pending_ocr",
                    extraction_method="pdf_text",
                    recommended_file_status="نیازمند بازبینی",
                    system_note="این سند PDF فاقد لایهٔ متنی دیجیتال است (اسکن‌شده) و نیازمند پردازش OCR آفلاین است.",
                )
        except Exception:
            return ExtractionResult(
                extracted_text="",
                pages=[],
                page_count=1,
                extraction_status="failed",
                extraction_method="pdf_text",
                recommended_file_status="خطا",
                error_code="PDF_CORRUPTED",
                error_message="ساختار فایل PDF آسیب‌دیده است و امکان استخراج متن وجود ندارد.",
            )

    # 3. Word DOCX documents
    if ext == ".docx" or mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        try:
            import docx

            doc = docx.Document(file_path)
            paragraphs = [
                normalize_persian_text(p.text)
                for p in doc.paragraphs
                if p.text and normalize_persian_text(p.text)
            ]
            # Also extract table cells if present
            for table in doc.tables:
                for row in table.rows:
                    row_cells = [normalize_persian_text(cell.text) for cell in row.cells if cell.text.strip()]
                    if row_cells:
                        paragraphs.append(" | ".join(row_cells))

            full_text = "\n\n".join(paragraphs)
            if not full_text:
                return ExtractionResult(
                    extracted_text="",
                    pages=[""],
                    page_count=1,
                    extraction_status="empty",
                    extraction_method="docx_text",
                    recommended_file_status="نیازمند بازبینی",
                    system_note="سند Word فاقد متن قابل استخراج است.",
                )
            return ExtractionResult(
                extracted_text=full_text,
                pages=[full_text],
                page_count=1,
                extraction_status="extracted",
                extraction_method="docx_text",
                recommended_file_status="آماده",
                system_note=None,
            )
        except Exception:
            return ExtractionResult(
                extracted_text="",
                pages=[],
                page_count=1,
                extraction_status="failed",
                extraction_method="docx_text",
                recommended_file_status="خطا",
                error_code="DOCX_CORRUPTED",
                error_message="فایل DOCX آسیب‌دیده است و قابل خواندن نیست.",
            )

    # 4. Images (awaiting OCR / Vision model in future milestone)
    if ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp") or mime_type.startswith("image/"):
        return ExtractionResult(
            extracted_text="",
            pages=[],
            page_count=1,
            extraction_status="pending_ocr",
            extraction_method="none",
            recommended_file_status="در صف",
            system_note="تصویر در آرشیو محلی ذخیره شد و در انتظار اجرای موتور OCR و تحلیل دیداری آفلاین است.",
        )

    return ExtractionResult(
        extracted_text="",
        pages=[],
        page_count=1,
        extraction_status="unsupported",
        extraction_method="none",
        recommended_file_status="خطا",
        error_code="UNSUPPORTED_FORMAT",
        error_message="فرمت فایل برای استخراج متن پشتیبانی نمی‌شود.",
    )
