"""General archive metadata: document descriptions, never identity profiles."""
import json
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field
from PIL import Image

from services.api.database import get_db
from services.api.repository import ArchiveRepository


class DocumentCard(BaseModel):
    folder_path: str = Field(default="", max_length=500)
    subject: str = Field(default="", max_length=500)
    media_kind: Literal["نامشخص", "اسکرین‌شات", "عکس دوربین", "سند اسکن‌شده", "تصویر گرافیکی", "سند متنی"] = "نامشخص"
    location_label: str = Field(default="", max_length=300)
    source_reference: str = Field(default="", max_length=2000)
    notes: str = Field(default="", max_length=20000)


def get_card(file_id: str) -> dict:
    item = ArchiveRepository.get_file(file_id)
    if not item:
        raise HTTPException(404, "سند در آرشیو یافت نشد.")
    with get_db() as conn:
        row = conn.execute("SELECT card_json FROM files WHERE id = ?", (file_id,)).fetchone()
    card = DocumentCard.model_validate_json(row["card_json"] or "{}").model_dump()
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
    with get_db() as conn:
        changed = conn.execute(
            "UPDATE files SET card_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(card.model_dump(), ensure_ascii=False), file_id),
        ).rowcount
        if not changed:
            raise HTTPException(404, "سند در آرشیو یافت نشد.")
    return get_card(file_id)
