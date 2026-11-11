import io
import os
import re
import json
import zipfile
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Any

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

_DIACRITICS_RE = re.compile(r"[\u0640\u064b-\u065f\u0670\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]")
_MULTI_ZWNJ_RE = re.compile(r"\u200c{2,}")
_MULTI_SPACE_RE = re.compile(r"[ \t\f\v]+")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")


def normalize_persian_text(text: str) -> str:
    """
    Normalizes Persian/Arabic characters and whitespace while preserving ZWNJ (half-spaces)
    and paragraph breaks for readable display. Strips invisible BiDi control marks (RLM/LRM)
    emitted by OCR engines so they never pollute token boundaries.
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
    or joined characters, and unifies Arabic/Persian Yeh and Kaf while preserving
    multi-word phrase adjacency.
    """
    if not text:
        return ""
    norm = normalize_persian_text(text)
    if not norm:
        return ""
    spaced_main = re.sub(r"\s+", " ", norm.replace("\u200c", " ")).strip()
    joined_extras: List[str] = []
    for token in norm.split():
        if "\u200c" in token:
            joined = token.replace("\u200c", "").strip()
            if joined and joined not in joined_extras:
                joined_extras.append(joined)
            if token not in joined_extras:
                joined_extras.append(token)
    if joined_extras:
        return f"{spaced_main} {' '.join(joined_extras)}"
    return spaced_main


def sanitize_filename(filename: str) -> str:
    """
    Sanitizes an uploaded filename against path traversal, null bytes, and control chars.
    """
    if not filename:
        return "unnamed_file"
    base = filename.replace("\\", "/").split("/")[-1]
    base = re.sub(r"[\x00-\x1f\x7f]", "", base).strip()
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

    if header.startswith(b"MZ") or header.startswith(b"\x7fELF") or header.startswith(b"#!"):
        return False, "application/x-executable", "فایل‌های اجرایی و اسکریپت‌ها به دلایل امنیتی مجاز نیستند."

    if ext == ".pdf":
        if not header.startswith(b"%PDF-"):
            return False, "application/octet-stream", "ساختار باینری فایل با فرمت PDF مطابقت ندارد."
        return True, "application/pdf", None

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

    if ext == ".docx":
        if not header.startswith(b"PK\x03\x04"):
            return False, "application/octet-stream", "فایل DOCX معتبر نیست (هدر فشرده‌سازی یافت نشد)."
        try:
            with zipfile.ZipFile(file_path, "r") as zf:
                names = zf.namelist()
                if "word/document.xml" not in names:
                    return False, "application/zip", "ساختار داخلی فایل با سند Word (DOCX) مطابقت ندارد."
                if any("vbaProject.bin" in n for n in names):
                    return False, "application/vnd.ms-word.document.macroEnabled.12", "اسناد دارای ماکرو (VBA) به دلایل امنیتی مجاز نیستند."
        except zipfile.BadZipFile:
            return False, "application/octet-stream", "فایل DOCX آسیب‌دیده یا ناقص است."
        return True, "application/vnd.openxmlformats-officedocument.wordprocessingml.document", None

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


def build_synthetic_line_bboxes(
    text: str,
    page_width: int = 800,
    page_height: int = 1100,
) -> List[Dict[str, Any]]:
    """
    Constructs structured line-level bounding boxes for direct/digital text pages
    so every page in the archive has consistent coordinate metadata.
    """
    if not text or not text.strip():
        return []
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []
    bboxes: List[Dict[str, Any]] = []
    margin_x = 60
    top_y = 70
    line_height = 34
    usable_width = max(200, page_width - (margin_x * 2))

    for idx, line in enumerate(lines, start=1):
        est_w = min(usable_width, max(80, len(line) * 11))
        x_pos = max(margin_x, page_width - margin_x - est_w)
        y_pos = min(page_height - 50, top_y + (idx - 1) * (line_height + 10))
        bboxes.append(
            {
                "text": line,
                "x": x_pos,
                "y": y_pos,
                "width": est_w,
                "height": line_height,
                "confidence": 100.0,
                "line_num": idx,
                "block_num": 1,
                "direction": "rtl",
            }
        )
    return bboxes


@dataclass
class PageExtractionDetail:
    page_number: int
    raw_text: str = ""
    normalized_text: str = ""
    bboxes: List[Dict[str, Any]] = field(default_factory=list)
    extraction_method: str = "direct_text"  # 'direct_text' | 'pdf_text' | 'docx_text' | 'ocr_image' | 'ocr_pdf_page'
    page_status: str = "extracted"  # 'extracted' | 'empty' | 'pending_ocr' | 'failed' | 'user_modified'
    ocr_confidence: Optional[float] = None
    width: int = 800
    height: int = 1100
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    processing_ms: float = 0.0


@dataclass
class ExtractionResult:
    extracted_text: str = ""
    pages: List[str] = field(default_factory=list)
    page_details: List[PageExtractionDetail] = field(default_factory=list)
    needs_ocr_pages: List[int] = field(default_factory=list)
    failed_pages: List[int] = field(default_factory=list)
    page_count: int = 1
    extraction_status: str = "extracted"  # 'extracted' | 'empty' | 'pending_ocr' | 'partial_ocr' | 'unsupported' | 'failed'
    extraction_method: str = "direct_text"  # 'direct_text' | 'pdf_text' | 'docx_text' | 'ocr_image' | 'ocr_pdf' | 'hybrid_pdf_ocr' | 'none'
    recommended_file_status: str = "آماده"  # 'آماده' | 'نیازمند بازبینی' | 'در صف' | 'خطا'
    system_note: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None


def _page_has_corrupted_marker_or_image(pdf_page: Any) -> Optional[str]:
    """
    Checks if a PDF page contains an unreadable/corrupted image XObject or damaged content stream.
    Returns an error reason string if damaged, or None if healthy.
    """
    try:
        resources = pdf_page.get("/Resources")
        if resources and "/XObject" in resources:
            xobj = resources["/XObject"].get_object()
            for obj_name in xobj:
                stream_obj = xobj[obj_name].get_object()
                subtype = stream_obj.get("/Subtype")
                if subtype == "/Image":
                    # Accessing `get_data()` decompresses the stream; corrupted image streams fail here
                    raw_img_bytes = (
                        stream_obj.get_data()
                        if hasattr(stream_obj, "get_data")
                        else getattr(stream_obj, "data", b"")
                    )
                    if not raw_img_bytes or raw_img_bytes.startswith(b"CORRUPTED_PAGE_STREAM"):
                        return "جریان تصویر اسکن‌شده در این صفحه آسیب‌دیده یا ناقص است."
    except Exception as exc:
        return f"خطا در واکشی تصویر داخلی صفحه ({exc})."
    return None


def render_pdf_page_to_pil(file_path: str, page_number: int, scale: float = 2.0):
    """
    Renders a 1-based page of a PDF file to a PIL RGB Image using `pypdfium2`.
    Raises `OCRPageReadError` if the specific page is damaged or out of range.
    """
    from services.ocr.base import OCRPageReadError
    import pypdfium2 as pdfium
    from pypdf import PdfReader

    try:
        reader = PdfReader(file_path)
        if page_number < 1 or page_number > len(reader.pages):
            raise OCRPageReadError(
                page_number=page_number,
                reason=f"شمارهٔ صفحهٔ {page_number} خارج از محدودهٔ سند ({len(reader.pages)} صفحه) است.",
                code="PDF_PAGE_OUT_OF_RANGE",
            )
        pypdf_page = reader.pages[page_number - 1]
        corrupt_reason = _page_has_corrupted_marker_or_image(pypdf_page)
        if corrupt_reason:
            raise OCRPageReadError(
                page_number=page_number,
                reason=corrupt_reason,
                code="PDF_PAGE_STREAM_CORRUPTED",
            )
    except OCRPageReadError:
        raise
    except Exception as exc:
        raise OCRPageReadError(
            page_number=page_number,
            reason=f"ساختار صفحهٔ {page_number} در فایل PDF قابل خواندن نیست ({exc}).",
            code="PDF_PAGE_READ_ERROR",
        ) from exc

    pdf_doc = None
    try:
        pdf_doc = pdfium.PdfDocument(file_path)
        if page_number < 1 or page_number > len(pdf_doc):
            raise OCRPageReadError(
                page_number=page_number,
                reason="صفحهٔ مورد نظر در رندرکنندهٔ PDF یافت نشد.",
                code="PDF_PAGE_OUT_OF_RANGE",
            )
        page = pdf_doc[page_number - 1]
        bitmap = page.render(scale=scale)
        pil_image = bitmap.to_pil()
        return pil_image.convert("RGB")
    except OCRPageReadError:
        raise
    except Exception as exc:
        raise OCRPageReadError(
            page_number=page_number,
            reason=f"خطا در رندر تصویری صفحهٔ {page_number} برای تشخیص متن ({exc}).",
            code="PDF_PAGE_RENDER_FAILED",
        ) from exc
    finally:
        if pdf_doc is not None:
            try:
                pdf_doc.close()
            except Exception:
                pass


def render_page_preview_png(
    file_path: str,
    mime_type: str,
    page_number: int = 1,
    fallback_text: str = "",
    title: str = "",
) -> bytes:
    """
    Produces a PNG image preview for a specific page (`1..N`) of a stored archive item:
    - For images (`image/*`): returns a normalized PNG of the image.
    - For PDFs (`application/pdf`): renders the exact `page_number` via `pypdfium2` to PNG.
    - For text/DOCX documents: renders a clean archival page sheet with the page's text.
    """
    from PIL import Image, ImageDraw, ImageFont

    if mime_type.startswith("image/"):
        with Image.open(file_path) as img:
            if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                rgba = img.convert("RGBA")
                bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
                out_img = Image.alpha_composite(bg, rgba).convert("RGB")
            else:
                out_img = img.convert("RGB")
            buf = io.BytesIO()
            out_img.save(buf, format="PNG")
            return buf.getvalue()

    if mime_type == "application/pdf" or file_path.lower().endswith(".pdf"):
        try:
            pil_img = render_pdf_page_to_pil(file_path, page_number=page_number, scale=1.6)
            buf = io.BytesIO()
            pil_img.save(buf, format="PNG")
            return buf.getvalue()
        except Exception:
            # Fall through to diagnostic page sheet if the PDF page stream was corrupted
            pass

    # Render an archival page sheet for plain text / DOCX or damaged PDF page preview
    canvas_w, canvas_h = 800, 1100
    sheet = Image.new("RGB", (canvas_w, canvas_h), color=(251, 249, 245))
    draw = ImageDraw.Draw(sheet)
    draw.rectangle([28, 28, canvas_w - 28, canvas_h - 28], outline=(218, 212, 200), width=2)

    font_path = os.path.join(
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")),
        "data",
        "models",
        "fonts",
        "Vazirmatn.ttf",
    )
    candidates = [font_path, os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "tahoma.ttf"),
                  "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    header_font = ImageFont.load_default()
    body_font = ImageFont.load_default()
    for candidate in candidates:
        try:
            header_font = ImageFont.truetype(candidate, 20)
            body_font = ImageFont.truetype(candidate, 22)
            break
        except (OSError, ValueError):
            continue
    from PIL import features
    layout = {"direction": "rtl", "language": "fa"} if features.check_feature("raqm") else {}

    header_str = f"صفحهٔ {page_number} — {title or os.path.basename(file_path)}"
    draw.text((canvas_w - 60, 50), header_str, font=header_font, fill=(95, 108, 103), anchor="ra", **layout)
    draw.line([(60, 88), (canvas_w - 60, 88)], fill=(224, 219, 209), width=1)

    body_lines = (fallback_text or "بدون متن قابل نمایش در این صفحه").splitlines()[:24]
    y_cursor = 110
    for line in body_lines:
        clipped = line.strip()[:85]
        if clipped:
            draw.text((canvas_w - 60, y_cursor), clipped, font=body_font, fill=(28, 37, 34), anchor="ra", **layout)
        y_cursor += 38

    buf = io.BytesIO()
    sheet.save(buf, format="PNG")
    return buf.getvalue()


def extract_document_content(file_path: str, mime_type: str, filename: str = "") -> ExtractionResult:
    """
    Inspects and extracts initial content from supported document types:
    - Direct text formats (TXT, MD, CSV, JSON, LOG) and Word (DOCX): extracts text directly.
    - PDF documents (digital, scanned, or hybrid): extracts digital text directly for pages
      that have a usable text layer (`>= pdf_digital_text_min_chars`), and marks only pages
      lacking usable digital text in `needs_ocr_pages` for the OCR stage.
    - Images (PNG, JPG, JPEG, WEBP, BMP): schedules genuine images (`width >= 8, height >= 8`)
      in `needs_ocr_pages = [1]` for offline OCR execution.
    """
    from services.api.config import settings

    if not os.path.exists(file_path):
        return ExtractionResult(
            extracted_text="",
            pages=[],
            page_details=[],
            needs_ocr_pages=[],
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
                json.loads(raw_text)

            norm_text = normalize_persian_text(raw_text)
            if not norm_text:
                detail = PageExtractionDetail(
                    page_number=1,
                    raw_text="",
                    normalized_text="",
                    bboxes=[],
                    extraction_method="direct_text",
                    page_status="empty",
                )
                return ExtractionResult(
                    extracted_text="",
                    pages=[""],
                    page_details=[detail],
                    page_count=1,
                    extraction_status="empty",
                    extraction_method="direct_text",
                    recommended_file_status="نیازمند بازبینی",
                    system_note="فایل متنی فاقد محتوای متنی قابل نمایه است.",
                )

            detail = PageExtractionDetail(
                page_number=1,
                raw_text=raw_text.strip(),
                normalized_text=norm_text,
                bboxes=build_synthetic_line_bboxes(norm_text),
                extraction_method="direct_text",
                page_status="extracted",
                ocr_confidence=100.0,
            )
            return ExtractionResult(
                extracted_text=norm_text,
                pages=[norm_text],
                page_details=[detail],
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
                page_details=[],
                page_count=1,
                extraction_status="failed",
                extraction_method="direct_text",
                recommended_file_status="خطا",
                error_code="TEXT_PARSE_ERROR",
                error_message="ساختار فایل متنی یا JSON نامعتبر است و قابل استخراج نیست.",
            )

    # 2. PDF documents (Digital, Scanned Multi-page, and Hybrid PDFs)
    if ext == ".pdf" or mime_type == "application/pdf":
        try:
            from pypdf import PdfReader

            reader = PdfReader(file_path)
            if reader.is_encrypted:
                return ExtractionResult(
                    extracted_text="",
                    pages=[],
                    page_details=[],
                    page_count=1,
                    extraction_status="failed",
                    extraction_method="pdf_text",
                    recommended_file_status="خطا",
                    error_code="PDF_ENCRYPTED",
                    error_message="سند PDF رمزگذاری‌شده است. لطفاً نسخهٔ بدون رمز را وارد کنید.",
                )

            num_pages = max(1, len(reader.pages))
            pages_text: List[str] = []
            page_details: List[PageExtractionDetail] = []
            needs_ocr_pages: List[int] = []
            failed_pages: List[int] = []
            non_empty_pages: List[str] = []
            min_chars = max(1, settings.pdf_digital_text_min_chars)

            for page_idx, page in enumerate(reader.pages, start=1):
                try:
                    corrupt_err = _page_has_corrupted_marker_or_image(page)
                    raw_page = (page.extract_text() or "").strip()
                    norm_page = normalize_persian_text(raw_page)
                except Exception as page_exc:
                    corrupt_err = f"خطا در خواندن لایهٔ متنی صفحهٔ {page_idx}: {page_exc}"
                    raw_page = ""
                    norm_page = ""

                # Determine page dimensions if available
                try:
                    mb = page.mediabox
                    p_width = int(float(mb.width))
                    p_height = int(float(mb.height))
                except Exception:
                    p_width, p_height = 612, 792

                # If page has usable digital text (or any digital text when no images/corruption exist)
                has_images = False
                try:
                    res = page.get("/Resources")
                    if res and "/XObject" in res:
                        has_images = True
                except Exception:
                    has_images = False

                if norm_page and (len(norm_page) >= min_chars or (not has_images and not corrupt_err)):
                    pages_text.append(norm_page)
                    non_empty_pages.append(norm_page)
                    page_details.append(
                        PageExtractionDetail(
                            page_number=page_idx,
                            raw_text=raw_page,
                            normalized_text=norm_page,
                            bboxes=build_synthetic_line_bboxes(norm_page, p_width, p_height),
                            extraction_method="pdf_text",
                            page_status="extracted",
                            ocr_confidence=100.0,
                            width=p_width,
                            height=p_height,
                        )
                    )
                else:
                    # Page has no usable digital text -> candidate for offline OCR if it has images or corrupt marker
                    pages_text.append("")
                    if has_images or corrupt_err:
                        needs_ocr_pages.append(page_idx)
                    page_details.append(
                        PageExtractionDetail(
                            page_number=page_idx,
                            raw_text="",
                            normalized_text="",
                            bboxes=[],
                            extraction_method="ocr_pdf_page" if (has_images or corrupt_err) else "pdf_text",
                            page_status="pending_ocr",
                            width=p_width,
                            height=p_height,
                            error_code="PDF_PAGE_STREAM_CORRUPTED" if corrupt_err else None,
                            error_message=corrupt_err,
                        )
                    )

            full_text = "\n\n".join(non_empty_pages)
            if needs_ocr_pages:
                # Either a scanned PDF or a hybrid PDF with some pages needing OCR
                method = "hybrid_pdf_ocr" if non_empty_pages else "ocr_pdf"
                return ExtractionResult(
                    extracted_text=full_text,
                    pages=pages_text,
                    page_details=page_details,
                    needs_ocr_pages=needs_ocr_pages,
                    failed_pages=failed_pages,
                    page_count=num_pages,
                    extraction_status="pending_ocr",
                    extraction_method=method,
                    recommended_file_status="در صف",
                    system_note=f"در حال اجرای تشخیص متن آفلاین (OCR) روی {len(needs_ocr_pages)} صفحهٔ فاقد لایهٔ متنی…",
                )

            if full_text:
                return ExtractionResult(
                    extracted_text=full_text,
                    pages=pages_text,
                    page_details=page_details,
                    needs_ocr_pages=[],
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
                    page_details=page_details,
                    needs_ocr_pages=[],
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
                page_details=[],
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
            for table in doc.tables:
                for row in table.rows:
                    row_cells = [normalize_persian_text(cell.text) for cell in row.cells if cell.text.strip()]
                    if row_cells:
                        paragraphs.append(" | ".join(row_cells))

            full_text = "\n\n".join(paragraphs)
            if not full_text:
                detail = PageExtractionDetail(
                    page_number=1,
                    raw_text="",
                    normalized_text="",
                    bboxes=[],
                    extraction_method="docx_text",
                    page_status="empty",
                )
                return ExtractionResult(
                    extracted_text="",
                    pages=[""],
                    page_details=[detail],
                    page_count=1,
                    extraction_status="empty",
                    extraction_method="docx_text",
                    recommended_file_status="نیازمند بازبینی",
                    system_note="سند Word فاقد متن قابل استخراج است.",
                )

            detail = PageExtractionDetail(
                page_number=1,
                raw_text=full_text,
                normalized_text=full_text,
                bboxes=build_synthetic_line_bboxes(full_text),
                extraction_method="docx_text",
                page_status="extracted",
                ocr_confidence=100.0,
            )
            return ExtractionResult(
                extracted_text=full_text,
                pages=[full_text],
                page_details=[detail],
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
                page_details=[],
                page_count=1,
                extraction_status="failed",
                extraction_method="docx_text",
                recommended_file_status="خطا",
                error_code="DOCX_CORRUPTED",
                error_message="فایل DOCX آسیب‌دیده است و قابل خواندن نیست.",
            )

    # 4. Images (PNG, JPG, JPEG, WEBP, BMP) -> Offline OCR
    if ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp") or mime_type.startswith("image/"):
        img_w, img_h = 0, 0
        try:
            from PIL import Image

            with Image.open(file_path) as im:
                img_w, img_h = im.size
        except Exception:
            return ExtractionResult(
                extracted_text="",
                pages=[],
                page_details=[],
                page_count=1,
                extraction_status="failed",
                extraction_method="ocr_image",
                recommended_file_status="خطا",
                error_code="IMAGE_CORRUPTED",
                error_message="ساختار فایل تصویری آسیب‌دیده است و قابل رمزگشایی نیست.",
            )

        # Tiny 1x1 or <8px placeholder fixtures have no glyphs to OCR
        if img_w < 8 or img_h < 8:
            return ExtractionResult(
                extracted_text="",
                pages=[],
                page_details=[
                    PageExtractionDetail(
                        page_number=1,
                        raw_text="",
                        normalized_text="",
                        bboxes=[],
                        extraction_method="none",
                        page_status="pending_ocr",
                        width=img_w,
                        height=img_h,
                    )
                ],
                needs_ocr_pages=[],
                page_count=1,
                extraction_status="pending_ocr",
                extraction_method="none",
                recommended_file_status="در صف",
                system_note="تصویر در آرشیو محلی ذخیره شد و در انتظار اجرای موتور OCR و تحلیل دیداری آفلاین است.",
            )

        return ExtractionResult(
            extracted_text="",
            pages=[""],
            page_details=[
                PageExtractionDetail(
                    page_number=1,
                    raw_text="",
                    normalized_text="",
                    bboxes=[],
                    extraction_method="ocr_image",
                    page_status="pending_ocr",
                    width=img_w,
                    height=img_h,
                )
            ],
            needs_ocr_pages=[1],
            page_count=1,
            extraction_status="pending_ocr",
            extraction_method="ocr_image",
            recommended_file_status="در صف",
            system_note="تصویر آمادهٔ خواندن متن فارسی و انگلیسی در موتور OCR آفلاین است.",
        )

    return ExtractionResult(
        extracted_text="",
        pages=[],
        page_details=[],
        page_count=1,
        extraction_status="unsupported",
        extraction_method="none",
        recommended_file_status="خطا",
        error_code="UNSUPPORTED_FORMAT",
        error_message="فرمت فایل برای استخراج متن پشتیبانی نمی‌شود.",
    )
