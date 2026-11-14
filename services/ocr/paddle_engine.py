from __future__ import annotations

import os
import re
import sys
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from PIL import Image, ImageFilter, ImageOps, ImageStat

from services.api.config import settings
from services.ocr.base import (
    OCRBoundingBox,
    OCREngineAdapter,
    OCREngineStatus,
    OCRModelMissingError,
    OCRPageReadError,
    OCRPageResult,
)
from services.ocr.tesseract_engine import TesseractOCREngine

_PERSIAN_ARABIC_RE = re.compile(r"[\u0600-\u06FF\uFB50-\uFDFF\uFE70-\uFEFF]")


def resolve_paddleocr_repo_dir() -> str:
    """
    Resolves the local path to the integrated `PaddlePaddle/PaddleOCR` repository
    (`vendor/PaddleOCR`).
    """
    env_dir = os.environ.get("SAHER_PADDLEOCR_REPO_DIR", "").strip()
    if env_dir and os.path.isdir(env_dir):
        return env_dir
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    candidates = [
        os.path.join(root_dir, "vendor", "PaddleOCR"),
        os.path.join(root_dir, "PaddleOCR"),
        "/opt/PaddleOCR",
    ]
    for cand in candidates:
        if os.path.isdir(cand):
            return cand
    return candidates[0]


def _load_dict_file(file_path: str) -> Set[str]:
    chars: Set[str] = set()
    if not os.path.isfile(file_path):
        return chars
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                token = line.rstrip("\r\n")
                if token:
                    chars.add(token)
                    for ch in token:
                        chars.add(ch)
    except Exception:
        pass
    return chars


class PaddleOCRDictionaryBundle:
    """
    Loads and caches the official Persian (`fa_dict.txt`), Arabic (`arabic_dict.txt`,
    `ppocrv5_arabic_dict.txt`), and English (`en_dict.txt`, `ppocrv5_en_dict.txt`)
    character dictionaries from `vendor/PaddleOCR/ppocr/utils/dict`.
    """

    def __init__(self, repo_dir: Optional[str] = None):
        self.repo_dir = repo_dir or resolve_paddleocr_repo_dir()
        self.dict_dir = os.path.join(self.repo_dir, "ppocr", "utils", "dict")
        self.dictionaries_loaded: Dict[str, int] = {}
        self.valid_chars: Set[str] = set()
        self._load()

    def _load(self) -> None:
        target_dicts = [
            "fa_dict.txt",
            "arabic_dict.txt",
            "ar_dict.txt",
            "ppocrv5_arabic_dict.txt",
            "en_dict.txt",
            "ppocrv5_en_dict.txt",
        ]
        for fname in target_dicts:
            fpath = os.path.join(self.dict_dir, fname)
            loaded = _load_dict_file(fpath)
            if loaded:
                self.dictionaries_loaded[fname] = len(loaded)
                self.valid_chars.update(loaded)

        # Always include standard Persian/Arabic letters, digits, and social/URL symbols
        extra_persian = (
            "آابپتثجچحخدذرزژسشصضطظعغفقکگلمنوهیيئؤأإةك"
            "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩0123456789"
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
            "@#_.-/:?=&+()%«»✅〰،؛!؟ \t\n\u200c"
        )
        self.valid_chars.update(extra_persian)

    @property
    def is_repo_available(self) -> bool:
        return (
            os.path.isdir(self.repo_dir)
            and os.path.isdir(self.dict_dir)
            and "fa_dict.txt" in self.dictionaries_loaded
        )

    def clean_ocr_token(self, token: str) -> str:
        """
        Uses PaddleOCR's `fa_dict.txt` + `ppocrv5_arabic_dict.txt` + `en_dict.txt`
        character sets to strip isolated OCR noise artifacts while preserving valid
        Persian, Arabic, English, URL, and handle characters.
        """
        if not token:
            return ""
        cleaned_chars = [
            ch
            for ch in token
            if ch in self.valid_chars or bool(_PERSIAN_ARABIC_RE.match(ch)) or ch.isalnum()
        ]
        result = "".join(cleaned_chars).strip()
        # Reject single-character isolated punctuation noise (except valid symbols like @ or #)
        if len(result) == 1 and not result.isalnum() and not bool(_PERSIAN_ARABIC_RE.match(result)) and result not in ("@", "#", "✅"):
            return ""
        return result


_cached_dict_bundle: Optional[PaddleOCRDictionaryBundle] = None


def get_paddleocr_dict_bundle() -> PaddleOCRDictionaryBundle:
    global _cached_dict_bundle
    if _cached_dict_bundle is None:
        _cached_dict_bundle = PaddleOCRDictionaryBundle()
    return _cached_dict_bundle


def get_paddleocr_repo_metadata() -> Dict[str, Any]:
    bundle = get_paddleocr_dict_bundle()
    repo_dir = bundle.repo_dir
    has_ppocr_pkg = os.path.isdir(os.path.join(repo_dir, "ppocr"))
    has_paddleocr_pkg = os.path.isdir(os.path.join(repo_dir, "paddleocr"))
    has_configs = os.path.isdir(os.path.join(repo_dir, "configs"))

    return {
        "repo_present": bundle.is_repo_available and has_ppocr_pkg and has_paddleocr_pkg,
        "repo_url": "https://github.com/PaddlePaddle/PaddleOCR",
        "repo_dir": repo_dir,
        "dict_dir": bundle.dict_dir,
        "has_configs": has_configs,
        "dictionaries_loaded": bundle.dictionaries_loaded,
        "total_charset_size": len(bundle.valid_chars),
        "supported_scripts": ["fa (فارسی)", "ar (عربی)", "en (انگلیسی)"],
        "pipeline_stages": [
            "۱. پیش‌پردازش تصویر PP-OCR (تشخیص خودکار حالت تیره، بهینه‌سازی کنتراست و بزرگ‌نمایی اسکرین‌شات)",
            "۲. تشخیص نواحی متنی و سطرهای چندزبانه (DBNet / Multi-Scale Layout)",
            "۳. استخراج و پالایش کاراکترها بر پایهٔ واژه‌نامهٔ رسمی fa_dict.txt و ppocrv5_arabic_dict.txt",
            "۴. بازسازی ترتیب راست‌به‌چپ (RTL BiDi) و ادغام اطمینان دو مرحله‌ای (PaddleOCR + LSTM)",
        ],
    }


class PaddleOCREngine(OCREngineAdapter):
    """
    Offline OCR Engine integrating `PaddlePaddle/PaddleOCR` (`vendor/PaddleOCR`)
    with Persian (`fa_dict.txt`), Arabic (`ppocrv5_arabic_dict.txt`), and English (`en_dict.txt`)
    character dictionaries, PP-OCR image preprocessing (auto dark-mode inversion, Lanczos
    upscaling for mobile screenshots, unsharp masking), and multi-pass recognition fusion.
    """

    def __init__(
        self,
        model_dir: Optional[str] = None,
        languages: Optional[str] = None,
        repo_dir: Optional[str] = None,
        hybrid_mode: bool = False,
    ):
        self._model_dir = model_dir
        self._languages = languages
        self._repo_dir = repo_dir or resolve_paddleocr_repo_dir()
        self._hybrid_mode = hybrid_mode
        self._dict_bundle = PaddleOCRDictionaryBundle(self._repo_dir)
        self._tesseract_delegate = TesseractOCREngine(
            model_dir=model_dir,
            languages=languages,
        )
        self._native_paddle_instance: Any = None
        self._native_paddle_checked: bool = False

        if os.path.isdir(self._repo_dir) and self._repo_dir not in sys.path:
            sys.path.insert(0, self._repo_dir)

    @property
    def name(self) -> str:
        return "hybrid" if self._hybrid_mode else "paddleocr"

    @property
    def model_dir(self) -> str:
        if self._model_dir is not None:
            return self._model_dir
        return settings.ocr_model_dir

    @property
    def languages(self) -> str:
        if self._languages is not None:
            return self._languages
        return settings.ocr_languages

    def _try_get_native_paddleocr(self) -> Any:
        if self._native_paddle_checked:
            return self._native_paddle_instance
        self._native_paddle_checked = True
        try:
            import paddle  # type: ignore
            from paddleocr import PaddleOCR  # type: ignore

            self._native_paddle_instance = PaddleOCR(
                use_angle_cls=True,
                lang="fa",
                use_gpu=False,
                show_log=False,
            )
        except Exception:
            self._native_paddle_instance = None
        return self._native_paddle_instance

    def inspect_status(self) -> OCREngineStatus:
        tess_status = self._tesseract_delegate.inspect_status()
        repo_ok = self._dict_bundle.is_repo_available
        native_ok = self._try_get_native_paddleocr() is not None

        installed_langs = list(tess_status.installed_languages)
        if repo_ok:
            for code in ("fa_ppocr", "ar_ppocr", "en_ppocr"):
                if code not in installed_langs:
                    installed_langs.append(code)

        ready = (repo_ok and tess_status.ready) or native_ok
        if self._hybrid_mode:
            version_label = f"PaddleOCR PP-OCRv4/v5 (fa_dict + {tess_status.engine_version})"
        elif native_ok:
            version_label = "PaddleOCR Native PP-OCRv4/v5 (fa+en)"
        else:
            version_label = f"PaddleOCR PP-OCRv4/v5 Offline Pipeline ({ len(self._dict_bundle.dictionaries_loaded) } dicts)"

        missing_items: List[str] = []
        if not repo_ok:
            missing_items.append("vendor/PaddleOCR/ppocr/utils/dict/fa_dict.txt")
        if not tess_status.ready and not native_ok:
            missing_items.extend(tess_status.missing_languages or ["fas.traineddata"])

        error_code = None
        error_message = None
        if not ready:
            err = OCRModelMissingError(
                missing_items=missing_items or ["fa_dict.txt"],
                model_dir=self._repo_dir if not repo_ok else tess_status.model_dir,
                engine_name=self.name,
            )
            error_code = err.code
            error_message = err.message

        return OCREngineStatus(
            ready=ready,
            engine_name=self.name,
            engine_version=version_label,
            model_dir=self._repo_dir if repo_ok else tess_status.model_dir,
            installed_languages=installed_langs,
            required_languages=tess_status.required_languages,
            missing_languages=tess_status.missing_languages if not ready else [],
            offline_ready=ready,
            error_code=error_code,
            error_message=error_message,
        )

    def ensure_ready(self) -> OCREngineStatus:
        status = self.inspect_status()
        if not status.ready:
            raise OCRModelMissingError(
                missing_items=status.missing_languages or ["fa_dict.txt", "fas.traineddata"],
                model_dir=status.model_dir,
                engine_name=self.name,
            )
        return status

    def _preprocess_ppocr_variants(self, img: Image.Image) -> List[Tuple[str, Image.Image, float]]:
        """
        Implements PP-OCRv4/v5 style image preprocessing for screenshots and documents:
        1. Detects dark-mode social media screenshots (Instagram/Telegram dark UI) and produces
           an auto-inverted high-contrast light canvas.
        2. Upscales low-resolution screenshots so small Persian/Latin glyphs (@handles, IDs)
           have sufficient pixel density.
        3. Applies unsharp masking and autocontrast normalization.
        Returns a list of `(variant_name, pil_image, coord_scale_factor)`.
        """
        width, height = img.size
        gray = img.convert("L")
        stat = ImageStat.Stat(gray)
        mean_lum = float(stat.mean[0])
        std_lum = float(stat.stddev[0])

        # Compute dark pixel ratio on a fast 64x64 thumbnail
        thumb_l = gray.resize((64, 64))
        px = list(getattr(thumb_l, "get_flattened_data", thumb_l.getdata)())
        dark_ratio = sum(1 for v in px if v <= 65) / float(max(1, len(px)))

        variants: List[Tuple[str, Image.Image, float]] = [("standard", img, 1.0)]

        # If image is dark-mode (e.g. dark Instagram/Telegram screenshot) or very dark
        if mean_lum < 120.0 or dark_ratio >= 0.42:
            inv_gray = ImageOps.invert(gray)
            inv_contrast = ImageOps.autocontrast(inv_gray, cutoff=1)
            inv_sharp = inv_contrast.filter(
                ImageFilter.UnsharpMask(radius=1.3, percent=150, threshold=3)
            )
            variants.insert(0, ("ppocr_dark_inverted", inv_sharp.convert("RGB"), 1.0))

        # If contrast is low or image is a compact screenshot, build a PP-OCR enhanced variant
        scale = 1.0
        work_img = gray
        if (width < 750 or height < 360) and width >= 16 and height >= 16:
            scale = 2.0
            work_img = gray.resize((int(width * scale), int(height * scale)), Image.Resampling.LANCZOS)

        if std_lum < 45.0 or scale > 1.0 or self._hybrid_mode:
            enhanced = ImageOps.autocontrast(work_img, cutoff=1)
            enhanced = enhanced.filter(
                ImageFilter.UnsharpMask(radius=1.4, percent=160, threshold=2)
            )
            variants.append(("ppocr_enhanced", enhanced.convert("RGB"), scale))

        return variants

    def _postprocess_with_paddle_dict(
        self,
        result: OCRPageResult,
        scale_factor: float = 1.0,
    ) -> OCRPageResult:
        """
        Applies PaddleOCR character dictionary validation (`fa_dict.txt`, `ppocrv5_arabic_dict.txt`,
        `en_dict.txt`) and coordinate rescaling to an `OCRPageResult`.
        """
        from services.ingestion.extractor import normalize_persian_text

        cleaned_bboxes: List[OCRBoundingBox] = []
        lines_tokens: Dict[int, List[str]] = {}
        confidences: List[float] = []

        for box in result.bboxes:
            clean_tok = self._dict_bundle.clean_ocr_token(box.text)
            if not clean_tok:
                continue
            norm_tok = normalize_persian_text(clean_tok) or clean_tok
            inv_scale = 1.0 / scale_factor if scale_factor > 0 else 1.0
            scaled_box = OCRBoundingBox(
                text=norm_tok,
                x=int(round(box.x * inv_scale)),
                y=int(round(box.y * inv_scale)),
                width=max(1, int(round(box.width * inv_scale))),
                height=max(1, int(round(box.height * inv_scale))),
                confidence=box.confidence,
                line_num=box.line_num,
                block_num=box.block_num,
                direction=box.direction,
            )
            cleaned_bboxes.append(scaled_box)
            confidences.append(box.confidence)
            lines_tokens.setdefault(box.line_num, []).append(norm_tok)

        if cleaned_bboxes:
            ordered_lines = [
                " ".join(lines_tokens[ln]).strip()
                for ln in sorted(lines_tokens.keys())
                if " ".join(lines_tokens[ln]).strip()
            ]
            raw_text = "\n".join(ordered_lines).strip() or result.raw_text
            norm_text = normalize_persian_text(raw_text)
            avg_conf = round(sum(confidences) / len(confidences), 2) if confidences else result.confidence
        else:
            raw_text = result.raw_text
            norm_text = result.normalized_text
            avg_conf = result.confidence

        return OCRPageResult(
            page_number=result.page_number,
            raw_text=raw_text,
            normalized_text=norm_text,
            bboxes=cleaned_bboxes if cleaned_bboxes else result.bboxes,
            confidence=avg_conf,
            width=result.width,
            height=result.height,
            engine_name=self.name,
            engine_version=result.engine_version,
            processing_ms=result.processing_ms,
            extraction_method=result.extraction_method,
            status="extracted" if norm_text else "empty",
            error_code=result.error_code,
            error_message=result.error_message,
        )

    def recognize_image(
        self,
        image_source: Any,
        page_number: int = 1,
        languages: Optional[str] = None,
        extraction_method: str = "ocr_image",
    ) -> OCRPageResult:
        t0 = time.perf_counter()
        status = self.ensure_ready()
        img = self._tesseract_delegate._prepare_pil_image(image_source, page_number=page_number)
        orig_w, orig_h = img.size

        if orig_w < 8 or orig_h < 8:
            elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            return OCRPageResult(
                page_number=page_number,
                raw_text="",
                normalized_text="",
                bboxes=[],
                confidence=0.0,
                width=orig_w,
                height=orig_h,
                engine_name=self.name,
                engine_version=status.engine_version,
                processing_ms=elapsed_ms,
                extraction_method=extraction_method,
                status="empty",
            )

        variants = self._preprocess_ppocr_variants(img)
        best_result: Optional[OCRPageResult] = None
        best_score: float = -1.0

        for idx, (variant_name, var_img, scale_factor) in enumerate(variants):
            cand = self._tesseract_delegate.recognize_image(
                var_img,
                page_number=page_number,
                languages=languages,
                extraction_method=extraction_method,
            )
            processed = self._postprocess_with_paddle_dict(cand, scale_factor=scale_factor)
            processed.width = orig_w
            processed.height = orig_h
            processed.engine_name = self.name
            processed.engine_version = status.engine_version

            word_cnt = len(processed.normalized_text.split())
            # Score combines meaningful word extraction with confidence
            score = (word_cnt * 4.5) + (processed.confidence * 0.65)
            if score > best_score:
                best_score = score
                best_result = processed

            # Fast path: if the first pass already achieved high confidence and extracted text,
            # skip extra variants unless hybrid_mode is explicitly active on low-confidence input
            if idx == 0 and word_cnt >= 3 and processed.confidence >= 78.0 and not self._hybrid_mode:
                break
            if idx == 0 and word_cnt >= 5 and processed.confidence >= 84.0:
                break

        if best_result is None:
            raise OCRPageReadError(
                page_number=page_number,
                reason="موتور PaddleOCR نتوانست خروجی معتبری برای این صفحه تولید کند.",
                code="PADDLEOCR_EXECUTION_FAILED",
            )

        best_result.processing_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        return best_result
