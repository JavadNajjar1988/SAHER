from typing import Any, Dict, List, Optional
from services.api.config import settings
from services.ocr.base import (
    OCREngineAdapter,
    OCREngineStatus,
    OCRPageResult,
    OCRBoundingBox,
    OCREngineError,
    OCRModelMissingError,
    OCRPageReadError,
)
from services.ocr.tesseract_engine import TesseractOCREngine
from services.ocr.paddle_engine import (
    PaddleOCREngine,
    PaddleOCRDictionaryBundle,
    get_paddleocr_dict_bundle,
    get_paddleocr_repo_metadata,
    resolve_paddleocr_repo_dir,
)

_active_engine: Optional[OCREngineAdapter] = None

AVAILABLE_OCR_ENGINES: List[str] = ["paddleocr", "hybrid", "tesseract"]


def get_ocr_engine_by_name(engine_name: Optional[str] = None) -> OCREngineAdapter:
    """
    Returns an OCR engine instance for the requested `engine_name`:
    - `paddleocr`: `PaddleOCREngine(hybrid_mode=False)` (backed by `vendor/PaddleOCR`)
    - `hybrid`: `PaddleOCREngine(hybrid_mode=True)` (`PaddleOCR + Tesseract 5 LSTM`)
    - `tesseract`: `TesseractOCREngine()`
    """
    norm_name = (engine_name or "").strip().lower()
    if norm_name in ("paddleocr", "paddle", "ppocr", "pp-ocr"):
        return PaddleOCREngine(hybrid_mode=False)
    if norm_name in ("hybrid", "paddleocr+tesseract", "ensemble"):
        return PaddleOCREngine(hybrid_mode=True)
    if norm_name in ("tesseract", "tess"):
        return TesseractOCREngine()
    return get_ocr_engine()


def get_ocr_engine() -> OCREngineAdapter:
    """
    Returns the configured pluggable OCR engine adapter.
    Supports `tesseract`, `paddleocr` (`PaddlePaddle/PaddleOCR`), and `hybrid`.
    """
    global _active_engine
    if _active_engine is not None:
        return _active_engine
    cfg = (settings.ocr_engine or "tesseract").strip().lower()
    if cfg in ("paddleocr", "paddle", "ppocr", "pp-ocr"):
        return PaddleOCREngine(hybrid_mode=False)
    if cfg in ("hybrid", "paddleocr+tesseract", "ensemble"):
        return PaddleOCREngine(hybrid_mode=True)
    return TesseractOCREngine()


def set_ocr_engine(engine: Optional[OCREngineAdapter]) -> None:
    """
    Allows swapping the OCR engine implementation at runtime or in tests.
    Pass `None` to reset to the default configured engine.
    """
    global _active_engine
    _active_engine = engine


def set_ocr_engine_by_name(engine_name: str) -> OCREngineAdapter:
    """
    Updates `settings.ocr_engine` and `_active_engine` to the requested engine
    (`paddleocr`, `hybrid`, or `tesseract`) and returns the active adapter.
    """
    global _active_engine
    norm = (engine_name or "paddleocr").strip().lower()
    if norm in ("paddleocr", "paddle", "ppocr", "pp-ocr"):
        settings.ocr_engine = "paddleocr"
        _active_engine = PaddleOCREngine(hybrid_mode=False)
    elif norm in ("hybrid", "paddleocr+tesseract", "ensemble"):
        settings.ocr_engine = "hybrid"
        _active_engine = PaddleOCREngine(hybrid_mode=True)
    else:
        settings.ocr_engine = "tesseract"
        _active_engine = TesseractOCREngine()
    return _active_engine


def list_available_ocr_engines() -> List[Dict[str, Any]]:
    meta = get_paddleocr_repo_metadata()
    return [
        {
            "id": "paddleocr",
            "title": "PaddleOCR (PP-OCRv4/v5 · مخزن PaddlePaddle/PaddleOCR)",
            "description": "پیش‌پردازش هوشمند اسکرین‌شات (تشخیص حالت تیره و بزرگ‌نمایی)، استخراج چندزبانه و پالایش با واژه‌نامهٔ رسمی fa_dict.txt و ppocrv5_arabic_dict.txt",
            "ready": bool(meta.get("repo_present")),
        },
        {
            "id": "hybrid",
            "title": "ترکیبی هوشمند (PaddleOCR + Tesseract 5 LSTM)",
            "description": "اجرای چندمرحله‌ای PP-OCR به همراه موتور LSTM و انتخاب بالاترین امتیاز اطمینان برای اسکرین‌شات‌های شبکهٔ اجتماعی و اسناد اسکن‌شده",
            "ready": True,
        },
        {
            "id": "tesseract",
            "title": "Tesseract 5 LSTM (موتور پایهٔ آفلاین)",
            "description": "موتور استاندارد تشخیص متن فارسی و انگلیسی (fas+eng) بدون پیش‌پردازش چندمرحله‌ای PP-OCR",
            "ready": True,
        },
    ]


__all__ = [
    "AVAILABLE_OCR_ENGINES",
    "OCREngineAdapter",
    "OCREngineStatus",
    "OCRPageResult",
    "OCRBoundingBox",
    "OCREngineError",
    "OCRModelMissingError",
    "OCRPageReadError",
    "TesseractOCREngine",
    "PaddleOCREngine",
    "PaddleOCRDictionaryBundle",
    "get_paddleocr_dict_bundle",
    "get_paddleocr_repo_metadata",
    "resolve_paddleocr_repo_dir",
    "get_ocr_engine",
    "get_ocr_engine_by_name",
    "set_ocr_engine",
    "set_ocr_engine_by_name",
    "list_available_ocr_engines",
]
