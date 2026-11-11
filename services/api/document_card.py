"""General archive metadata: document descriptions, never identity profiles."""
import json
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator
from uuid import uuid4
from PIL import Image

from services.api.database import get_db
from services.api.repository import ArchiveRepository


class DocumentEvidence(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()), max_length=100)
    quote: str = Field(min_length=1, max_length=5000)
    page_number: int = Field(ge=1)
    source_reference: str = Field(default="", max_length=2000)
    review_status: Literal["pending", "confirmed", "rejected"] = "pending"
    reviewer_note: str = Field(default="", max_length=2000)

    @field_validator("quote")
    @classmethod
    def quote_not_blank(cls, value):
        if not value.strip():
            raise ValueError("نقل‌قول نمی‌تواند خالی باشد.")
        return value


class DocumentCard(BaseModel):
    folder_path: str = Field(default="", max_length=500)
    subject: str = Field(default="", max_length=500)
    media_kind: Literal["نامشخص", "اسکرین‌شات", "عکس دوربین", "سند اسکن‌شده", "تصویر گرافیکی", "سند متنی"] = "نامشخص"
    location_label: str = Field(default="", max_length=300)
    source_reference: str = Field(default="", max_length=2000)
    notes: str = Field(default="", max_length=20000)
    evidence: list[DocumentEvidence] = Field(default_factory=list, max_length=100)


def get_card(file_id: str) -> dict:
    item = ArchiveRepository.get_file(file_id)
    if not item:
        raise HTTPException(404, "سند در آرشیو یافت نشد.")
    with get_db() as conn:
        row = conn.execute("SELECT card_json FROM files WHERE id = ?", (file_id,)).fetchone()
    card = DocumentCard.model_validate_json(row["card_json"] or "{}").model_dump()
    pages = {p.page_number: p.raw_text for p in ArchiveRepository.get_file_pages(file_id)} if card["evidence"] else {}
    for entry in card["evidence"]:
        # Matching is exact, and independent of the human review status.
        entry["quote_matches_page"] = entry["quote"] in pages.get(entry["page_number"], "")
    detected = "سند متنی" if not item.mime_type.startswith("image/") else "نامشخص"
    evidence = "نوع سند بر اساس قالب فایل" if detected == "سند متنی" else "برای تعیین نوع تصویر، بازبینی لازم است."
    width = height = None
    info = ArchiveRepository.get_file_storage_path(file_id)
    if info and item.mime_type.startswith("image/"):
        try:
            with Image.open(info[0]) as image:
                exif = image.getexif()
                width, height = image.size
                if exif.get(274) in (5, 6, 7, 8):
                    width, height = height, width
                if exif.get(271) or exif.get(272):
                    detected, evidence = "عکس دوربین", "فرادادهٔ سازنده یا مدل دوربین در فایل موجود است."
                elif any(word in item.title.lower() for word in ("screenshot", "screen shot", "اسکرین", "نماگرفت")):
                    detected, evidence = "اسکرین‌شات", "نام فایل نشان‌دهندهٔ نماگرفت است؛ نیازمند تأیید کاربر."
        except (OSError, ValueError):
            evidence = "خواندن فرادادهٔ تصویر ممکن نبود."
    return {**card, "detected_media_kind": detected, "detection_evidence": evidence,
            "width": width, "height": height}


def save_card(file_id: str, card: DocumentCard) -> dict:
    if len({entry.id for entry in card.evidence}) != len(card.evidence):
        raise HTTPException(422, "شناسهٔ شواهد باید یکتا باشد.")
    if card.evidence:
        page_numbers = {p.page_number for p in ArchiveRepository.get_file_pages(file_id)}
        if any(entry.page_number not in page_numbers for entry in card.evidence):
            raise HTTPException(422, "صفحهٔ مرجع شاهد در این سند یافت نشد؛ ابتدا استخراج صفحات را تکمیل کنید.")
    with get_db() as conn:
        existing = conn.execute("SELECT card_json FROM files WHERE id = ?", (file_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "سند در آرشیو یافت نشد.")
        data = card.model_dump()
        # Older clients do not send evidence; preserve it unless explicitly supplied.
        if "evidence" not in card.model_fields_set:
            data["evidence"] = json.loads(existing["card_json"] or "{}").get("evidence", [])
        changed = conn.execute(
            "UPDATE files SET card_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(data, ensure_ascii=False), file_id),
        ).rowcount
        if not changed:
            raise HTTPException(404, "سند در آرشیو یافت نشد.")
    return get_card(file_id)


def list_collections(limit: int = 100, offset: int = 0) -> dict:
    with get_db() as conn:
        counts = conn.execute("""SELECT COUNT(*) AS documents,
            COUNT(DISTINCT COALESCE(NULLIF(TRIM(json_extract(card_json, '$.folder_path')), ''), '')) AS collections
            FROM files WHERE archive_id = 'default'""").fetchone()
        rows = conn.execute("""SELECT
            COALESCE(NULLIF(TRIM(json_extract(card_json, '$.folder_path')), ''), '') AS folder_path,
            COUNT(*) AS document_count,
            COUNT(DISTINCT NULLIF(TRIM(json_extract(card_json, '$.source_reference')), '')) AS source_count
            FROM files WHERE archive_id = 'default' GROUP BY 1 ORDER BY document_count DESC, folder_path
            LIMIT ? OFFSET ?""", (limit, offset)).fetchall()
    return {"total_documents": counts["documents"], "total_collections": counts["collections"],
            "items": [dict(row) for row in rows], "limit": limit, "offset": offset}
