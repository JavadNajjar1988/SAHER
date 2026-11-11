import os
import re
import time
import shutil
import subprocess
from typing import List, Optional, Any, Dict, Tuple
from services.api.config import settings
from services.ocr.base import (
    OCREngineAdapter,
    OCREngineStatus,
    OCRPageResult,
    OCRBoundingBox,
    OCRModelMissingError,
    OCRPageReadError,
)

_PERSIAN_ARABIC_RE = re.compile(r"[\u0600-\u06FF\uFB50-\uFDFF\uFE70-\uFEFF]")


def _contains_rtl(text: str) -> bool:
    return bool(_PERSIAN_ARABIC_RE.search(text or ""))


class TesseractOCREngine(OCREngineAdapter):
    """
    Offline Persian + English OCR Engine backed by Tesseract 5 LSTM (`fas+eng`).
    Reads language models strictly from the configured local `tessdata` directory
    without requiring any internet access at runtime.
    """

    def __init__(
        self,
        model_dir: Optional[str] = None,
        languages: Optional[str] = None,
    ):
        self._model_dir = model_dir
        self._languages = languages

    @property
    def name(self) -> str:
        return "tesseract"

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

    def _required_lang_codes(self, languages: Optional[str] = None) -> List[str]:
        raw = languages or self.languages or "fas+eng"
        return [code.strip() for code in raw.replace(",", "+").split("+") if code.strip()]

    def _resolve_tesseract_bin(self) -> Optional[str]:
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        bundled_bin = os.path.join(root_dir, "node_modules", ".saher_bin", "tesseract")
        bundled_lib = os.path.join(root_dir, "node_modules", ".saher_bin", "lib")
        if os.path.isfile(bundled_bin) and os.access(bundled_bin, os.X_OK):
            if os.path.isdir(bundled_lib):
                cur_ld = os.environ.get("LD_LIBRARY_PATH", "")
                if bundled_lib not in cur_ld:
                    os.environ["LD_LIBRARY_PATH"] = f"{bundled_lib}:{cur_ld}" if cur_ld else bundled_lib
            try:
                import pytesseract
                pytesseract.pytesseract.tesseract_cmd = bundled_bin
            except Exception:
                pass
            return bundled_bin
        return shutil.which("tesseract")

    def _detect_tesseract_version(self) -> Tuple[bool, str]:
        bin_path = self._resolve_tesseract_bin()
        if not bin_path:
            return False, "not_installed"
        try:
            proc = subprocess.run(
                [bin_path, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
                env=os.environ.copy(),
            )
            first_line = (proc.stdout or proc.stderr or "").splitlines()
            version_str = first_line[0].strip() if first_line else "tesseract 5.x"
            return True, version_str
        except Exception:
            return False, "unknown"

    def inspect_status(self) -> OCREngineStatus:
        has_bin, version_str = self._detect_tesseract_version()
        model_dir = self.model_dir
        required = self._required_lang_codes()
        installed: List[str] = []

        if os.path.isdir(model_dir):
            for entry in os.listdir(model_dir):
                if entry.endswith(".traineddata"):
                    lang_code = entry[: -len(".traineddata")]
                    if lang_code:
                        installed.append(lang_code)
        installed.sort()

        missing_langs = [lang for lang in required if lang not in installed]
        missing_items: List[str] = []
        if not has_bin:
            missing_items.append("tesseract-ocr (باینری موتور)")
        for ml in missing_langs:
            missing_items.append(f"{ml}.traineddata")

        ready = has_bin and len(missing_langs) == 0
        error_code = None
        error_message = None
        if not ready:
            err = OCRModelMissingError(
                missing_items=missing_items,
                model_dir=model_dir,
                engine_name=self.name,
            )
            error_code = err.code
            error_message = err.message

        return OCREngineStatus(
            ready=ready,
            engine_name=self.name,
            engine_version=version_str,
            model_dir=model_dir,
            installed_languages=installed,
            required_languages=required,
            missing_languages=missing_langs,
            offline_ready=ready,
            error_code=error_code,
            error_message=error_message,
        )

    def ensure_ready(self) -> OCREngineStatus:
        status = self.inspect_status()
        if not status.ready:
            missing_items: List[str] = []
            if status.engine_version == "not_installed":
                missing_items.append("tesseract-ocr")
            for ml in status.missing_languages:
                missing_items.append(f"{ml}.traineddata")
            raise OCRModelMissingError(
                missing_items=missing_items or ["fas.traineddata"],
                model_dir=status.model_dir,
                engine_name=self.name,
            )
        return status

    def _prepare_pil_image(self, image_source: Any, page_number: int):
        from PIL import Image, ImageOps

        try:
            if isinstance(image_source, str):
                if not os.path.exists(image_source):
                    raise OCRPageReadError(
                        page_number=page_number,
                        reason="فایل تصویر منبع در دیسک یافت نشد.",
                        code="OCR_IMAGE_MISSING",
                    )
                img = Image.open(image_source)
                img.load()
            elif isinstance(image_source, Image.Image):
                img = image_source.copy()
            else:
                raise OCRPageReadError(
                    page_number=page_number,
                    reason="فرمت ورودی تصویر برای موتور OCR معتبر نیست.",
                    code="OCR_INVALID_IMAGE_INPUT",
                )

            if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                rgba = img.convert("RGBA")
                white_bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
                img = Image.alpha_composite(white_bg, rgba).convert("RGB")
            elif img.mode != "RGB":
                img = img.convert("RGB")

            img = ImageOps.exif_transpose(img)
            return img
        except OCRPageReadError:
            raise
        except Exception as exc:
            raise OCRPageReadError(
                page_number=page_number,
                reason=f"تصویر صفحه آسیب‌دیده یا غیرقابل بازگشایی است ({exc}).",
                code="OCR_CORRUPTED_PAGE_IMAGE",
            ) from exc

    def recognize_image(
        self,
        image_source: Any,
        page_number: int = 1,
        languages: Optional[str] = None,
        extraction_method: str = "ocr_image",
    ) -> OCRPageResult:
        from services.ingestion.extractor import normalize_persian_text
        import pytesseract

        t0 = time.perf_counter()
        status = self.ensure_ready()
        img = self._prepare_pil_image(image_source, page_number=page_number)
        width, height = img.size

        # Very tiny images (e.g., 1x1 or 2x2 synthetic test fixtures) contain no readable glyphs
        if width < 8 or height < 8:
            elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            return OCRPageResult(
                page_number=page_number,
                raw_text="",
                normalized_text="",
                bboxes=[],
                confidence=0.0,
                width=width,
                height=height,
                engine_name=self.name,
                engine_version=status.engine_version,
                processing_ms=elapsed_ms,
                extraction_method=extraction_method,
                status="empty",
            )

        lang_spec = languages or self.languages or "fas+eng"
        tess_config = f'--tessdata-dir "{status.model_dir}" --oem 1 --psm 6'

        try:
            from services.worker.execution import remaining_seconds
            data = pytesseract.image_to_data(
                img,
                lang=lang_spec,
                config=tess_config,
                output_type=pytesseract.Output.DICT,
                timeout=remaining_seconds(max(1, settings.job_timeout_seconds)),
            )
        except Exception as exc:
            raise OCRPageReadError(
                page_number=page_number,
                reason=f"خطا در اجرای موتور تشخیص متن روی صفحهٔ {page_number}: {exc}",
                code="OCR_EXECUTION_FAILED",
            ) from exc

        # Group recognized words by (block_num, par_num, line_num)
        lines_map: Dict[Tuple[int, int, int], List[Dict[str, Any]]] = {}
        n_items = len(data.get("text", []))
        for i in range(n_items):
            raw_word = (data["text"][i] or "").strip()
            if not raw_word:
                continue
            try:
                conf = float(data["conf"][i])
            except (ValueError, TypeError):
                conf = 0.0
            if conf < 0:
                continue

            left = int(data["left"][i])
            top = int(data["top"][i])
            w = int(data["width"][i])
            h = int(data["height"][i])
            block_num = int(data["block_num"][i] or 1)
            par_num = int(data["par_num"][i] or 1)
            line_num = int(data["line_num"][i] or 1)
            word_num = int(data["word_num"][i] or 1)

            key = (block_num, par_num, line_num)
            lines_map.setdefault(key, []).append(
                {
                    "text": raw_word,
                    "left": left,
                    "top": top,
                    "width": w,
                    "height": h,
                    "right": left + w,
                    "confidence": round(conf, 2),
                    "block_num": block_num,
                    "line_num": line_num,
                    "word_num": word_num,
                }
            )

        # Sort lines vertically from top to bottom
        sorted_line_keys = sorted(
            lines_map.keys(),
            key=lambda k: (min(w["top"] for w in lines_map[k]), k[0], k[1], k[2]),
        )

        ordered_lines_raw: List[str] = []
        bboxes: List[OCRBoundingBox] = []
        confidences: List[float] = []

        for line_idx, key in enumerate(sorted_line_keys, start=1):
            words = lines_map[key]
            joined_preview = " ".join(w["text"] for w in words)
            is_rtl_line = _contains_rtl(joined_preview)

            if is_rtl_line:
                # In Persian/RTL lines, words in visual right-to-left order have descending `right` coordinates
                words_sorted = sorted(words, key=lambda w: (-w["right"], w["word_num"]))
                direction = "rtl"
            else:
                words_sorted = sorted(words, key=lambda w: (w["left"], w["word_num"]))
                direction = "ltr"

            line_tokens: List[str] = []
            for w in words_sorted:
                line_tokens.append(w["text"])
                confidences.append(w["confidence"])
                bboxes.append(
                    OCRBoundingBox(
                        text=normalize_persian_text(w["text"]) or w["text"],
                        x=w["left"],
                        y=w["top"],
                        width=w["width"],
                        height=w["height"],
                        confidence=w["confidence"],
                        line_num=line_idx,
                        block_num=w["block_num"],
                        direction=direction,
                    )
                )

            line_str = " ".join(line_tokens).strip()
            if line_str:
                ordered_lines_raw.append(line_str)

        raw_text = "\n".join(ordered_lines_raw).strip()
        normalized_text = normalize_persian_text(raw_text)
        avg_conf = round(sum(confidences) / len(confidences), 2) if confidences else 0.0
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)

        return OCRPageResult(
            page_number=page_number,
            raw_text=raw_text,
            normalized_text=normalized_text,
            bboxes=bboxes,
            confidence=avg_conf,
            width=width,
            height=height,
            engine_name=self.name,
            engine_version=status.engine_version,
            processing_ms=elapsed_ms,
            extraction_method=extraction_method,
            status="extracted" if normalized_text else "empty",
        )
