from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from PIL import Image, ImageStat

from services.ingestion.extractor import normalize_persian_text


@dataclass
class ImageAnalysisResult:
    file_id: str
    title: str
    relative_path: str = ""
    image_path: str = ""
    mime_type: str = "image/png"
    file_size: int = 0
    width: int = 0
    height: int = 0
    aspect_ratio: float = 1.0
    orientation: str = "افقی (Landscape)"
    color_mode: str = "RGB"
    dominant_color_hex: str = "#F5F3EE"
    color_profile_label: str = "زمینهٔ روشن کاغذی"
    mean_brightness: float = 240.0
    contrast_std: float = 25.0
    paper_bg_ratio: float = 0.8
    edge_density: float = 0.05
    word_count: int = 0
    char_count: int = 0
    line_count: int = 0
    bbox_count: int = 0
    ocr_confidence: Optional[float] = None
    extracted_text: str = ""
    image_nature: str = "سند یا برگهٔ متنی اسکن‌شده"
    detected_topic: str = "اداری و مکاتبات"
    confidence_label: str = "بالا"
    tags: List[str] = field(default_factory=list)
    key_findings: List[str] = field(default_factory=list)
    analysis_summary: str = ""


_TOPIC_KEYWORDS: Dict[str, List[str]] = {
    "مالی و حسابداری": [
        "مالی", "حسابداری", "حسابرسی", "فاکتور", "رسید", "مبلغ", "ریال", "تومان",
        "پرداخت", "بانک", "چک", "سود", "زیان", "بودجه", "ترازنامه", "هزینه",
        "درآمد", "مالیات", "ارزش افزوده", "invoice", "receipt", "payment", "total",
        "amount", "tax", "financial", "budget", "bank",
    ],
    "حقوقی و قراردادها": [
        "قرارداد", "ماده", "تبصره", "پیمانکار", "کارفرما", "تعهد", "حقوقی",
        "صورت‌جلسه", "صورتجلسه", "امضا", "گواهی", "مجوز", "داوری", "فسخ",
        "قانون", "مقررات", "آیین‌نامه", "contract", "agreement", "legal", "clause",
    ],
    "فناوری و نرم‌افزار": [
        "سامانه", "نرم‌افزار", "پلتفرم", "پایگاه داده", "سرور", "کارگر", "کد",
        "برنامه", "هوشمند", "شبکه", "امنیت", "داده", "الگوریتم", "فناوری",
        "کامپیوتر", "سیستم", "خطا", "لاگ", "api", "server", "database", "system",
        "software", "code", "error", "cloud", "docker", "python", "react", "saher",
    ],
    "معماری و مهندسی": [
        "معماری", "سازه", "مهندسی", "نقشه", "پلان", "طرح", "پروژه", "ساختمان",
        "عمران", "تأسیسات", "مقیاس", "متر", "ابعاد", "فنی", "شماره نقشه",
        "architecture", "engineering", "plan", "layout", "cad", "structure",
    ],
    "آموزش و پژوهش": [
        "آموزش", "پژوهش", "مقاله", "دانشگاه", "علمی", "تحقیق", "آزمایش", "درس",
        "کتاب", "فصل", "خلاصه", "یادداشت", "سمینار", "کنفرانس", "منابع",
        "research", "study", "university", "paper", "journal", "education", "course",
    ],
    "طراحی و گرافیک": [
        "طراحی", "گرافیک", "رنگ", "فونت", "رابط کاربری", "تجربه کاربری", "پوستر",
        "لوگو", "برند", "بصری", "چیدمان", "کادر", "تصویرسازی",
        "design", "ui", "ux", "graphic", "brand", "poster", "typography", "color",
    ],
    "اداری و مکاتبات": [
        "نامه", "اداری", "مکاتبات", "پیوست", "شماره", "تاریخ", "جناب", "سرکار",
        "مدیریت", "بایگانی", "آرشیو", "گزارش", "سازمان", "شرکت", "دبیرخانه",
        "اداره", "درخواست", "ابلاغ", "office", "memo", "report", "letter", "archive",
    ],
}


def _compute_visual_metrics(image_path: str) -> Dict[str, Any]:
    """
    Extracts genuine visual and geometric metrics from an image file using Pillow:
    dimensions, aspect ratio, orientation, luminance mean/contrast, paper-like light background
    ratio, dark UI surface ratio, color saturation, edge density, and dominant RGB hex.
    """
    default_metrics = {
        "width": 800,
        "height": 600,
        "aspect_ratio": 1.33,
        "orientation": "افقی (Landscape)",
        "color_mode": "RGB",
        "dominant_color_hex": "#F7F5F0",
        "color_profile_label": "زمینهٔ روشن کاغذی",
        "mean_brightness": 235.0,
        "contrast_std": 28.0,
        "paper_bg_ratio": 0.78,
        "dark_bg_ratio": 0.04,
        "mean_saturation": 12.0,
        "edge_density": 0.06,
    }
    if not image_path or not os.path.exists(image_path):
        return default_metrics

    try:
        with Image.open(image_path) as img:
            orig_mode = img.mode
            width, height = img.size
            if width <= 0 or height <= 0:
                return default_metrics

            ratio = round(width / float(height), 2)
            if 0.92 <= ratio <= 1.08:
                orientation = "مربعی (Square)"
            elif ratio > 1.08:
                orientation = "افقی (Landscape)"
            else:
                orientation = "عمودی (Portrait)"

            rgb = img.convert("RGB")
            thumb = rgb.resize((64, 64))
            pixels = list(getattr(thumb, "get_flattened_data", thumb.getdata)())
            total_px = max(1, len(pixels))

            # Grayscale statistics
            gray = thumb.convert("L")
            stat_l = ImageStat.Stat(gray)
            mean_b = round(float(stat_l.mean[0]), 1)
            std_b = round(float(stat_l.stddev[0]), 1)

            paper_count = 0
            dark_count = 0
            sat_sum = 0.0
            r_sum, g_sum, b_sum = 0, 0, 0

            for r, g, b in pixels:
                r_sum += r
                g_sum += g
                b_sum += b
                c_max = max(r, g, b)
                c_min = min(r, g, b)
                sat = (c_max - c_min)
                sat_sum += sat
                lum = 0.299 * r + 0.587 * g + 0.114 * b
                if lum >= 205 and sat <= 35:
                    paper_count += 1
                elif lum <= 55:
                    dark_count += 1

            paper_ratio = round(paper_count / total_px, 3)
            dark_ratio = round(dark_count / total_px, 3)
            mean_sat = round(sat_sum / total_px, 1)

            avg_r = int(r_sum / total_px)
            avg_g = int(g_sum / total_px)
            avg_b = int(b_sum / total_px)
            dom_hex = f"#{avg_r:02X}{avg_g:02X}{avg_b:02X}"

            # Simple horizontal + vertical gradient edge density on 64x64 luminance grid
            g_bytes = list(getattr(gray, "get_flattened_data", gray.getdata)())
            strong_edges = 0
            comparisons = 0
            for row in range(63):
                row_offset = row * 64
                for col in range(63):
                    idx = row_offset + col
                    val = g_bytes[idx]
                    if abs(val - g_bytes[idx + 1]) > 28 or abs(val - g_bytes[idx + 64]) > 28:
                        strong_edges += 1
                    comparisons += 1
            edge_density = round(strong_edges / max(1, comparisons), 3)

            if paper_ratio >= 0.60 and mean_sat < 28:
                color_profile = "زمینهٔ روشن کاغذی (مناسب اسناد چاپی و اسکن‌شده)"
            elif dark_ratio >= 0.45:
                color_profile = "زمینهٔ تیره با کنتراست بالا (محیط نرم‌افزاری یا حالت تیره)"
            elif mean_sat >= 42:
                color_profile = "طیف رنگی غنی و طبیعی (تصویر عکاسی یا گرافیک رنگی)"
            elif mean_b >= 180:
                color_profile = "طیف روشن و متعادل"
            else:
                color_profile = "طیف میانه با کنتراست استاندارد"

            return {
                "width": width,
                "height": height,
                "aspect_ratio": ratio,
                "orientation": orientation,
                "color_mode": orig_mode,
                "dominant_color_hex": dom_hex,
                "color_profile_label": color_profile,
                "mean_brightness": mean_b,
                "contrast_std": std_b,
                "paper_bg_ratio": paper_ratio,
                "dark_bg_ratio": dark_ratio,
                "mean_saturation": mean_sat,
                "edge_density": edge_density,
            }
    except Exception:
        return default_metrics


def _classify_nature_and_topic(
    title: str,
    norm_text: str,
    visual: Dict[str, Any],
    word_count: int,
    line_count: int,
    bbox_count: int,
) -> Tuple[str, str, List[str]]:
    """
    Determines:
    1. `image_nature` (ماهیت تصویر)
    2. `detected_topic` (موضوع تصویر)
    3. `tags` (برچسب‌های تحلیلی)
    """
    combined_lower = f"{title} {norm_text}".lower()
    digits_found = len(re.findall(r"\d", combined_lower))

    # Score topics based on OCR text + filename
    topic_scores: Dict[str, int] = {k: 0 for k in _TOPIC_KEYWORDS}
    matched_keywords: List[str] = []

    for topic, kw_list in _TOPIC_KEYWORDS.items():
        for kw in kw_list:
            if kw in combined_lower:
                weight = 3 if kw in norm_text.lower() else 2
                topic_scores[topic] += weight
                if len(kw) >= 3 and kw not in matched_keywords and not kw.isascii():
                    matched_keywords.append(kw)

    paper_ratio = visual["paper_bg_ratio"]
    dark_ratio = visual["dark_bg_ratio"]
    mean_sat = visual["mean_saturation"]
    ratio = visual["aspect_ratio"]
    edge_density = visual["edge_density"]

    # Determine Image Nature (ماهیت تصویر)
    is_screenshot_name = any(
        w in title.lower()
        for w in ("screenshot", "screen", "اسکرین", "نماگرفت", "capture", "snap")
    )
    has_financial_terms = topic_scores["مالی و حسابداری"] >= 3
    has_legal_terms = topic_scores["حقوقی و قراردادها"] >= 3
    has_arch_terms = topic_scores["معماری و مهندسی"] >= 3
    has_tech_terms = topic_scores["فناوری و نرم‌افزار"] >= 3

    if has_financial_terms and (word_count >= 3 or digits_found >= 4):
        image_nature = "فاکتور، رسید یا صورت‌حساب مالی"
    elif has_legal_terms and word_count >= 5:
        image_nature = "سند رسمی، قرارداد یا صورت‌جلسهٔ اسکن‌شده"
    elif is_screenshot_name or (dark_ratio >= 0.35 and word_count >= 2) or (
        1.55 <= ratio <= 1.85 and has_tech_terms and paper_ratio < 0.72
    ):
        image_nature = "اسکرین‌شات رابط کاربری یا محیط نرم‌افزار"
    elif has_arch_terms or (paper_ratio >= 0.55 and edge_density >= 0.14 and word_count < 25):
        image_nature = "نقشه، نمودار یا طرح فنی و مهندسی"
    elif paper_ratio >= 0.55 and word_count >= 4:
        if 1.35 <= ratio <= 1.75 and line_count <= 8:
            image_nature = "کارت، فرم مشخصات یا گواهی‌نامهٔ اسکن‌شده"
        else:
            image_nature = "سند یا برگهٔ متنی اسکن‌شده (اداری/مستندات)"
    elif word_count >= 6:
        image_nature = "تصویر حاوی نوشتار و اطلاعات متنی (پوستر/برگهٔ اطلاع‌رسانی)"
    else:
        # Purely visual / photographic / graphic image with little or no text
        if mean_sat >= 35:
            if ratio > 1.2:
                image_nature = "تصویر عکاسی یا منظره با کادر افقی (فاقد متن غالب)"
            elif ratio < 0.85:
                image_nature = "تصویر عکاسی پرتره یا سوژهٔ عمودی (فاقد متن غالب)"
            else:
                image_nature = "تصویر عکاسی یا سوژهٔ بصری رنگی"
        elif paper_ratio >= 0.65 and word_count == 0:
            image_nature = "برگهٔ خام یا تصویر اسکن‌شده با کنتراست متنی پایین"
        else:
            image_nature = "تصویر گرافیکی، نماد بصری یا قطعهٔ طراحی"

    # Select best Topic (موضوع تصویر)
    best_topic = max(topic_scores.items(), key=lambda kv: kv[1])
    if best_topic[1] >= 2:
        detected_topic = best_topic[0]
    else:
        # Infer topic from visual nature when text has no domain-specific keywords
        if "مالی" in image_nature or "فاکتور" in image_nature:
            detected_topic = "مالی و حسابداری"
        elif "قرارداد" in image_nature or "حقوقی" in image_nature:
            detected_topic = "حقوقی و قراردادها"
        elif "اسکرین‌شات" in image_nature or "نرم‌افزار" in image_nature:
            detected_topic = "فناوری و نرم‌افزار"
        elif "نقشه" in image_nature or "مهندسی" in image_nature:
            detected_topic = "معماری و مهندسی"
        elif "سند" in image_nature or "برگه" in image_nature or "فرم" in image_nature:
            detected_topic = "اداری و مکاتبات"
        elif "گرافیکی" in image_nature or "طراحی" in image_nature:
            detected_topic = "طراحی و گرافیک"
        else:
            detected_topic = "عکاسی و تصاویر عمومی"

    # Build clean tags
    tags: List[str] = [detected_topic]
    short_nature = image_nature.split("(")[0].strip()
    if short_nature and short_nature not in tags:
        tags.append(short_nature)
    for kw in matched_keywords[:4]:
        if kw not in tags:
            tags.append(kw)

    return image_nature, detected_topic, tags[:6]


def analyze_image_nature_and_topic(
    file_id: str,
    title: str,
    image_path: str,
    mime_type: str = "image/png",
    file_size: int = 0,
    extracted_text: str = "",
    bboxes: Optional[List[Dict[str, Any]]] = None,
    ocr_confidence: Optional[float] = None,
    relative_path: str = "",
) -> ImageAnalysisResult:
    """
    Performs a comprehensive visual + textual analysis of a single image,
    determining its visual nature (ماهیت تصویر), subject/topic (موضوع),
    structural attributes, and generating a Persian analytical narrative.
    """
    norm_text = normalize_persian_text(extracted_text or "")
    words = [w for w in norm_text.split() if w.strip()]
    lines = [ln.strip() for ln in norm_text.splitlines() if ln.strip()]
    word_count = len(words)
    char_count = len(norm_text)
    line_count = len(lines)
    bbox_list = bboxes or []
    bbox_count = len(bbox_list)

    if ocr_confidence is None and bbox_list:
        confs = [float(b.get("confidence", 0.0)) for b in bbox_list if b.get("confidence") is not None]
        if confs:
            ocr_confidence = round(sum(confs) / len(confs), 1)

    visual = _compute_visual_metrics(image_path)
    image_nature, detected_topic, tags = _classify_nature_and_topic(
        title=title,
        norm_text=norm_text,
        visual=visual,
        word_count=word_count,
        line_count=line_count,
        bbox_count=bbox_count,
    )

    if (ocr_confidence and ocr_confidence >= 80) or word_count >= 8 or visual["paper_bg_ratio"] >= 0.7:
        confidence_label = "بالا"
    elif word_count >= 2 or visual["width"] >= 200:
        confidence_label = "متوسط"
    else:
        confidence_label = "پایین (تصویر بسیار کوچک یا فاقد جزئیات)"

    key_findings: List[str] = [
        f"ماهیت بصری و ساختاری: {image_nature}",
        f"موضوع طبقه‌بندی‌شده: {detected_topic}",
        f"ابعاد و هندسهٔ تصویر: {visual['width']}×{visual['height']} پیکسل ({visual['orientation']}، نسبت ابعاد {visual['aspect_ratio']})",
        f"پروفایل رنگی و روشنایی: {visual['color_profile_label']} (میانگین روشنایی {visual['mean_brightness']} از ۲۵۵، رنگ غالب {visual['dominant_color_hex']})",
    ]

    if word_count > 0:
        conf_str = f" با میانگین اطمینان {ocr_confidence:.1f}٪" if ocr_confidence is not None else ""
        key_findings.append(
            f"تحلیل نوشتاری (OCR): دارای {word_count} کلمه در قالب {line_count} سطر متنی{conf_str}."
        )
        preview_excerpt = " / ".join(lines[:2])[:160]
        key_findings.append(f"گزیدهٔ شاخص متن داخل تصویر: «{preview_excerpt}»")
    else:
        key_findings.append(
            "تحلیل نوشتاری (OCR): هیچ لایهٔ متنی یا نوشتار قابل استخراجی در این تصویر مشاهده نشد (تصویر ماهیت کاملاً بصری/گرافیکی دارد)."
        )

    # Compose detailed analytical paragraph for the Word report & UI
    if word_count > 0:
        first_line = lines[0][:110] if lines else ""
        summary = (
            f"بر اساس واکاوی بصری و محتوایی، تصویر «{title}» دارای ماهیت «{image_nature}» بوده و در حوزهٔ موضوعی "
            f"«{detected_topic}» قرار می‌گیرد. این فایل با ابعاد {visual['width']}×{visual['height']} پیکسل "
            f"({visual['orientation']}) دارای {visual['color_profile_label']} است. "
            f"موتور تشخیص متن آفلاین ساهر در مجموع {word_count} کلمه ({line_count} سطر) را از داخل این تصویر استخراج کرده است"
            f"{f' که بخش آغازین آن شامل عبارت «{first_line}» است' if first_line else ''}."
        )
    else:
        summary = (
            f"بر اساس بررسی ویژگی‌های بصری، رنگ و کنتراست، فایل «{title}» دارای ماهیت «{image_nature}» بوده و در دستهٔ "
            f"«{detected_topic}» جای می‌گیرد. تصویر دارای ابعاد {visual['width']}×{visual['height']} پیکسل "
            f"({visual['orientation']}) و {visual['color_profile_label']} است و فاقد نوشتار چاپی غالب در سطح تصویر می‌باشد."
        )

    return ImageAnalysisResult(
        file_id=file_id,
        title=title,
        relative_path=relative_path or title,
        image_path=image_path,
        mime_type=mime_type,
        file_size=file_size,
        width=visual["width"],
        height=visual["height"],
        aspect_ratio=visual["aspect_ratio"],
        orientation=visual["orientation"],
        color_mode=visual["color_mode"],
        dominant_color_hex=visual["dominant_color_hex"],
        color_profile_label=visual["color_profile_label"],
        mean_brightness=visual["mean_brightness"],
        contrast_std=visual["contrast_std"],
        paper_bg_ratio=visual["paper_bg_ratio"],
        edge_density=visual["edge_density"],
        word_count=word_count,
        char_count=char_count,
        line_count=line_count,
        bbox_count=bbox_count,
        ocr_confidence=ocr_confidence,
        extracted_text=norm_text,
        image_nature=image_nature,
        detected_topic=detected_topic,
        confidence_label=confidence_label,
        tags=tags,
        key_findings=key_findings,
        analysis_summary=summary,
    )
