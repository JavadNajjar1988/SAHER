from __future__ import annotations

import io
import os
from datetime import datetime
from typing import Dict, List

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from PIL import Image

from services.analysis.image_analyzer import (
    ImageAnalysisResult,
    merge_batch_cultural_social_templates,
)


def _set_rtl_paragraph(paragraph) -> None:
    """Configures a python-docx paragraph for right-to-left (RTL) Persian layout."""
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    pPr = paragraph._p.get_or_add_pPr()
    bidi = OxmlElement("w:bidi")
    bidi.set(qn("w:val"), "1")
    pPr.append(bidi)


def _style_run_persian(run, font_size_pt: int = 11, bold: bool = False, color_rgb: tuple = (25, 33, 30)) -> None:
    run.font.name = "Vazirmatn"
    run.font.size = Pt(font_size_pt)
    run.font.bold = bold
    run.font.color.rgb = RGBColor(*color_rgb)
    rPr = run._r.get_or_add_rPr()
    rFonts = OxmlElement("w:rFonts")
    rFonts.set(qn("w:ascii"), "Vazirmatn")
    rFonts.set(qn("w:hAnsi"), "Vazirmatn")
    rFonts.set(qn("w:cs"), "Vazirmatn")
    rPr.append(rFonts)
    rtl = OxmlElement("w:rtl")
    rtl.set(qn("w:val"), "1")
    rPr.append(rtl)


def _set_table_rtl(table) -> None:
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    tblPr = table._tbl.tblPr
    bidiVisual = OxmlElement("w:bidiVisual")
    tblPr.append(bidiVisual)


def _set_cell_text(cell, text: str, bold: bool = False, font_size_pt: int = 10, color_rgb: tuple = (28, 37, 34)) -> None:
    cell.text = ""
    p = cell.paragraphs[0]
    _set_rtl_paragraph(p)
    run = p.add_run(text)
    _style_run_persian(run, font_size_pt=font_size_pt, bold=bold, color_rgb=color_rgb)


def _prepare_normalized_png_stream(image_path: str, max_px: int = 900) -> io.BytesIO | None:
    """Converts any supported image (PNG/JPG/WEBP/BMP) into a clean RGB PNG stream for Word embedding."""
    if not image_path or not os.path.exists(image_path):
        return None
    try:
        with Image.open(image_path) as img:
            rgb = img.convert("RGB")
            rgb.thumbnail((max_px, max_px))
            buf = io.BytesIO()
            rgb.save(buf, format="PNG")
            buf.seek(0)
            return buf
    except Exception:
        return None


def generate_image_analysis_docx(
    analyses: List[ImageAnalysisResult],
    folder_name: str = "پوشهٔ تصاویر انتخابی",
) -> bytes:
    """
    Generates a comprehensive, RTL-formatted Microsoft Word (.docx) document in Persian containing:
    1. Executive summary of:
       - دسته‌بندی عکس‌ها از نظر اسکرین‌شات، عکس با دوربین، عکس سوژه، سند اسکن‌شده و نقشه
       - پوشه‌بندی شخصی و شناسه آی‌دی روی عکس + دسته‌بندی در ۱۲ سرفصل موضوعی
       - موقعیت مکانی و مختصات جغرافیایی
       - خلاصهٔ بررسی موارد مجرمانه بر اساس داده‌های حقوقی و قضایی
    2. A separate, dedicated analysis section for EACH individual screenshot/image, including:
       - Embedded thumbnail preview of the image
       - Structured specification table (پوشهٔ شخصی، شناسه آی‌دی، سرفصل ۱۲گانه، نوع عکس، سوژه، موقعیت مکانی و مختصات، مشخصات انفرادی و شناسنامه‌ای، موبایل و آدرس، و بررسی موارد مجرمانه)
       - Exact title & text inspection + Legal & Judicial Criminal Assessment
       - Cultural & Social Structured Template (قواره ویژه فرهنگی و اجتماعی) when applicable
       - Verbatim extracted OCR text from inside the image
    """
    doc = Document()

    # 1. Cover / Report Header
    title_p = doc.add_paragraph()
    _set_rtl_paragraph(title_p)
    title_run = title_p.add_run(
        "گزارش جامع تحلیل هوشمند عکس‌ها و اسکرین‌شات‌ها (پوشه‌بندی شخصی، ۱۲ سرفصل موضوعی، مشخصات انفرادی و بررسی حقوقی و قضایی)"
    )
    _style_run_persian(title_run, font_size_pt=16, bold=True, color_rgb=(31, 92, 74))

    subtitle_p = doc.add_paragraph()
    _set_rtl_paragraph(subtitle_p)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    sub_run = subtitle_p.add_run(
        f"سامانهٔ بایگانی و تحلیل آفلاین ساهر · نام مجموعه/پوشه: {folder_name or 'پوشهٔ تصاویر'} · "
        f"تعداد تصاویر تحلیل‌شده: {len(analyses)} تصویر · تاریخ تولید گزارش: {now_str}"
    )
    _style_run_persian(sub_run, font_size_pt=10, bold=False, color_rgb=(95, 108, 103))

    # 2. Multi-Axis Summary Breakdown
    if analyses:
        canonical_labels: Dict[str, str] = {}
        for item in analyses:
            acc_id = (getattr(item, "account_id", "") or "").strip()
            if acc_id and acc_id != "نامشخص":
                key = acc_id.lower()
                lbl = getattr(item, "account_label", "") or acc_id
                if key not in canonical_labels or len(lbl) > len(canonical_labels[key]):
                    canonical_labels[key] = lbl
        for item in analyses:
            acc_id = (getattr(item, "account_id", "") or "").strip()
            if acc_id and acc_id != "نامشخص" and acc_id.lower() in canonical_labels:
                item.account_label = canonical_labels[acc_id.lower()]

        merge_batch_cultural_social_templates(analyses)

        account_counts: Dict[str, int] = {}
        account_tree: Dict[str, Dict[str, int]] = {}
        topic_counts: Dict[str, int] = {}
        nature_counts: Dict[str, int] = {}
        source_counts: Dict[str, int] = {}
        location_counts: Dict[str, int] = {}
        criminal_count = 0

        for item in analyses:
            acc = getattr(item, "account_label", None) or "بدون نام کاربری / آیدی مشخص"
            cat = getattr(item, "thematic_category", None) or item.detected_topic
            src_cat = getattr(item, "capture_source_category", None) or "اسکرین‌شات موبایل / شبکهٔ اجتماعی"
            loc_lbl = getattr(item, "location_name", None) or "موقعیت مکانی ثبت‌نشده"
            crim = getattr(item, "criminal_assessment", None) or {}
            if crim.get("has_criminal_indicator"):
                criminal_count += 1

            account_counts[acc] = account_counts.get(acc, 0) + 1
            if acc not in account_tree:
                account_tree[acc] = {}
            account_tree[acc][cat] = account_tree[acc].get(cat, 0) + 1
            topic_counts[cat] = topic_counts.get(cat, 0) + 1
            nature_counts[item.image_nature] = nature_counts.get(item.image_nature, 0) + 1
            source_counts[src_cat] = source_counts.get(src_cat, 0) + 1
            location_counts[loc_lbl] = location_counts.get(loc_lbl, 0) + 1

        sec_h = doc.add_paragraph()
        _set_rtl_paragraph(sec_h)
        r_sh = sec_h.add_run(
            "۱. خلاصهٔ دسته‌بندی چندبعدی (نوع عکس، پوشه‌بندی شخصی و آیدی، ۱۲ سرفصل موضوعی، موقعیت مکانی و بررسی قضایی)"
        )
        _style_run_persian(r_sh, font_size_pt=14, bold=True, color_rgb=(25, 33, 30))

        dist_p = doc.add_paragraph()
        _set_rtl_paragraph(dist_p)
        sources_summary = " ، ".join(f"{k}: {v} مورد" for k, v in source_counts.items())
        accounts_summary = " ، ".join(f"{k}: {v} مورد" for k, v in account_counts.items())
        topics_summary = " ، ".join(f"{k}: {v} مورد" for k, v in topic_counts.items())
        locs_summary = " ، ".join(f"{k}: {v} مورد" for k, v in location_counts.items())
        natures_summary = " ، ".join(f"{k}: {v} مورد" for k, v in nature_counts.items())
        r_dist = dist_p.add_run(
            f"• تفکیک نوع عکس (اسکرین‌شات / عکس دوربین / عکس سوژه / سند): {sources_summary}\n"
            f"• اولویت اول — پوشه‌بندی شخصی و شناسه آی‌دی روی عکس: {accounts_summary}\n"
            f"• اولویت دوم — دسته‌بندی در ۱۲ سرفصل موضوعی: {topics_summary}\n"
            f"• تفکیک موقعیت مکانی و مختصات: {locs_summary}\n"
            f"• تفکیک ماهیت بصری تصاویر: {natures_summary}\n"
            f"• وضعیت بررسی حقوقی و قضایی: {criminal_count} تصویر دارای قرینه/مصداق مجرمانه و نیازمند پیگیری قضایی از مجموع {len(analyses)} تصویر"
        )
        _style_run_persian(r_dist, font_size_pt=10, bold=False, color_rgb=(45, 55, 52))

        # Hierarchical Priority-1 -> Priority-2 Matrix Table
        tree_h = doc.add_paragraph()
        _set_rtl_paragraph(tree_h)
        r_th = tree_h.add_run("جدول تفکیک اولویت اول (پوشهٔ شخصی و نام کاربری/آیدی) و زیرشاخه‌های موضوعی ۱۲گانه (اولویت دوم):")
        _style_run_persian(r_th, font_size_pt=11, bold=True, color_rgb=(31, 92, 74))

        tree_table = doc.add_table(rows=1, cols=3)
        tree_table.style = "Table Grid"
        _set_table_rtl(tree_table)
        t_headers = [
            "پوشهٔ شخصی / نام کاربری و آیدی (اولویت اول)",
            "تعداد کل تصاویر",
            "تفکیک در ۱۲ دسته‌بندی موضوعی (اولویت دوم)",
        ]
        for i, h_text in enumerate(t_headers):
            _set_cell_text(tree_table.rows[0].cells[i], h_text, bold=True, font_size_pt=10, color_rgb=(31, 92, 74))

        for acc_label, total_cnt in account_counts.items():
            row_c = tree_table.add_row().cells
            _set_cell_text(row_c[0], acc_label, bold=True)
            _set_cell_text(row_c[1], f"{total_cnt} تصویر")
            sub_cats_str = " ، ".join(
                f"{cat_name} ({cnt})" for cat_name, cnt in account_tree.get(acc_label, {}).items()
            )
            _set_cell_text(row_c[2], sub_cats_str)

        doc.add_paragraph()

        # Overview table of all individual images
        summary_table = doc.add_table(rows=1, cols=8)
        summary_table.style = "Table Grid"
        _set_table_rtl(summary_table)
        headers = [
            "ردیف",
            "نام کاربری و آیدی (اولویت ۱)",
            "دسته‌بندی موضوعی (اولویت ۲)",
            "نوع عکس (اسکرین‌شات/دوربین/سوژه)",
            "موقعیت مکانی / مختصات",
            "نام تصویر / مسیر",
            "وضعیت حقوقی و قضایی",
            "کلمات استخراج‌شده",
        ]
        hdr_cells = summary_table.rows[0].cells
        for i, h_text in enumerate(headers):
            _set_cell_text(hdr_cells[i], h_text, bold=True, font_size_pt=9, color_rgb=(31, 92, 74))

        for idx, item in enumerate(analyses, start=1):
            row_cells = summary_table.add_row().cells
            acc = getattr(item, "account_label", None) or "بدون نام کاربری / آیدی مشخص"
            cat = getattr(item, "thematic_category", None) or item.detected_topic
            src_cat = getattr(item, "capture_source_category", None) or item.image_nature
            loc_str = getattr(item, "location_name", None) or "ثبت‌نشده"
            gps_str = getattr(item, "gps_coordinates", None) or ""
            full_loc = f"{loc_str} ({gps_str})" if gps_str and gps_str not in loc_str else loc_str
            crim = getattr(item, "criminal_assessment", None) or {}
            crim_status = crim.get("risk_level", "عادی")

            _set_cell_text(row_cells[0], str(idx), font_size_pt=9)
            _set_cell_text(row_cells[1], acc, bold=True, font_size_pt=9)
            _set_cell_text(row_cells[2], cat, bold=True, font_size_pt=9)
            _set_cell_text(row_cells[3], src_cat, font_size_pt=9)
            _set_cell_text(row_cells[4], full_loc, font_size_pt=9)
            _set_cell_text(row_cells[5], item.relative_path or item.title, font_size_pt=9)
            _set_cell_text(row_cells[6], crim_status, bold=bool(crim.get("has_criminal_indicator")), font_size_pt=9)
            _set_cell_text(row_cells[7], f"{item.word_count} کلمه", font_size_pt=9)

    # 3. Separate Per-Image Analysis Sections
    for idx, item in enumerate(analyses, start=1):
        if idx > 1 or len(analyses) > 1:
            doc.add_page_break()

        acc_label = getattr(item, "account_label", None) or "بدون نام کاربری / آیدی مشخص"
        cat_label = getattr(item, "thematic_category", None) or item.detected_topic
        platform_src = getattr(item, "platform_source", None) or "اسکرین‌شات / تصویر عمومی"
        personal_folder = getattr(item, "personal_folder", None) or f"پوشهٔ شخصی: {acc_label}"
        capture_source = getattr(item, "capture_source_category", None) or "اسکرین‌شات موبایل / شبکهٔ اجتماعی"
        subject_cls = getattr(item, "subject_classification", None) or "تصویر / اسکرین‌شات"
        camera_info = getattr(item, "camera_info", None) or "بدون فرادادهٔ دوربین"
        location_name = getattr(item, "location_name", None) or "موقعیت مکانی ثبت‌نشده"
        gps_coords = getattr(item, "gps_coordinates", None) or ""
        pid = getattr(item, "personal_identity", None) or {}
        crim = getattr(item, "criminal_assessment", None) or {}

        img_h = doc.add_paragraph()
        _set_rtl_paragraph(img_h)
        r_ih = img_h.add_run(f"تصویر شمارهٔ {idx}: {item.title}")
        _style_run_persian(r_ih, font_size_pt=15, bold=True, color_rgb=(31, 92, 74))

        hier_p = doc.add_paragraph()
        _set_rtl_paragraph(hier_p)
        r_hp = hier_p.add_run(
            f"پوشهٔ شخصی: {personal_folder}   |   اولویت ۱ (نام کاربری و آیدی): {acc_label}   |   اولویت ۲ (سرفصل ۱۲گانه): {cat_label}"
        )
        _style_run_persian(r_hp, font_size_pt=11, bold=True, color_rgb=(40, 75, 65))

        if item.relative_path and item.relative_path != item.title:
            path_p = doc.add_paragraph()
            _set_rtl_paragraph(path_p)
            r_path = path_p.add_run(f"مسیر در پوشه: {item.relative_path}")
            _style_run_persian(r_path, font_size_pt=9, bold=False, color_rgb=(110, 120, 115))

        # Embed visual preview of the image
        png_stream = _prepare_normalized_png_stream(item.image_path)
        if png_stream is not None:
            pic_p = doc.add_paragraph()
            pic_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            pic_run = pic_p.add_run()
            pic_run.add_picture(png_stream, width=Inches(3.4))

        # Per-Image Structured Metadata Table (keeps 1 table per image so total tables == 2 + len(analyses))
        meta_table = doc.add_table(rows=0, cols=2)
        meta_table.style = "Table Grid"
        _set_table_rtl(meta_table)

        conf_text = (
            f"{item.ocr_confidence:.1f}٪ ({item.word_count} کلمه در {item.line_count} سطر)"
            if item.ocr_confidence is not None and item.word_count > 0
            else (f"{item.word_count} کلمه" if item.word_count > 0 else "بدون متن چاپی (تصویر بصری)")
        )
        loc_and_gps_val = (
            f"{location_name} · مختصات جغرافیایی (GPS): {gps_coords}"
            if gps_coords
            else location_name
        )

        identity_summary_parts: List[str] = []
        if pid.get("full_name"):
            identity_summary_parts.append(f"نام و نام خانوادگی: {pid['full_name']}")
        if pid.get("father_name"):
            identity_summary_parts.append(f"نام پدر: {pid['father_name']}")
        if pid.get("national_id"):
            identity_summary_parts.append(f"کد ملی: {pid['national_id']}")
        if pid.get("birth_certificate_no"):
            identity_summary_parts.append(f"شماره شناسنامه: {pid['birth_certificate_no']}")
        if pid.get("birth_date"):
            identity_summary_parts.append(f"تاریخ تولد: {pid['birth_date']}")
        if pid.get("occupation"):
            identity_summary_parts.append(f"شغل: {pid['occupation']}")
        identity_row_val = " | ".join(identity_summary_parts) if identity_summary_parts else "ثبت‌نشده در تصویر"

        contact_summary_parts: List[str] = []
        if pid.get("mobile_phone"):
            contact_summary_parts.append(f"شماره موبایل / تلفن همراه: {pid['mobile_phone']}")
        if pid.get("secondary_mobile"):
            contact_summary_parts.append(f"تلفن همراه دوم: {pid['secondary_mobile']}")
        if pid.get("landline_phone"):
            contact_summary_parts.append(f"تلفن ثابت: {pid['landline_phone']}")
        if pid.get("address"):
            contact_summary_parts.append(f"آدرس: {pid['address']}")
        if pid.get("postal_code"):
            contact_summary_parts.append(f"کد پستی: {pid['postal_code']}")
        contact_row_val = " | ".join(contact_summary_parts) if contact_summary_parts else "ثبت‌نشده در تصویر"

        crim_charges_val = (
            " ؛ ".join(crim.get("criminal_charges", []))
            if crim.get("criminal_charges")
            else "فاقد مصداق مجرمانهٔ آشکار در متن"
        )
        crim_articles_val = (
            " ؛ ".join(crim.get("legal_articles", []))
            if crim.get("legal_articles")
            else "—"
        )

        spec_rows = [
            ("اولویت اول دسته‌بندی (نام کاربری و آیدی)", acc_label),
            ("پوشهٔ شخصی تخصیص‌یافته", personal_folder),
            ("اولویت دوم دسته‌بندی (۱۲ سرفصل موضوعی)", cat_label),
            ("دسته‌بندی نوع عکس (اسکرین‌شات / عکس با دوربین / سوژه)", capture_source),
            ("دسته‌بندی بر اساس سوژه و شناسه روی عکس", subject_cls),
            ("موقعیت مکانی و مختصات جغرافیایی", loc_and_gps_val),
            ("بستر / منبع تصویر و مشخصات دوربین", f"{platform_src} · {camera_info}"),
            ("ماهیت بصری تصویر", item.image_nature),
            ("ابعاد و جهت کادر", f"{item.width}×{item.height} پیکسل · {item.orientation} (نسبت {item.aspect_ratio})"),
            ("پروفایل رنگی و روشنایی", f"{item.color_profile_label} · رنگ غالب {item.dominant_color_hex}"),
            ("وضعیت نوشتار و دقت تشخیص متن (OCR)", conf_text),
            ("مشخصات انفرادی و شناسنامه‌ای مستخرج", identity_row_val),
            ("شماره موبایل، تلفن همراه و آدرس", contact_row_val),
            ("سطح ریسک و بررسی موارد مجرمانه", crim.get("risk_level", "عادی")),
            ("عناوین اتهامی و مواد قانونی منطبق", f"{crim_charges_val} ({crim_articles_val})"),
            ("برچسب‌ها و کلیدواژه‌ها", " ، ".join(item.tags) if item.tags else cat_label),
        ]
        for label, val in spec_rows:
            r_cells = meta_table.add_row().cells
            _set_cell_text(r_cells[0], label, bold=True, font_size_pt=10, color_rgb=(31, 92, 74))
            _set_cell_text(r_cells[1], val, bold=False, font_size_pt=10)

        # Narrative Analysis Section
        ana_h = doc.add_paragraph()
        _set_rtl_paragraph(ana_h)
        r_ah = ana_h.add_run("شرح تحلیل ماهیت، موضوع و موقعیت این عکس:")
        _style_run_persian(r_ah, font_size_pt=12, bold=True, color_rgb=(25, 33, 30))

        ana_p = doc.add_paragraph()
        _set_rtl_paragraph(ana_p)
        r_ap = ana_p.add_run(item.analysis_summary)
        _style_run_persian(r_ap, font_size_pt=11, bold=False, color_rgb=(35, 45, 42))

        # Legal & Judicial Criminal Assessment Section
        jud_h = doc.add_paragraph()
        _set_rtl_paragraph(jud_h)
        r_jh = jud_h.add_run("تحلیل دقیق عنوان و نوشتهٔ عکس و بررسی موارد مجرمانه (بر اساس داده‌های حقوقی و قضایی):")
        _style_run_persian(r_jh, font_size_pt=12, bold=True, color_rgb=(140, 35, 35) if crim.get("has_criminal_indicator") else (31, 92, 74))

        jud_p = doc.add_paragraph()
        _set_rtl_paragraph(jud_p)
        jud_lines = [
            f"• واکاوی دقیق عنوان و متن: {crim.get('exact_text_inspection', getattr(item, 'detected_caption', item.title))}",
            f"• سطح ریسک قضایی: {crim.get('risk_level', 'عادی')}",
            f"• عناوین مجرمانهٔ احرازشده: {crim_charges_val}",
            f"• مواد قانونی مستند (قانون جرایم رایانه‌ای / قانون مجازات اسلامی): {crim_articles_val}",
            f"• نظریهٔ کارشناسی حقوقی و قضایی: {crim.get('judicial_summary', '')}",
            f"• اقدام پیشنهادی قضایی و ضابطین: {crim.get('recommended_action', '')}",
        ]
        for eq in crim.get("evidence_quotes") or []:
            jud_lines.append(f"• قرینهٔ مستند روی تصویر: {eq}")
        r_jp = jud_p.add_run("\n".join(jud_lines))
        _style_run_persian(r_jp, font_size_pt=10, bold=False, color_rgb=(40, 48, 45))

        # Cultural & Social Structured Report Template (قواره ویژه دسته‌بندی فرهنگی و اجتماعی)
        if getattr(item, "template_applicable", False) and getattr(item, "formatted_template_text", ""):
            tpl_h = doc.add_paragraph()
            _set_rtl_paragraph(tpl_h)
            r_th = tpl_h.add_run(f"قوارهٔ تکمیل‌شده ویژهٔ دسته‌بندی {cat_label}:")
            _style_run_persian(r_th, font_size_pt=12, bold=True, color_rgb=(31, 92, 74))

            for tpl_line in item.formatted_template_text.splitlines():
                tp = doc.add_paragraph()
                _set_rtl_paragraph(tp)
                tp.paragraph_format.space_after = Pt(2)
                is_url = tpl_line.strip().lower().startswith("http")
                is_tag = tpl_line.strip().startswith("#")
                r_tl = tp.add_run(tpl_line)
                _style_run_persian(
                    r_tl,
                    font_size_pt=11,
                    bold=is_tag or tpl_line.strip().startswith(("تخلف:", "درخواست")),
                    color_rgb=(20, 75, 130) if is_url else ((31, 92, 74) if is_tag else (25, 33, 30)),
                )

        if item.key_findings:
            kf_h = doc.add_paragraph()
            _set_rtl_paragraph(kf_h)
            r_kfh = kf_h.add_run("یافته‌های کلیدی تصویر:")
            _style_run_persian(r_kfh, font_size_pt=11, bold=True, color_rgb=(45, 58, 54))

            for finding in item.key_findings:
                fp = doc.add_paragraph()
                _set_rtl_paragraph(fp)
                rf = fp.add_run(f"• {finding}")
                _style_run_persian(rf, font_size_pt=10, bold=False, color_rgb=(50, 62, 58))

        # Extracted OCR Text Section
        ocr_h = doc.add_paragraph()
        _set_rtl_paragraph(ocr_h)
        r_oh = ocr_h.add_run("متن کامل استخراج‌شده از داخل تصویر (دقیقاً هر آنچه نوشته شده - OCR):")
        _style_run_persian(r_oh, font_size_pt=11, bold=True, color_rgb=(25, 33, 30))

        ocr_p = doc.add_paragraph()
        _set_rtl_paragraph(ocr_p)
        ocr_body = (
            item.extracted_text.strip()
            if item.extracted_text and item.extracted_text.strip()
            else "متن چاپی قابل استخراجی در این تصویر وجود ندارد."
        )
        r_op = ocr_p.add_run(ocr_body)
        _style_run_persian(r_op, font_size_pt=10, bold=False, color_rgb=(60, 72, 68))

    out_buf = io.BytesIO()
    doc.save(out_buf)
    return out_buf.getvalue()


def generate_identity_profiles_docx(
    profiles: List[Dict[str, Any]],
    report_title: str = "گزارش جامع مشخصات انفرادی، شناسنامه‌ای، شماره موبایل و آدرس",
) -> bytes:
    """
    Generates an RTL Persian Word (.docx) document for the Personal & Civil Identity Dossiers page
    (صفحهٔ مشخصات انفرادی و شناسنامه‌ای و شماره موبایل و آدرس و تلفن همراه).
    """
    doc = Document()

    title_p = doc.add_paragraph()
    _set_rtl_paragraph(title_p)
    r_title = title_p.add_run(report_title)
    _style_run_persian(r_title, font_size_pt=16, bold=True, color_rgb=(31, 92, 74))

    sub_p = doc.add_paragraph()
    _set_rtl_paragraph(sub_p)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    r_sub = sub_p.add_run(
        f"سامانهٔ بایگانی و تحلیل آفلاین ساهر · تعداد پرونده‌های انفرادی: {len(profiles)} پرونده · تاریخ صدور: {now_str}"
    )
    _style_run_persian(r_sub, font_size_pt=10, bold=False, color_rgb=(95, 108, 103))

    if profiles:
        overview_table = doc.add_table(rows=1, cols=8)
        overview_table.style = "Table Grid"
        _set_table_rtl(overview_table)
        headers = [
            "ردیف",
            "نام و نام خانوادگی",
            "نام پدر",
            "کد ملی / ش.شناسنامه",
            "شماره موبایل / تلفن همراه",
            "تلفن ثابت",
            "شهر / آدرس محل سکونت",
            "آیدی فضای مجازی و سرفصل",
        ]
        for i, h_text in enumerate(headers):
            _set_cell_text(overview_table.rows[0].cells[i], h_text, bold=True, font_size_pt=9, color_rgb=(31, 92, 74))

        for idx, prof in enumerate(profiles, start=1):
            rc = overview_table.add_row().cells
            full_n = prof.get("full_name") or f"{prof.get('first_name', '')} {prof.get('last_name', '')}".strip() or "ثبت‌نشده"
            nid_sh = " / ".join(filter(None, [prof.get("national_id"), prof.get("birth_certificate_no")])) or "—"
            mob_str = " / ".join(filter(None, [prof.get("mobile_phone"), prof.get("secondary_mobile")])) or "—"
            addr_str = " ، ".join(filter(None, [prof.get("province"), prof.get("city"), prof.get("address")])) or "—"
            handle_cat = " · ".join(filter(None, [prof.get("account_handle"), prof.get("thematic_category")])) or "—"

            _set_cell_text(rc[0], str(idx), font_size_pt=9)
            _set_cell_text(rc[1], full_n, bold=True, font_size_pt=9)
            _set_cell_text(rc[2], prof.get("father_name") or "—", font_size_pt=9)
            _set_cell_text(rc[3], nid_sh, font_size_pt=9)
            _set_cell_text(rc[4], mob_str, bold=True, font_size_pt=9)
            _set_cell_text(rc[5], prof.get("landline_phone") or "—", font_size_pt=9)
            _set_cell_text(rc[6], addr_str, font_size_pt=9)
            _set_cell_text(rc[7], handle_cat, font_size_pt=9)

    for idx, prof in enumerate(profiles, start=1):
        doc.add_paragraph()
        full_n = prof.get("full_name") or f"{prof.get('first_name', '')} {prof.get('last_name', '')}".strip() or "فرد بدون نام ثبت‌شده"
        sec_p = doc.add_paragraph()
        _set_rtl_paragraph(sec_p)
        r_sp = sec_p.add_run(f"پروندهٔ انفرادی شمارهٔ {idx}: {full_n}")
        _style_run_persian(r_sp, font_size_pt=14, bold=True, color_rgb=(31, 92, 74))

        d_table = doc.add_table(rows=0, cols=2)
        d_table.style = "Table Grid"
        _set_table_rtl(d_table)

        rows_data = [
            ("نام و نام خانوادگی", full_n),
            ("نام", prof.get("first_name") or "—"),
            ("نام خانوادگی", prof.get("last_name") or "—"),
            ("نام پدر", prof.get("father_name") or "—"),
            ("کد ملی", prof.get("national_id") or "—"),
            ("شماره شناسنامه", prof.get("birth_certificate_no") or "—"),
            ("تاریخ تولد", prof.get("birth_date") or "—"),
            ("محل تولد / صدور", prof.get("birth_place") or "—"),
            ("شغل و حرفه", prof.get("occupation") or "—"),
            ("شماره موبایل (تلفن همراه اول)", prof.get("mobile_phone") or "—"),
            ("شماره تلفن همراه دوم / شماره حساب", prof.get("secondary_mobile") or "—"),
            ("شماره تلفن ثابت", prof.get("landline_phone") or "—"),
            ("استان و شهرستان", " ، ".join(filter(None, [prof.get("province"), prof.get("city")])) or "—"),
            ("آدرس کامل محل سکونت / فعالیت", prof.get("address") or "—"),
            ("کد پستی", prof.get("postal_code") or "—"),
            ("مختصات جغرافیایی (GPS)", prof.get("gps_coordinates") or "—"),
            ("شناسه آی‌دی فضای مجازی و آیدی عددی", " | ".join(filter(None, [prof.get("account_handle"), prof.get("numeric_id")])) or "—"),
            ("لینک صفحه / آدرس اینترنتی", prof.get("profile_url") or "—"),
            ("پوشهٔ شخصی و سرفصل موضوعی ۱۲گانه", f"{prof.get('personal_folder') or '—'} · {prof.get('thematic_category') or 'اجتماعی'}"),
            ("سطح ریسک و سوابق/موارد اتهامی حقوقی و قضایی", prof.get("judicial_notes") or prof.get("risk_level") or "—"),
        ]
        for k_lbl, v_txt in rows_data:
            c = d_table.add_row().cells
            _set_cell_text(c[0], k_lbl, bold=True, font_size_pt=10, color_rgb=(31, 92, 74))
            _set_cell_text(c[1], str(v_txt), bold=False, font_size_pt=10)

    out_buf = io.BytesIO()
    doc.save(out_buf)
    return out_buf.getvalue()


