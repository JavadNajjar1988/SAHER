from typing import Optional
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

_active_engine: Optional[OCREngineAdapter] = None


def get_ocr_engine() -> OCREngineAdapter:
    """
    Returns the configured pluggable OCR engine adapter.
    Defaults to `TesseractOCREngine` reading models from `settings.ocr_model_dir`.
    """
    global _active_engine
    if _active_engine is not None:
        return _active_engine
    return TesseractOCREngine()


def set_ocr_engine(engine: Optional[OCREngineAdapter]) -> None:
    """
    Allows swapping the OCR engine implementation at runtime or in tests.
    Pass `None` to reset to the default configured engine.
    """
    global _active_engine
    _active_engine = engine


__all__ = [
    "OCREngineAdapter",
    "OCREngineStatus",
    "OCRPageResult",
    "OCRBoundingBox",
    "OCREngineError",
    "OCRModelMissingError",
    "OCRPageReadError",
    "TesseractOCREngine",
    "get_ocr_engine",
    "set_ocr_engine",
]
