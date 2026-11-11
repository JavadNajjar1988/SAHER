"""Lossless text export of a general archive document to Persian Word."""
import io
import re
from datetime import datetime, timezone, timedelta

from docx import Document
from docx.shared import Cm, Pt
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from services.analysis.word_exporter import _set_rtl_paragraph, _style_run_persian, _set_table_rtl, _set_cell_text


def _xml_text(value):
    # XML 1.0 excludes control characters even when a source text file contains them.
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]", "", str(value))


def _fa_digits(value):
    return str(value).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def generate_document_docx(item, pages, card):
    doc = Document()
    section = doc.sections[0]
    section.top_margin = section.bottom_margin = Cm(2)
    section.left_margin = section.right_margin = Cm(2)
    normal = doc.styles["Normal"]
    normal.font.name = "Vazirmatn"
    normal.font.size = Pt(11)

    def paragraph(text, bold=False, size=11):
        p = doc.add_paragraph()
        _set_rtl_paragraph(p)
        p.paragraph_format.space_after = Pt(6)
        _style_run_persian(p.add_run(_xml_text(text)), font_size_pt=size, bold=bold)
        return p

    paragraph("شناسنامه و متن سند آرشیوی", True, 18)
    paragraph(item.title, True, 14)
    tehran = timezone(timedelta(hours=3, minutes=30))
    paragraph("تاریخ تهیه (میلادی، به وقت تهران): " + _fa_digits(datetime.now(tehran).strftime("%Y/%m/%d %H:%M")), size=9)
    table = doc.add_table(rows=0, cols=2)
    table.style = "Table Grid"
    _set_table_rtl(table)
    fields = [("شناسهٔ سند", item.id), ("موضوع", item.topic), ("پوشه", card["folder_path"]),
              ("شرح سوژهٔ سند", card["subject"]),
              ("نوع فایل", card["media_kind"] if card["media_kind"] != "نامشخص" else card["detected_media_kind"]),
              ("مبنای پیشنهاد نوع", card["detection_evidence"]),
              ("برچسب مکان سند (ثبت کاربر)", card["location_label"]), ("مرجع منبع", card["source_reference"]),
              ("برچسب‌ها", "، ".join(item.tags)), ("اثر انگشت SHA-256", item.sha256)]
    for label, value in fields:
        cells = table.add_row().cells
        _set_cell_text(cells[0], label, bold=True)
        _set_cell_text(cells[1], _xml_text(value or "ثبت نشده"))
    if card["notes"]:
        paragraph("یادداشت ثبت‌شده توسط کاربر", True)
        paragraph(card["notes"])
    paragraph("شواهد مستند", True, 14)
    evidence = card.get("evidence", [])
    if not evidence:
        paragraph("شاهدی برای این سند ثبت نشده است.")
    review_labels = {"pending": "نیازمند بازبینی", "confirmed": "تأییدشده توسط بازبین", "rejected": "ردشده توسط بازبین"}
    sources = {}
    if card["source_reference"].strip():
        sources[card["source_reference"].strip()] = 0
    for index, entry in enumerate(evidence, 1):
        paragraph(f"شاهد {_fa_digits(index)} · صفحهٔ {_fa_digits(entry['page_number'])}", True)
        paragraph(entry["quote"])
        source = entry["source_reference"].strip() or card["source_reference"].strip() or "منبع ثبت نشده"
        sources[source] = sources.get(source, 0) + 1
        paragraph("منبع: " + source, size=9)
        paragraph("وضعیت بازبینی: " + review_labels[entry["review_status"]], size=9)
        matching = any(p.page_number == entry["page_number"] and entry["quote"] in p.raw_text for p in pages)
        paragraph("تطابق متن: " + ("تطابق دقیق با متن ذخیره‌شدهٔ صفحه" if matching else "نیازمند تطبیق با اصل صفحه"), size=9)
        if entry["reviewer_note"]:
            paragraph("یادداشت بازبین: " + entry["reviewer_note"])
    paragraph("مجموعه و منابع سند", True, 14)
    paragraph("مجموعه: " + (card["folder_path"] or "بدون پوشه"))
    for source, count in sources.items():
        paragraph(f"{source} · {_fa_digits(count)} شاهد")
    if not sources:
        paragraph("منبعی ثبت نشده است.")
    paragraph("متن زیر خروجی استخراج یا اصلاح دستی است؛ تطبیق نهایی با اصل سند لازم است.", size=9)
    if not pages:
        paragraph(item.text or "هنوز متنی برای این سند استخراج نشده است.")
    for page in pages:
        doc.add_page_break()
        paragraph(f"صفحهٔ {_fa_digits(page.page_number)} از سند اصلی", True, 14)
        status = "اصلاح دستی کاربر" if page.is_user_modified else "متن استخراج‌شده"
        if page.ocr_confidence is not None:
            status += f" · اطمینان تشخیص متن: {_fa_digits(f'{page.ocr_confidence:.1f}')}٪"
        paragraph(status, size=9)
        if page.error_message:
            paragraph("خطای صفحه: " + page.error_message, size=9)
        # Do not normalize, truncate or summarize source text.
        for line in (page.raw_text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            paragraph(line)
    footer = section.footer.paragraphs[0]
    _set_rtl_paragraph(footer)
    _style_run_persian(footer.add_run("ساهر · صفحهٔ "), font_size_pt=9)
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    footer._p.append(field)
    result = io.BytesIO()
    doc.save(result)
    return result.getvalue()
