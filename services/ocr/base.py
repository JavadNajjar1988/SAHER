from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Any, Dict


class OCREngineError(Exception):
    def __init__(self, message: str, code: str = "OCR_ENGINE_ERROR"):
        super().__init__(message)
        self.message = message
        self.code = code


class OCRModelMissingError(OCREngineError):
    """
    Raised when the offline OCR binary or required language model files
    (e.g., fas.traineddata, eng.traineddata) are missing on disk.
    """

    def __init__(
        self,
        missing_items: List[str],
        model_dir: str,
        engine_name: str = "tesseract",
    ):
        missing_str = "، ".join(missing_items)
        msg = (
            f"بستهٔ مدل تشخیص متن آفلاین ({engine_name}) ناقص است یا یافت نشد: «{missing_str}». "
            f"لطفاً فایل‌های مدل (fas.traineddata و eng.traineddata) را در مسیر «{model_dir}» قرار دهید "
            f"یا بستهٔ tesseract-ocr-fas و tesseract-ocr-eng را نصب کنید."
        )
        super().__init__(msg, code="OCR_MODEL_MISSING")
        self.missing_items = missing_items
        self.model_dir = model_dir
        self.engine_name = engine_name


class OCRPageReadError(OCREngineError):
    """
    Raised when reading or recognizing a specific page fails.
    Includes the 1-based page number so other healthy pages are preserved.
    """

    def __init__(self, page_number: int, reason: str, code: str = "OCR_PAGE_READ_ERROR"):
        msg = f"خطا در خواندن متن صفحهٔ {page_number}: {reason}"
        super().__init__(msg, code=code)
        self.page_number = page_number
        self.reason = reason


@dataclass
class OCRBoundingBox:
    text: str
    x: int
    y: int
    width: int
    height: int
    confidence: float = 100.0
    line_num: int = 1
    block_num: int = 1
    direction: str = "rtl"  # 'rtl' | 'ltr'

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class OCRPageResult:
    page_number: int
    raw_text: str = ""
    normalized_text: str = ""
    bboxes: List[OCRBoundingBox] = field(default_factory=list)
    confidence: float = 0.0
    width: int = 0
    height: int = 0
    engine_name: str = "tesseract"
    engine_version: str = ""
    processing_ms: float = 0.0
    extraction_method: str = "ocr_image"  # 'ocr_image' | 'ocr_pdf_page' | 'pdf_text' | 'direct_text'
    status: str = "extracted"  # 'extracted' | 'empty' | 'failed'
    error_code: Optional[str] = None
    error_message: Optional[str] = None


@dataclass
class OCREngineStatus:
    ready: bool
    engine_name: str
    engine_version: str
    model_dir: str
    installed_languages: List[str] = field(default_factory=list)
    required_languages: List[str] = field(default_factory=lambda: ["fas", "eng"])
    missing_languages: List[str] = field(default_factory=list)
    offline_ready: bool = False
    error_code: Optional[str] = None
    error_message: Optional[str] = None


class OCREngineAdapter(ABC):
    """
    Pluggable interface for offline Persian + English text recognition engines.
    Implementations must operate completely offline once the local model bundle is present.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Identifier of the OCR engine implementation."""

    @abstractmethod
    def inspect_status(self) -> OCREngineStatus:
        """
        Inspects engine binary and offline model bundle availability without network calls.
        """

    @abstractmethod
    def ensure_ready(self) -> OCREngineStatus:
        """
        Verifies that the engine and required offline language models (fas, eng) are present.
        Raises `OCRModelMissingError` if any required model file or binary is missing.
        """

    @abstractmethod
    def recognize_image(
        self,
        image_source: Any,
        page_number: int = 1,
        languages: Optional[str] = None,
        extraction_method: str = "ocr_image",
    ) -> OCRPageResult:
        """
        Executes offline text recognition on a PIL Image or image file path,
        returning raw text, normalized Persian/English text, bounding boxes, and confidence.
        """
