from __future__ import annotations

import html as html_lib
import io
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import docx
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Cm, Pt, RGBColor


# 15 Standard Charge Categories from the reference report
USER_REPORT_CHARGE_RULES: List[Dict[str, Any]] = [
    {
        "title": "توهین به مقدسات اسلامی (قرآن، پیامبر، حضرت فاطمه، امام‌های شیعیان)",
        "keywords": [
            "قرآن", "قران", "پیامبر", "امام هادی", "حضرت علی", "شیادان",
            "خرافات", "بت‌پرستی", "بت پرستی", "مرتد", "مرتتد", "ادیان دنیا ساخته",
            "به دین اینا", "بی خدایی", "بی دین", "عایشه",
        ],
    },
    {
        "title": "توهین به رهبری و امام خمینی (موشعلی، خامنه‌ای)",
        "keywords": [
            "مقوای مقام", "مجتبی مقوایی", "قبر خامنه‌ای", "قبر خامنه ای",
            "موشعلی", "عامل کشتار تمام سران کشور هم شخص علی خامنه‌ای",
        ],
    },
    {
        "title": "توهین به سپاه پاسداران انقلاب اسلامی",
        "keywords": [
            "فاطمیون", "سیاه لشکری", "سیاه لشکریها", "نیروی سرکوب", "زینبیون",
        ],
    },
    {
        "title": "توهین به بسیج و ارزشی‌ها (عرزشی)",
        "keywords": [
            "ارزشی", "ارزشیها", "ارزشی‌ها", "عرزشی", "جیره خور", "گدا گشنه",
        ],
    },
    {
        "title": "توهین به شهدا با الفاظ رکیک (کتلت قاسم، جاوید نام، جانفدا) - فقط در صورت استفاده تحقیرآمیز",
        "keywords": [
            "کتلت", "جاوید نام نابودشان", "جان شو فدا کنه", "جانفدا",
        ],
    },
    {
        "title": "حمایت از سلطنت‌طلبان و فراخوان‌های پهلوی",
        "keywords": [
            "جاوید شاه", "جاویدشاه", "شاهزاده", "پهلوی", "رضاشاه", "رضا شاه",
            "محمدرضا شاه", "پادشاهی خواه", "پادشاهی‌خواه", "شاهنشاه", "شیروخورشید",
        ],
    },
    {
        "title": "همکاری با رسانه‌های ضد انقلاب خارجی",
        "keywords": [
            "اینترنشنال", "اینترل نشنال", "فرکانس", "پارازیت", "بی‌بی‌سی", "منوتو",
        ],
    },
    {
        "title": "تبلیغ برای فتنه ۸۸ و اغتشاشات ۱۴۰۱ و ۱۴۰۲ (زن زندگی آزادی، آبان ۱۳۹۸)",
        "keywords": [
            "18 و 19 دی", "۱۸ و ۱۹ دی", "19 و 18 دی", "هجدهم و نوزدهم دیماه",
            "زن زندگی آزادی", "آبان 98", "آبان ۹۸", "رگبار بستن رو مردم",
        ],
    },
    {
        "title": "فراخوان به مقاومت مسلحانه",
        "keywords": [
            "جنگ چریکی", "به سمت مردم شلیک کرده رو قراره بگیریم", "دستگیر محاکمه و اعدام کنیم",
            "مسلحانه", "کوکتل مولوتف",
        ],
    },
    {
        "title": "تبلیغ صریح برای براندازی جمهوری اسلامی",
        "keywords": [
            "تغییر رژیم", "رژیم رو عوض", "نابودی جمهوری اسلامی", "رفتن جمهوری اسلامی",
            "رژیم از داخل فر میریزه", "رژیم اول از داخل بشکنه", "جمهوری اسلامی خود شیطانه",
        ],
    },
    {
        "title": "توهین به مراسم عاشورا و محرم (عاشورا، تاسوعا، کربلا)",
        "keywords": [
            "تاسوعاست", "عاشورا", "محرم", "کربلا گریه", "حسینیه‌ها", "شام غریبان",
        ],
    },
    {
        "title": "نشر اخبار دروغ درباره حوادث امنیتی",
        "keywords": [
            "ترور الارم", "صدای انفجار", "صدای پدافند", "بچه‌های اژه‌ای رو دزدیدن",
            "ماجرای جنجالی محمدرضا شهبازی",
        ],
    },
    {
        "title": "توهین به چهره‌های مذهبی و روحانیون",
        "keywords": [
            "ملایان فریبکار", "حجت‌الاسلامهای مفتخوار", "عمامه‌ی زاهد", "آخوندها", "اخوندها",
        ],
    },
    {
        "title": "حمایت از گروه‌های تجزیه‌طلب و مخالف",
        "keywords": [
            "مجاهدین", "مسیح علی‌نژاد", "عبدالله مهتدی", "حامد اسماعیلیان", "نازنین بنیادی",
        ],
    },
    {
        "title": "استفاده از الفاظ رکیک و توهین‌آمیز",
        "keywords": [
            "کصکش", "خواهر کصده", "حرومزاده", "ک ...‌ی ... ر", "ک ..‌ی .. ر", "ک .. و .. ن",
        ],
    },
]


def _clean_html_text(raw: str) -> str:
    if not raw:
        return ""
    # Remove any nested tags if present
    no_tags = re.sub(r"<[^>]+>", "", raw)
    return html_lib.unescape(no_tags).strip()


def parse_user_report_html(html_content: str) -> Dict[str, Any]:
    """
    Parses an HTML user report structured like `890046190_8b7aba55.html` into a complete,
    structured dictionary preserving all 6 tabs:
    - `virtual` (دیتای فضای مجازی)
    - `real` (دیتای حقیقی)
    - `analysis` (تحلیل شخصیت)
    - `charges` (عناوین اتهامی + شواهد مستند)
    - `groups` (گروه‌های کاربر)
    - `messages` (پیام‌های کاربر)
    """
    # 1. Header parsing
    h1_match = re.search(r"<h1>(.*?)</h1>", html_content, re.S)
    header_title = _clean_html_text(h1_match.group(1)) if h1_match else "گزارش کاربر"
    full_name = re.sub(r"^گزارش\s+کاربر\s*[:\-]?\s*", "", header_title).strip() or "کاربر ناشناس"

    header_p_match = re.search(
        r'<div\s+class="header-content">.*?<p>(.*?)</p>', html_content, re.S
    )
    header_subtitle = _clean_html_text(header_p_match.group(1)) if header_p_match else ""

    username = ""
    telegram_id = ""
    province = ""
    final_status = "سیاه"

    for part in header_subtitle.split("|"):
        p = part.strip()
        if p.startswith("آیدی:") or p.startswith("نام کاربری:"):
            username = p.split(":", 1)[1].strip()
        elif p.startswith("آیدی تلگرام:") or p.startswith("آیدی عددی:"):
            telegram_id = p.split(":", 1)[1].strip()
        elif p.startswith("استان:"):
            province = p.split(":", 1)[1].strip()
        elif p.startswith("وضعیت:"):
            final_status = p.split(":", 1)[1].strip()

    def _extract_tab_block(tab_id: str) -> str:
        pattern = rf'<div\s+id="{re.escape(tab_id)}"\s+class="tab-content[^"]*">(.*?)(?=<div\s+id="(?:virtual|real|analysis|charges|groups|messages)"\s+class="tab-content|<script>|$)'
        m = re.search(pattern, html_content, re.S)
        return m.group(1) if m else ""

    # 2. Virtual Data (دیتای فضای مجازی)
    virtual_block = _extract_tab_block("virtual")
    virtual_data: List[Dict[str, str]] = []
    for lbl, val in re.findall(
        r'<div\s+class="info-item">\s*<div\s+class="info-label">(.*?)</div>\s*<div\s+class="info-value">(.*?)</div>\s*</div>',
        virtual_block,
        re.S,
    ):
        virtual_data.append(
            {"label": _clean_html_text(lbl), "value": _clean_html_text(val)}
        )

    # 3. Real Data (دیتای حقیقی)
    real_block = _extract_tab_block("real")
    real_data: List[Dict[str, str]] = []
    real_map: Dict[str, str] = {}
    for lbl, val in re.findall(
        r'<div\s+class="info-item">\s*<div\s+class="info-label">(.*?)</div>\s*<div\s+class="info-value">(.*?)</div>\s*</div>',
        real_block,
        re.S,
    ):
        c_lbl = _clean_html_text(lbl)
        c_val = _clean_html_text(val)
        real_data.append({"label": c_lbl, "value": c_val})
        real_map[c_lbl] = c_val

    national_id = real_map.get("کد ملی", "")
    birth_date = real_map.get("تاریخ تولد", "")
    gender = real_map.get("جنسیت", "")
    postal_code = real_map.get("کد پستی", "")
    city = real_map.get("شهر", "")
    province = province or real_map.get("استان", "")
    telegram_id = telegram_id or real_map.get("آیدی تلگرام", "")
    username = username or real_map.get("نام کاربری", "")
    phone_number = real_map.get("شماره تلفن", "") or real_map.get("شماره موبایل", "")
    full_name = real_map.get("نام و نام خانوادگی", "") or full_name

    # 4. Personality Analysis (تحلیل شخصیت)
    analysis_block = _extract_tab_block("analysis")
    personality_analysis: List[Dict[str, str]] = []
    for title_raw, content_raw in re.findall(
        r'<div\s+class="analysis-section">\s*<div\s+class="analysis-section-title">(.*?)</div>\s*<div\s+class="analysis-content">(.*?)</div>\s*</div>',
        analysis_block,
        re.S,
    ):
        c_title = _clean_html_text(title_raw)
        c_content = _clean_html_text(content_raw)
        personality_analysis.append({"title": c_title, "content": c_content})
        if c_title == "وضعیت نهایی" and c_content:
            final_status = c_content

    # 5. Charges & Evidences (عناوین اتهامی)
    charges_block = _extract_tab_block("charges")
    charges: List[Dict[str, Any]] = []
    charge_sections = re.split(r'<div\s+class="charge-section"[^>]*>', charges_block)
    for sec in charge_sections[1:]:
        t_match = re.search(r'<div\s+class="charge-title">(.*?)</div>', sec, re.S)
        m_match = re.search(r'<div\s+class="charge-meta">(.*?)</div>', sec, re.S)
        c_title = _clean_html_text(t_match.group(1)) if t_match else "عنوان اتهامی"
        meta_text = _clean_html_text(m_match.group(1)) if m_match else ""
        evidences: List[Dict[str, Any]] = []

        for ev_meta_raw, ev_content_raw in re.findall(
            r'<div\s+class="evidence-item"[^>]*>\s*<div\s+class="evidence-meta">(.*?)</div>\s*<div\s+class="evidence-content">(.*?)</div>\s*</div>',
            sec,
            re.S,
        ):
            ev_meta = _clean_html_text(ev_meta_raw)
            ev_content = _clean_html_text(ev_content_raw)
            doc_id = ""
            offset = ""
            date_str = ""
            source_str = ""

            doc_m = re.search(r"سند\s*#?(\d+)", ev_meta)
            if doc_m:
                doc_id = doc_m.group(1)
            off_m = re.search(r"offset\s*(\d+)", ev_meta)
            if off_m:
                offset = off_m.group(1)
            date_m = re.search(r"تاریخ:\s*([^|]+)", ev_meta)
            if date_m:
                date_str = date_m.group(1).strip()
            src_m = re.search(r"منبع:\s*(.+)$", ev_meta)
            if src_m:
                source_str = src_m.group(1).strip()

            evidences.append(
                {
                    "meta": ev_meta,
                    "doc_id": doc_id,
                    "offset": offset,
                    "date": date_str,
                    "source": source_str,
                    "content": ev_content,
                }
            )

        cnt = len(evidences)
        cnt_m = re.search(r"(\d+)", meta_text)
        if cnt_m and not evidences:
            cnt = int(cnt_m.group(1))

        charges.append(
            {
                "title": c_title,
                "count": cnt,
                "evidences": evidences,
            }
        )

    # 6. User Groups (گروه‌های کاربر)
    groups_block = _extract_tab_block("groups")
    groups: List[Dict[str, Any]] = []
    for g_name_raw, g_cnt_raw in re.findall(
        r'<div\s+class="group-item">\s*<div\s+class="group-name">(.*?)</div>\s*<div\s+class="group-count">(.*?)</div>\s*</div>',
        groups_block,
        re.S,
    ):
        g_name = _clean_html_text(g_name_raw)
        g_cnt_label = _clean_html_text(g_cnt_raw)
        num_m = re.search(r"(\d+)", g_cnt_label)
        g_num = int(num_m.group(1)) if num_m else 0
        groups.append(
            {
                "name": g_name,
                "message_count": g_num,
                "count_label": g_cnt_label or f"{g_num} پیام",
            }
        )

    # 7. User Messages (پیام‌های کاربر)
    messages_block = _extract_tab_block("messages")
    messages: List[Dict[str, Any]] = []
    for msg_meta_raw, msg_content_raw in re.findall(
        r'<div\s+class="message"[^>]*>\s*<div\s+class="message-meta">(.*?)</div>\s*<div\s+class="message-content">(.*?)</div>\s*</div>',
        messages_block,
        re.S,
    ):
        m_meta = _clean_html_text(msg_meta_raw)
        m_content = _clean_html_text(msg_content_raw)
        date_str = ""
        source_str = ""
        doc_id = ""
        for chunk in m_meta.split("|"):
            c = chunk.strip()
            if c.startswith("تاریخ:"):
                date_str = c.split(":", 1)[1].strip()
            elif c.startswith("منبع:"):
                source_str = c.split(":", 1)[1].strip()
            elif c.startswith("سند:"):
                doc_id = c.split(":", 1)[1].strip()
        messages.append(
            {
                "meta": m_meta,
                "date": date_str,
                "source": source_str,
                "doc_id": doc_id,
                "content": m_content,
            }
        )

    return {
        "full_name": full_name,
        "username": username,
        "telegram_id": telegram_id,
        "national_id": national_id,
        "phone_number": phone_number,
        "birth_date": birth_date,
        "gender": gender,
        "postal_code": postal_code,
        "city": city,
        "province": province,
        "final_status": final_status,
        "header_subtitle": header_subtitle
        or f"آیدی: {username or '—'} | آیدی تلگرام: {telegram_id or '—'} | استان: {province or '—'} | وضعیت: {final_status}",
        "virtual_data": virtual_data,
        "real_data": real_data,
        "personality_analysis": personality_analysis,
        "charges": charges,
        "groups": groups,
        "messages": messages,
        "total_charges": len(charges),
        "total_groups": len(groups),
        "total_messages": len(messages),
    }


def build_user_report_from_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Builds or auto-analyzes a complete 6-tab User Report from user input, raw messages,
    or structured fields.
    """
    full_name = (payload.get("full_name") or "").strip() or "کاربر مورد بررسی"
    username = (payload.get("username") or "").strip().lstrip("@")
    telegram_id = (payload.get("telegram_id") or "").strip()
    national_id = (payload.get("national_id") or "").strip()
    phone_number = (payload.get("phone_number") or "").strip()
    birth_date = (payload.get("birth_date") or "").strip()
    gender = (payload.get("gender") or "مرد").strip()
    postal_code = (payload.get("postal_code") or "").strip()
    city = (payload.get("city") or "کاشمر").strip()
    province = (payload.get("province") or "خراسان رضوی").strip()
    final_status = (payload.get("final_status") or "سیاه").strip()

    # Virtual data
    virtual_data = payload.get("virtual_data")
    if not isinstance(virtual_data, list) or not virtual_data:
        virtual_data = [
            {"label": "نام کامل", "value": full_name},
            {"label": "نام کاربری", "value": username or "—"},
            {"label": "آیدی تلگرام", "value": telegram_id or "—"},
        ]

    # Real data
    real_data = payload.get("real_data")
    if not isinstance(real_data, list) or not real_data:
        real_data = [
            {"label": "کد ملی", "value": national_id or "—"},
            {"label": "تاریخ تولد", "value": birth_date or "—"},
            {"label": "جنسیت", "value": gender or "—"},
            {"label": "کد پستی", "value": postal_code or "—"},
            {"label": "شهر", "value": city or "—"},
            {"label": "استان", "value": province or "—"},
            {"label": "آیدی تلگرام", "value": telegram_id or "—"},
            {"label": "نام کاربری", "value": username or "—"},
            {"label": "شماره تلفن", "value": phone_number or "—"},
            {"label": "نام و نام خانوادگی", "value": full_name},
        ]

    # Parse messages if raw_messages_text is provided
    messages: List[Dict[str, Any]] = []
    if isinstance(payload.get("messages"), list) and payload["messages"]:
        messages = payload["messages"]
    elif payload.get("raw_messages_text"):
        raw_lines = [
            ln.strip()
            for ln in str(payload["raw_messages_text"]).splitlines()
            if ln.strip()
        ]
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        default_group = (payload.get("default_group") or "گروه رصد فضای مجازی").strip()
        for idx, line in enumerate(raw_lines):
            # Support "تاریخ | منبع | متن" or plain text
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 3:
                m_date, m_src, m_txt = parts[0], parts[1], " | ".join(parts[2:])
            elif len(parts) == 2:
                m_date, m_src, m_txt = now_str, parts[0], parts[1]
            else:
                m_date, m_src, m_txt = now_str, default_group, line
            doc_no = str(16040000 + idx)
            messages.append(
                {
                    "meta": f"تاریخ: {m_date} | منبع: {m_src} | سند: {doc_no}",
                    "date": m_date,
                    "source": m_src,
                    "doc_id": doc_no,
                    "content": m_txt,
                }
            )

    # Groups aggregation
    groups: List[Dict[str, Any]] = []
    if isinstance(payload.get("groups"), list) and payload["groups"]:
        groups = payload["groups"]
    else:
        group_counts: Dict[str, int] = {}
        for idx, msg in enumerate(messages):
            src = (msg.get("source") or "گروه عمومی").strip()
            group_counts[src] = group_counts.get(src, 0) + 1
        for g_name, g_cnt in sorted(group_counts.items(), key=lambda x: -x[1]):
            groups.append(
                {
                    "name": g_name,
                    "message_count": g_cnt,
                    "count_label": f"{g_cnt} پیام",
                }
            )

    # Charges matching against messages
    charges: List[Dict[str, Any]] = []
    if isinstance(payload.get("charges"), list) and payload["charges"]:
        charges = payload["charges"]
    else:
        for rule in USER_REPORT_CHARGE_RULES:
            matched_evidences: List[Dict[str, Any]] = []
            for idx, msg in enumerate(messages):
                txt = (msg.get("content") or "").strip()
                if not txt:
                    continue
                if any(kw in txt for kw in rule["keywords"]):
                    doc_id = msg.get("doc_id") or str(16040000 + idx)
                    m_date = msg.get("date") or ""
                    m_src = msg.get("source") or "گروه رصد"
                    matched_evidences.append(
                        {
                            "meta": f"سند #{doc_id} (offset {idx + 1}) | تاریخ: {m_date} | منبع: {m_src}",
                            "doc_id": str(doc_id),
                            "offset": str(idx + 1),
                            "date": m_date,
                            "source": m_src,
                            "content": txt,
                        }
                    )
            if matched_evidences:
                charges.append(
                    {
                        "title": rule["title"],
                        "count": len(matched_evidences),
                        "evidences": matched_evidences,
                    }
                )

    # Personality analysis
    personality_analysis = payload.get("personality_analysis")
    if not isinstance(personality_analysis, list) or not personality_analysis:
        charge_titles = [c["title"] for c in charges]
        group_names = [g["name"] for g in groups]
        activity_type = (
            payload.get("activity_type")
            or (
                "فعالیت سیاسی-اعتراضی و تبلیغی در فضای مجازی با مصادیق مجرمانه: "
                + "، ".join(charge_titles[:3])
                if charge_titles
                else "فعالیت عمومی و رصدشده در شبکه‌های اجتماعی و گروه‌های پیام‌رسان"
            )
        )
        behavior_desc = (
            payload.get("behavior_desc")
            or f"کاربر با نام «{full_name}» و شناسهٔ کاربری «{username or telegram_id or 'نامشخص'}» دارای {len(messages)} پیام ثبت‌شده در {len(groups)} گروه است. "
            + (
                f"در بررسی محتوایی پیام‌ها، {len(charges)} عنوان اتهامی مستند تشخیص داده شد."
                if charges
                else "در پیام‌های ثبت‌شده مصداق مجرمانهٔ حادی مشاهده نشد."
            )
        )
        network_desc = (
            payload.get("network_desc")
            or (
                "فعال در گروه‌ها و کانال‌های: " + "، ".join(group_names)
                if group_names
                else "تعاونی و ارتباطات در گروه‌های پیام‌رسان و شبکه‌های اجتماعی"
            )
        )
        interests_desc = (
            payload.get("interests_desc")
            or "مباحث سیاسی، اجتماعی، بازنشر مطالب کانال‌ها و تبادل نظر در گروه‌های مجازی"
        )
        key_points = payload.get("key_points") or (
            " ".join(
                f"{idx + 1}. {c['title']} ({c['count']} مورد شاهد مستند)."
                for idx, c in enumerate(charges[:10])
            )
            if charges
            else "۱. بررسی اولیهٔ پیام‌ها و فعالیت‌های کاربر در فضای مجازی انجام شده است."
        )
        final_reason = (
            payload.get("final_reason")
            or (
                "وجود شواهد و مستندات متعدد در عناوین اتهامی شامل: "
                + "، ".join(charge_titles)
                if charge_titles
                else "ثبت جهت مستندسازی در بانک پرونده‌های کاربری ساهر."
            )
        )
        personality_analysis = [
            {"title": "نوع فعالیت", "content": activity_type},
            {"title": "شخصیت و رفتار", "content": behavior_desc},
            {"title": "شبکه ارتباطی", "content": network_desc},
            {"title": "علایق و تخصص‌ها", "content": interests_desc},
            {"title": "نکات کلیدی", "content": key_points},
            {"title": "وضعیت نهایی", "content": final_status},
            {"title": "دلیل نهایی", "content": final_reason},
        ]

    header_subtitle = (
        f"آیدی: {username or '—'} | آیدی تلگرام: {telegram_id or '—'} | استان: {province or '—'} | وضعیت: {final_status}"
    )

    return {
        "full_name": full_name,
        "username": username,
        "telegram_id": telegram_id,
        "national_id": national_id,
        "phone_number": phone_number,
        "birth_date": birth_date,
        "gender": gender,
        "postal_code": postal_code,
        "city": city,
        "province": province,
        "final_status": final_status,
        "header_subtitle": header_subtitle,
        "virtual_data": virtual_data,
        "real_data": real_data,
        "personality_analysis": personality_analysis,
        "charges": charges,
        "groups": groups,
        "messages": messages,
        "total_charges": len(charges),
        "total_groups": len(groups),
        "total_messages": len(messages),
    }


def export_user_report_html(report: Dict[str, Any]) -> str:
    """
    Exports a user report as a standalone, self-contained HTML file matching the exact
    template, CSS, 6 tabs, charge evidence pagination (5 per page), and message pagination
    of `890046190_8b7aba55.html`.
    """
    esc = html_lib.escape
    full_name = esc(str(report.get("full_name") or "کاربر"))
    subtitle = esc(
        str(
            report.get("header_subtitle")
            or f"آیدی: {report.get('username') or '—'} | آیدی تلگرام: {report.get('telegram_id') or '—'} | استان: {report.get('province') or '—'} | وضعیت: {report.get('final_status') or 'سیاه'}"
        )
    )
    virtual_data = report.get("virtual_data") or []
    real_data = report.get("real_data") or []
    personality_analysis = report.get("personality_analysis") or []
    charges = report.get("charges") or []
    groups = report.get("groups") or []
    messages = report.get("messages") or []

    virtual_items_html = "\n".join(
        f"""                    <div class="info-item">
                        <div class="info-label">{esc(str(item.get("label") or ""))}</div>
                        <div class="info-value">{esc(str(item.get("value") or ""))}</div>
                    </div>"""
        for item in virtual_data
    )

    real_items_html = "\n".join(
        f"""                    <div class="info-item">
                        <div class="info-label">{esc(str(item.get("label") or ""))}</div>
                        <div class="info-value">{esc(str(item.get("value") or ""))}</div>
                    </div>"""
        for item in real_data
    )

    analysis_items_html = "\n".join(
        f"""                    <div class="analysis-section">
                        <div class="analysis-section-title">{esc(str(sec.get("title") or ""))}</div>
                        <div class="analysis-content">{esc(str(sec.get("content") or ""))}</div>
                    </div>"""
        for sec in personality_analysis
    )

    charges_html_parts: List[str] = []
    for c_idx, ch in enumerate(charges):
        c_title = esc(str(ch.get("title") or ""))
        evidences = ch.get("evidences") or []
        c_count = ch.get("count") or len(evidences)
        ev_html_list: List[str] = []
        for e_idx, ev in enumerate(evidences):
            ev_meta = esc(
                str(
                    ev.get("meta")
                    or f"سند #{ev.get('doc_id') or ''} (offset {ev.get('offset') or (e_idx + 1)}) | تاریخ: {ev.get('date') or ''} | منبع: {ev.get('source') or ''}"
                )
            )
            ev_content = esc(str(ev.get("content") or ""))
            ev_html_list.append(
                f"""                <div class="evidence-item" data-charge="{c_idx}" data-index="{e_idx}">
                    <div class="evidence-meta">{ev_meta}</div>
                    <div class="evidence-content">{ev_content}</div>
                </div>"""
            )
        total_ev_pages = max(1, (len(evidences) + 4) // 5)
        pag_html = ""
        if len(evidences) > 5:
            pag_html = f"""                <div class="evidence-pagination">
                    <button onclick="changeEvidencePage({c_idx}, -1)" id="evidence-prev-{c_idx}">قبلی</button>
                    <span id="evidence-page-info-{c_idx}">صفحه 1 از {total_ev_pages}</span>
                    <button onclick="changeEvidencePage({c_idx}, 1)" id="evidence-next-{c_idx}">بعدی</button>
                </div>"""
        charges_html_parts.append(
            f"""            <div class="charge-section" id="charge-{c_idx}">
                <div class="charge-title">{c_title}</div>
                <div class="charge-meta">تعداد شواهد: {c_count}</div>
                <div id="evidence-container-{c_idx}">
{chr(10).join(ev_html_list)}
                </div>
{pag_html}
            </div>"""
        )

    groups_html = "\n".join(
        f"""            <div class="group-item">
                <div class="group-name">{esc(str(g.get("name") or ""))}</div>
                <div class="group-count">{esc(str(g.get("count_label") or f"{g.get('message_count', 0)} پیام"))}</div>
            </div>"""
        for g in groups
    )

    messages_html = "\n".join(
        f"""            <div class="message" data-page="1">
                <div class="message-meta">
                    {esc(str(m.get("meta") or f"تاریخ: {m.get('date') or ''} | منبع: {m.get('source') or ''} | سند: {m.get('doc_id') or ''}"))}
                </div>
                <div class="message-content">{esc(str(m.get("content") or ""))}</div>
            </div>"""
        for m in messages
    )

    return f"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>گزارش کاربر - {full_name}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
            direction: rtl;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            overflow: hidden;
        }}
        .header {{
            background: linear-gradient(135deg, #dc2626 0%, #b91c1c 100%);
            color: white;
            padding: 40px;
            position: relative;
            overflow: hidden;
        }}
        .header-content {{ position: relative; z-index: 1; }}
        .header h1 {{ font-size: 32px; margin-bottom: 10px; font-weight: 700; }}
        .header p {{ font-size: 16px; opacity: 0.9; }}
        .tabs {{
            display: flex;
            background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
            border-bottom: 3px solid #dee2e6;
            overflow-x: auto;
            padding: 0 10px;
        }}
        .tab {{
            padding: 18px 30px;
            cursor: pointer;
            border: none;
            background: none;
            font-size: 15px;
            font-weight: 700;
            color: #6c757d;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            white-space: nowrap;
            position: relative;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .tab.active {{
            color: #667eea;
            background: white;
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.2);
        }}
        .tab-content {{ display: none; padding: 30px; }}
        .tab-content.active {{ display: block; }}
        .section {{ margin-bottom: 25px; }}
        .section-title {{
            font-size: 20px;
            font-weight: 700;
            color: #2c3e50;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 3px solid #667eea;
        }}
        .info-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
        }}
        .info-item {{
            background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
            padding: 20px;
            border-radius: 12px;
            border: 1px solid #dee2e6;
        }}
        .info-label {{ font-weight: 700; color: #495057; margin-bottom: 8px; font-size: 14px; }}
        .info-value {{ color: #212529; font-size: 15px; font-weight: 500; }}
        .message {{
            background: #f8f9fa;
            padding: 20px;
            border-radius: 12px;
            margin-bottom: 15px;
            border-right: 4px solid #667eea;
        }}
        .message-content {{ white-space: pre-wrap; line-height: 1.8; color: #212529; }}
        .message-meta {{
            font-size: 13px;
            color: #6c757d;
            margin-bottom: 10px;
            padding-bottom: 10px;
            border-bottom: 1px solid #dee2e6;
        }}
        .charge-section {{
            background: linear-gradient(135deg, #fff5f5 0%, #ffe0e0 100%);
            padding: 25px;
            border-radius: 15px;
            margin-bottom: 20px;
            border: 2px solid #ffcccc;
        }}
        .charge-title {{ color: #dc2626; font-size: 18px; font-weight: 700; margin-bottom: 15px; }}
        .evidence-item {{
            background: white;
            padding: 15px;
            border-radius: 10px;
            margin-bottom: 10px;
            border: 1px solid #ffcccc;
        }}
        .evidence-content {{ white-space: pre-wrap; line-height: 1.6; color: #495057; }}
        .evidence-meta {{
            font-size: 12px;
            color: #6c757d;
            margin-bottom: 8px;
            padding-bottom: 8px;
            border-bottom: 1px solid #fecaca;
        }}
        .evidence-pagination {{
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 10px;
            margin-top: 15px;
            padding: 12px;
            background: rgba(255, 204, 204, 0.3);
            border-radius: 10px;
        }}
        .analysis-section {{
            background: linear-gradient(135deg, #e8f4f8 0%, #d1e8f0 100%);
            padding: 25px;
            border-radius: 15px;
            margin-bottom: 20px;
            border: 2px solid #b8d4e3;
        }}
        .analysis-section-title {{ color: #2c5f7c; font-size: 17px; font-weight: 700; margin-bottom: 12px; }}
        .analysis-content {{ white-space: pre-wrap; line-height: 1.9; color: #1a3a4a; }}
        .group-item {{
            background: linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 100%);
            padding: 15px 20px;
            border-radius: 10px;
            margin-bottom: 10px;
            border: 1px solid #bae6fd;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .group-name {{ font-weight: 600; color: #0369a1; }}
        .group-count {{
            background: #0ea5e9;
            color: white;
            padding: 5px 12px;
            border-radius: 20px;
            font-size: 13px;
            font-weight: 600;
        }}
        .pagination {{
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 15px;
            margin-top: 25px;
            padding: 20px;
            background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
            border-radius: 15px;
            flex-wrap: wrap;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="header-content">
                <h1>گزارش کاربر: {full_name}</h1>
                <p>{subtitle}</p>
            </div>
        </div>
        <div class="tabs">
            <button class="tab active" onclick="showTab('virtual')">🌐 دیتای فضای مجازی</button>
            <button class="tab" onclick="showTab('real')">👤 دیتای حقیقی</button>
            <button class="tab" onclick="showTab('analysis')">🧠 تحلیل شخصیت</button>
            <button class="tab" onclick="showTab('charges')">⚖️ عناوین اتهامی ({len(charges)})</button>
            <button class="tab" onclick="showTab('groups')">👥 گروه‌های کاربر ({len(groups)})</button>
            <button class="tab" onclick="showTab('messages')">💬 پیام‌های کاربر ({len(messages)})</button>
        </div>
        <div id="virtual" class="tab-content active">
            <div class="section">
                <div class="section-title">دیتای فضای مجازی</div>
                <div class="info-grid">
{virtual_items_html}
                </div>
            </div>
        </div>
        <div id="real" class="tab-content">
            <div class="section">
                <div class="section-title">دیتای حقیقی</div>
                <div class="info-grid">
{real_items_html}
                </div>
            </div>
        </div>
        <div id="analysis" class="tab-content">
            <div class="section">
                <div class="section-title">تحلیل شخصیت</div>
{analysis_items_html}
            </div>
        </div>
        <div id="charges" class="tab-content">
            <div class="section">
                <div class="section-title">عناوین اتهامی</div>
{chr(10).join(charges_html_parts)}
            </div>
        </div>
        <div id="groups" class="tab-content">
            <div class="section">
                <div class="section-title">گروه‌های کاربر</div>
{groups_html}
            </div>
        </div>
        <div id="messages" class="tab-content">
            <div class="section">
                <div class="section-title">پیام‌های کاربر ({len(messages)} پیام)</div>
                <div id="messages-container">
{messages_html}
                </div>
                <div class="pagination">
                    <button onclick="changePage(-1)" id="prev-btn">قبلی</button>
                    <span id="page-info">صفحه 1 از 1</span>
                    <button onclick="changePage(1)" id="next-btn">بعدی</button>
                    <div class="pagination-controls">
                        <label for="items-per-page">تعداد در صفحه:</label>
                        <select id="items-per-page" onchange="changeItemsPerPage()">
                            <option value="10">10</option>
                            <option value="20" selected>20</option>
                            <option value="50">50</option>
                            <option value="100">100</option>
                            <option value="200">200</option>
                        </select>
                    </div>
                </div>
            </div>
        </div>
    </div>
    <script>
        function showTab(tabId) {{
            document.querySelectorAll('.tab-content').forEach(tab => tab.classList.remove('active'));
            document.querySelectorAll('.tab').forEach(tab => tab.classList.remove('active'));
            document.getElementById(tabId).classList.add('active');
            event.target.classList.add('active');
        }}
        let messagesPerPage = 20;
        let currentPage = 1;
        const messages = document.querySelectorAll('.message');
        function changePage(direction) {{
            const totalPages = Math.max(1, Math.ceil(messages.length / messagesPerPage));
            currentPage += direction;
            if (currentPage < 1) currentPage = 1;
            if (currentPage > totalPages) currentPage = totalPages;
            updatePagination();
        }}
        function changeItemsPerPage() {{
            messagesPerPage = parseInt(document.getElementById('items-per-page').value);
            currentPage = 1;
            updatePagination();
        }}
        function updatePagination() {{
            const newTotalPages = Math.max(1, Math.ceil(messages.length / messagesPerPage));
            messages.forEach((msg, index) => {{
                const pageNum = Math.floor(index / messagesPerPage) + 1;
                msg.style.display = pageNum === currentPage ? 'block' : 'none';
            }});
            document.getElementById('page-info').textContent = `صفحه ${{currentPage}} از ${{newTotalPages}}`;
            document.getElementById('prev-btn').disabled = currentPage === 1;
            document.getElementById('next-btn').disabled = currentPage === newTotalPages;
        }}
        const evidencePerPage = 5;
        const evidenceState = {{}};
        function changeEvidencePage(chargeIdx, direction) {{
            if (!evidenceState[chargeIdx]) evidenceState[chargeIdx] = 1;
            evidenceState[chargeIdx] += direction;
            if (evidenceState[chargeIdx] < 1) evidenceState[chargeIdx] = 1;
            const evidenceItems = document.querySelectorAll(`.evidence-item[data-charge="${{chargeIdx}}"]`);
            const totalEvidencePages = Math.max(1, Math.ceil(evidenceItems.length / evidencePerPage));
            if (evidenceState[chargeIdx] > totalEvidencePages) evidenceState[chargeIdx] = totalEvidencePages;
            evidenceItems.forEach((item, index) => {{
                const pageNum = Math.floor(index / evidencePerPage) + 1;
                item.style.display = pageNum === evidenceState[chargeIdx] ? 'block' : 'none';
            }});
            const infoEl = document.getElementById(`evidence-page-info-${{chargeIdx}}`);
            if (infoEl) infoEl.textContent = `صفحه ${{evidenceState[chargeIdx]}} از ${{totalEvidencePages}}`;
        }}
        if (messages.length > 0) updatePagination();
        document.querySelectorAll('.charge-section').forEach((section, idx) => {{
            const evidenceItems = section.querySelectorAll('.evidence-item');
            if (evidenceItems.length > 5) {{
                evidenceState[idx] = 1;
                changeEvidencePage(idx, 0);
            }}
        }});
    </script>
</body>
</html>"""


def generate_user_report_docx(report: Dict[str, Any]) -> bytes:
    """
    Generates a comprehensive RTL Persian Word (.docx) document for a 6-tab User Report.
    """
    _EN_TO_FA_TRANS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

    def _to_persian_digits(val: Any) -> str:
        return str(val or "").translate(_EN_TO_FA_TRANS)

    def _apply_rtl_paragraph(paragraph: Any, align: Any = WD_ALIGN_PARAGRAPH.RIGHT) -> None:
        paragraph.alignment = align
        pPr = paragraph._p.get_or_add_pPr()
        bidi = OxmlElement("w:bidi")
        bidi.set(qn("w:val"), "1")
        pPr.append(bidi)

    def _set_run_persian_font(
        run: Any,
        size_pt: float = 11,
        bold: bool = False,
        color: Optional[RGBColor] = None,
    ) -> None:
        run.font.name = "Vazirmatn"
        run.font.size = Pt(size_pt)
        run.font.bold = bold
        if color is not None:
            run.font.color.rgb = color
        rPr = run._r.get_or_add_rPr()
        rFonts = OxmlElement("w:rFonts")
        rFonts.set(qn("w:ascii"), "Vazirmatn")
        rFonts.set(qn("w:hAnsi"), "Vazirmatn")
        rFonts.set(qn("w:cs"), "Vazirmatn")
        rPr.append(rFonts)
        rtl = OxmlElement("w:rtl")
        rtl.set(qn("w:val"), "1")
        rPr.append(rtl)

    def _set_table_rtl(table: Any) -> None:
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        tblPr = table._tbl.tblPr
        bidiVisual = OxmlElement("w:bidiVisual")
        tblPr.append(bidiVisual)

    def _set_cell_background(cell: Any, fill_hex: str) -> None:
        tcPr = cell._tc.get_or_add_tcPr()
        shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex}"/>')
        tcPr.append(shd)

    def _set_cell_margins(cell: Any, top: int = 90, bottom: int = 90, left: int = 120, right: int = 120) -> None:
        tcPr = cell._tc.get_or_add_tcPr()
        tcMar = OxmlElement("w:tcMar")
        for m_name, val in (("top", top), ("bottom", bottom), ("left", left), ("right", right)):
            node = OxmlElement(f"w:{m_name}")
            node.set(qn("w:w"), str(val))
            node.set(qn("w:type"), "dxa")
            tcMar.append(node)
        tcPr.append(tcMar)

    doc = docx.Document()
    for section in doc.sections:
        section.top_margin = Cm(1.8)
        section.bottom_margin = Cm(1.8)
        section.left_margin = Cm(1.8)
        section.right_margin = Cm(1.8)

    full_name = report.get("full_name") or "کاربر"
    subtitle = _to_persian_digits(report.get("header_subtitle") or "")

    # Title Banner
    p_title = doc.add_paragraph()
    _apply_rtl_paragraph(p_title, WD_ALIGN_PARAGRAPH.CENTER)
    r_title = p_title.add_run(f"گزارش جامع کاربر: {full_name}")
    _set_run_persian_font(r_title, size_pt=16, bold=True, color=RGBColor(185, 28, 28))

    p_sub = doc.add_paragraph()
    _apply_rtl_paragraph(p_sub, WD_ALIGN_PARAGRAPH.CENTER)
    r_sub = p_sub.add_run(subtitle)
    _set_run_persian_font(r_sub, size_pt=11, bold=True, color=RGBColor(51, 65, 85))

    # 1. Virtual & Real Data Table
    p_h1 = doc.add_paragraph()
    _apply_rtl_paragraph(p_h1)
    r_h1 = p_h1.add_run("۱. دیتای فضای مجازی و دیتای حقیقی کاربر")
    _set_run_persian_font(r_h1, size_pt=13, bold=True, color=RGBColor(30, 58, 95))

    combined_info = []
    for item in report.get("virtual_data") or []:
        combined_info.append((f"[مجازی] {item.get('label', '')}", str(item.get("value", "—"))))
    for item in report.get("real_data") or []:
        combined_info.append((f"[حقیقی] {item.get('label', '')}", str(item.get("value", "—"))))

    if combined_info:
        tbl = doc.add_table(rows=len(combined_info), cols=2)
        tbl.style = "Table Grid"
        _set_table_rtl(tbl)
        for idx, (lbl, val) in enumerate(combined_info):
            row = tbl.rows[idx]
            c0, c1 = row.cells[0], row.cells[1]
            _set_cell_background(c0, "F1F5F9")
            _set_cell_margins(c0)
            _set_cell_margins(c1)
            p0 = c0.paragraphs[0]
            _apply_rtl_paragraph(p0)
            r0 = p0.add_run(_to_persian_digits(lbl))
            _set_run_persian_font(r0, size_pt=10, bold=True)
            p1 = c1.paragraphs[0]
            _apply_rtl_paragraph(p1)
            r1 = p1.add_run(_to_persian_digits(val))
            _set_run_persian_font(r1, size_pt=10)

    # 2. Personality Analysis
    p_h2 = doc.add_paragraph()
    _apply_rtl_paragraph(p_h2)
    r_h2 = p_h2.add_run("۲. تحلیل شخصیت، رفتار و وضعیت نهایی")
    _set_run_persian_font(r_h2, size_pt=13, bold=True, color=RGBColor(30, 58, 95))

    for sec in report.get("personality_analysis") or []:
        p_sec = doc.add_paragraph()
        _apply_rtl_paragraph(p_sec)
        r_st = p_sec.add_run(f"▪ {sec.get('title', '')}: ")
        _set_run_persian_font(r_st, size_pt=11, bold=True, color=RGBColor(44, 95, 124))
        r_sc = p_sec.add_run(_to_persian_digits(sec.get("content", "")))
        _set_run_persian_font(r_sc, size_pt=10.5)

    # 3. Criminal Charges
    charges = report.get("charges") or []
    p_h3 = doc.add_paragraph()
    _apply_rtl_paragraph(p_h3)
    r_h3 = p_h3.add_run(_to_persian_digits(f"۳. عناوین اتهامی و شواهد مستند ({len(charges)} عنوان)"))
    _set_run_persian_font(r_h3, size_pt=13, bold=True, color=RGBColor(185, 28, 28))

    for idx, ch in enumerate(charges):
        p_ch = doc.add_paragraph()
        _apply_rtl_paragraph(p_ch)
        evidences = ch.get("evidences") or []
        r_ch = p_ch.add_run(
            _to_persian_digits(
                f"عنوان اتهامی {idx + 1}: {ch.get('title', '')} (تعداد شواهد: {ch.get('count', len(evidences))})"
            )
        )
        _set_run_persian_font(r_ch, size_pt=11, bold=True, color=RGBColor(185, 28, 28))
        for ev in evidences[:10]:
            p_ev = doc.add_paragraph()
            _apply_rtl_paragraph(p_ev)
            r_em = p_ev.add_run(_to_persian_digits(f"  • [{ev.get('meta', '')}]: "))
            _set_run_persian_font(r_em, size_pt=9.5, bold=True, color=RGBColor(100, 116, 139))
            r_ec = p_ev.add_run(_to_persian_digits(ev.get("content", "")))
            _set_run_persian_font(r_ec, size_pt=10)

    # 4. Groups
    groups = report.get("groups") or []
    p_h4 = doc.add_paragraph()
    _apply_rtl_paragraph(p_h4)
    r_h4 = p_h4.add_run(_to_persian_digits(f"۴. گروه‌های فعالیت کاربر ({len(groups)} گروه)"))
    _set_run_persian_font(r_h4, size_pt=13, bold=True, color=RGBColor(3, 105, 161))

    for g in groups:
        p_g = doc.add_paragraph()
        _apply_rtl_paragraph(p_g)
        r_g = p_g.add_run(
            _to_persian_digits(f"• {g.get('name', '')} — {g.get('count_label', '')}")
        )
        _set_run_persian_font(r_g, size_pt=10.5, bold=True)

    # 5. Messages Summary
    messages = report.get("messages") or []
    p_h5 = doc.add_paragraph()
    _apply_rtl_paragraph(p_h5)
    r_h5 = p_h5.add_run(
        _to_persian_digits(f"۵. فهرست پیام‌های ثبت‌شدهٔ کاربر (مجموع کل: {len(messages)} پیام)")
    )
    _set_run_persian_font(r_h5, size_pt=13, bold=True, color=RGBColor(30, 58, 95))

    for m in messages[:50]:
        p_m = doc.add_paragraph()
        _apply_rtl_paragraph(p_m)
        r_mm = p_m.add_run(_to_persian_digits(f"[{m.get('meta', '')}]\n"))
        _set_run_persian_font(r_mm, size_pt=9, bold=True, color=RGBColor(100, 116, 139))
        r_mc = p_m.add_run(_to_persian_digits(m.get("content", "")))
        _set_run_persian_font(r_mc, size_pt=10)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
