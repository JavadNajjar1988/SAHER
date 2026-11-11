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
    size_cs = OxmlElement("w:szCs")
    size_cs.set(qn("w:val"), str(font_size_pt * 2))
    rPr.append(size_cs)
    bold_cs = OxmlElement("w:bCs")
    bold_cs.set(qn("w:val"), "1" if bold else "0")
    rPr.append(bold_cs)
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
    Generates a comprehensive, RTL-formatted Microsoft Word (.docx) document containing:
    1. Executive summary of the two-level classification:
       - Priority 1 (اولویت اول): دسته‌بندی بر اساس نام کاربری و آیدی (Username & Account ID)
       - Priority 2 (اولویت دوم): دسته‌بندی بر اساس ۱۲ سرفصل موضوعی مشخص‌شده
         (اجتماعی، اقتصادی، امنیتی، جاسوسی، دفاعی (نظامی، کویر و مرز)، دین و روحانیت،
          رزمایش، سایبری، سیاسی، علم و فناوری، فرهنگی، هواگرد (پهپاد، ریزپرنده، جنگنده و ...))
    2. A separate, dedicated analysis section for EACH individual screenshot/image, including:
       - Embedded thumbnail preview of the image
       - Structured specification table (نام کاربری و آیدی، سرفصل موضوعی ۱۲گانه، ماهیت بصری، پلتفرم، ابعاد، وضعیت OCR، برچسب‌ها)
       - Detailed analytical explanation (شرح ماهیت و موضوع عکس)
       - Cultural & Social Structured Template (قواره ویژه فرهنگی و اجتماعی) when applicable
       - Extracted OCR text from inside the image
    """
    doc = Document()

    # 1. Cover / Report Header
    title_p = doc.add_paragraph()
    _set_rtl_paragraph(title_p)
    title_run = title_p.add_run(
        "گزارش تحلیل هوشمند پوشهٔ عکس‌ها و اسکرین‌شات‌ها (بر اساس نام کاربری/آیدی و ۱۲ سرفصل موضوعی)"
    )
    _style_run_persian(title_run, font_size_pt=17, bold=True, color_rgb=(31, 92, 74))

    subtitle_p = doc.add_paragraph()
    _set_rtl_paragraph(subtitle_p)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    sub_run = subtitle_p.add_run(
        f"سامانهٔ بایگانی و تحلیل آفلاین ساهر · نام مجموعه/پوشه: {folder_name or 'پوشهٔ تصاویر'} · "
        f"تعداد تصاویر تحلیل‌شده: {len(analyses)} تصویر · تاریخ تولید گزارش: {now_str}"
    )
    _style_run_persian(sub_run, font_size_pt=10, bold=False, color_rgb=(95, 108, 103))

    # 2. Two-Level Summary Breakdown: Priority 1 (Username & ID) -> Priority 2 (12 Thematic Categories)
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

        for item in analyses:
            acc = getattr(item, "account_label", None) or "بدون نام کاربری / آیدی مشخص"
            cat = getattr(item, "thematic_category", None) or item.detected_topic
            account_counts[acc] = account_counts.get(acc, 0) + 1
            if acc not in account_tree:
                account_tree[acc] = {}
            account_tree[acc][cat] = account_tree[acc].get(cat, 0) + 1
            topic_counts[cat] = topic_counts.get(cat, 0) + 1
            nature_counts[item.image_nature] = nature_counts.get(item.image_nature, 0) + 1

        sec_h = doc.add_paragraph()
        _set_rtl_paragraph(sec_h)
        r_sh = sec_h.add_run("۱. خلاصهٔ دسته‌بندی دومرحله‌ای (اولویت اول: نام کاربری و آیدی ← اولویت دوم: ۱۲ سرفصل موضوعی)")
        _style_run_persian(r_sh, font_size_pt=14, bold=True, color_rgb=(25, 33, 30))

        dist_p = doc.add_paragraph()
        _set_rtl_paragraph(dist_p)
        accounts_summary = " ، ".join(f"{k}: {v} مورد" for k, v in account_counts.items())
        topics_summary = " ، ".join(f"{k}: {v} مورد" for k, v in topic_counts.items())
        natures_summary = " ، ".join(f"{k}: {v} مورد" for k, v in nature_counts.items())
        r_dist = dist_p.add_run(
            f"• اولویت اول — تفکیک بر اساس نام کاربری و آیدی: {accounts_summary}\n"
            f"• اولویت دوم — تفکیک بر اساس ۱۲ سرفصل موضوعی: {topics_summary}\n"
            f"• تفکیک ماهیت بصری تصاویر: {natures_summary}"
        )
        _style_run_persian(r_dist, font_size_pt=10, bold=False, color_rgb=(45, 55, 52))

        # Hierarchical Priority-1 -> Priority-2 Matrix Table
        tree_h = doc.add_paragraph()
        _set_rtl_paragraph(tree_h)
        r_th = tree_h.add_run("جدول تفکیک اولویت اول (نام کاربری و آیدی) و زیرشاخه‌های موضوعی (اولویت دوم):")
        _style_run_persian(r_th, font_size_pt=11, bold=True, color_rgb=(31, 92, 74))

        tree_table = doc.add_table(rows=1, cols=3)
        tree_table.style = "Table Grid"
        _set_table_rtl(tree_table)
        t_headers = ["نام کاربری و آیدی (اولویت اول)", "تعداد کل اسکرین‌شات‌ها", "تفکیک در ۱۲ دسته‌بندی موضوعی (اولویت دوم)"]
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
        summary_table = doc.add_table(rows=1, cols=7)
        summary_table.style = "Table Grid"
        _set_table_rtl(summary_table)
        headers = [
            "ردیف",
            "نام کاربری و آیدی (اولویت ۱)",
            "دسته‌بندی موضوعی (اولویت ۲)",
            "نام تصویر / مسیر",
            "ماهیت بصری تصویر",
            "ابعاد (پیکسل)",
            "کلمات استخراج‌شده",
        ]
        hdr_cells = summary_table.rows[0].cells
        for i, h_text in enumerate(headers):
            _set_cell_text(hdr_cells[i], h_text, bold=True, font_size_pt=9, color_rgb=(31, 92, 74))

        for idx, item in enumerate(analyses, start=1):
            row_cells = summary_table.add_row().cells
            acc = getattr(item, "account_label", None) or "بدون نام کاربری / آیدی مشخص"
            cat = getattr(item, "thematic_category", None) or item.detected_topic
            _set_cell_text(row_cells[0], str(idx), font_size_pt=9)
            _set_cell_text(row_cells[1], acc, bold=True, font_size_pt=9)
            _set_cell_text(row_cells[2], cat, bold=True, font_size_pt=9)
            _set_cell_text(row_cells[3], item.relative_path or item.title, font_size_pt=9)
            _set_cell_text(row_cells[4], item.image_nature, font_size_pt=9)
            _set_cell_text(row_cells[5], f"{item.width}×{item.height}", font_size_pt=9)
            _set_cell_text(row_cells[6], f"{item.word_count} کلمه", font_size_pt=9)

    # 3. Separate Per-Image Analysis Sections
    for idx, item in enumerate(analyses, start=1):
        if idx > 1 or len(analyses) > 1:
            doc.add_page_break()

        acc_label = getattr(item, "account_label", None) or "بدون نام کاربری / آیدی مشخص"
        cat_label = getattr(item, "thematic_category", None) or item.detected_topic
        platform_src = getattr(item, "platform_source", None) or "اسکرین‌شات / تصویر عمومی"

        img_h = doc.add_paragraph()
        _set_rtl_paragraph(img_h)
        r_ih = img_h.add_run(f"تصویر شمارهٔ {idx}: {item.title}")
        _style_run_persian(r_ih, font_size_pt=15, bold=True, color_rgb=(31, 92, 74))

        hier_p = doc.add_paragraph()
        _set_rtl_paragraph(hier_p)
        r_hp = hier_p.add_run(
            f"اولویت ۱ (نام کاربری و آیدی): {acc_label}   |   اولویت ۲ (سرفصل موضوعی): {cat_label}"
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

        # Per-Image Structured Metadata Table
        meta_table = doc.add_table(rows=0, cols=2)
        meta_table.style = "Table Grid"
        _set_table_rtl(meta_table)

        conf_text = (
            f"{item.ocr_confidence:.1f}٪ ({item.word_count} کلمه در {item.line_count} سطر)"
            if item.ocr_confidence is not None and item.word_count > 0
            else (f"{item.word_count} کلمه" if item.word_count > 0 else "بدون متن چاپی (تصویر بصری)")
        )
        spec_rows = [
            ("اولویت اول دسته‌بندی (نام کاربری و آیدی)", acc_label),
            ("اولویت دوم دسته‌بندی (۱۲ سرفصل موضوعی)", cat_label),
            ("بستر / منبع اسکرین‌شات", platform_src),
            ("ماهیت تصویر (Image Nature)", item.image_nature),
            ("ابعاد و جهت کادر", f"{item.width}×{item.height} پیکسل · {item.orientation} (نسبت {item.aspect_ratio})"),
            ("پروفایل رنگی و روشنایی", f"{item.color_profile_label} · رنگ غالب {item.dominant_color_hex}"),
            ("وضعیت نوشتار و دقت OCR", conf_text),
            ("برچسب‌ها و کلیدواژه‌ها", " ، ".join(item.tags) if item.tags else cat_label),
        ]
        for label, val in spec_rows:
            r_cells = meta_table.add_row().cells
            _set_cell_text(r_cells[0], label, bold=True, font_size_pt=10, color_rgb=(31, 92, 74))
            _set_cell_text(r_cells[1], val, bold=False, font_size_pt=10)

        # Narrative Analysis Section
        ana_h = doc.add_paragraph()
        _set_rtl_paragraph(ana_h)
        r_ah = ana_h.add_run("شرح تحلیل ماهیت و موضوع این عکس:")
        _style_run_persian(r_ah, font_size_pt=12, bold=True, color_rgb=(25, 33, 30))

        ana_p = doc.add_paragraph()
        _set_rtl_paragraph(ana_p)
        r_ap = ana_p.add_run(item.analysis_summary)
        _style_run_persian(r_ap, font_size_pt=11, bold=False, color_rgb=(35, 45, 42))

        # Cultural & Social Structured Report Template (قواره ویژه دسته‌بندی فرهنگی و اجتماعی)
        # Strictly rendered ONLY when thematic_category is «فرهنگی» or «اجتماعی»
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
        r_oh = ocr_h.add_run("متن استخراج‌شده از داخل تصویر (OCR):")
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


