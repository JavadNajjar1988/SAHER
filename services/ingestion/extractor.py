import os
from typing import Tuple

def extract_text_from_file(file_path: str, mime_type: str) -> Tuple[str, int, str]:
    """
    Extracts text from supported document types (PDF, DOCX, TXT, MD, CSV, JSON).
    Returns (extracted_text, page_count, extraction_method).
    """
    if not os.path.exists(file_path):
        return "", 0, "none"
        
    ext = os.path.splitext(file_path)[1].lower()
    
    # 1. Plain text formats
    if ext in [".txt", ".md", ".json", ".csv", ".log", ".yaml", ".yml", ".py", ".ts", ".js", ".html"]:
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
            return text, 1, "direct"
        except Exception as e:
            return f"خطا در خواندن فایل متنی: {str(e)}", 1, "error"
            
    # 2. PDF extraction
    if ext == ".pdf" or mime_type == "application/pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(file_path)
            num_pages = len(reader.pages)
            extracted = []
            for i, page in enumerate(reader.pages):
                page_text = page.extract_text() or ""
                if page_text.strip():
                    extracted.append(page_text.strip())
            
            full_text = "\n\n".join(extracted)
            if full_text.strip():
                return full_text, max(1, num_pages), "direct_pdf"
            else:
                return "سند PDF اسکن‌شده یا بدون لایهٔ متنی است. برای استخراج کامل متن نیاز به پردازش OCR آفلاین دارد.", max(1, num_pages), "pdf_needs_ocr"
        except Exception as e:
            return f"خطا در پردازش PDF: {str(e)}", 1, "error"
            
    # 3. Word DOCX
    if ext == ".docx" or mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        try:
            import docx
            doc = docx.Document(file_path)
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            return "\n\n".join(paragraphs), 1, "direct_docx"
        except Exception as e:
            return f"خطا در پردازش DOCX: {str(e)}", 1, "error"
            
    # 4. Images
    if ext in [".png", ".jpg", ".jpeg", ".webp", ".svg", ".bmp"] or mime_type.startswith("image/"):
        return "فایل تصویری دریافت شد. این تصویر برای تحلیل دیداری، توصیف خودکار فضا و استخراج متن اسکن‌شده آماده است.", 1, "image_pending_ocr"
        
    return "فرمت فایل برای استخراج مستقیم متن پشتیبانی نمی‌شود.", 1, "unsupported"
