from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from PIL import Image, ImageStat

from services.ingestion.extractor import normalize_persian_text


THEMATIC_CATEGORIES_12: List[str] = [
    "اجتماعی",
    "اقتصادی",
    "امنیتی",
    "جاسوسی",
    "دفاعی (نظامی، کویر و مرز)",
    "دین و روحانیت",
    "رزمایش",
    "سایبری",
    "سیاسی",
    "علم و فناوری",
    "فرهنگی",
    "هواگرد (پهپاد، ریزپرنده، جنگنده و ...)",
]


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
    # Priority 1: Username & Account ID classification
    account_id: str = ""
    account_username: str = ""
    account_label: str = "بدون نام کاربری / آیدی مشخص"
    platform_source: str = "اسکرین‌شات / تصویر عمومی"
    # Priority 2: 12 Thematic Categories + Visual Nature
    thematic_category: str = "اجتماعی"
    image_nature: str = "سند یا برگهٔ متنی اسکن‌شده"
    detected_topic: str = "اجتماعی"
    confidence_label: str = "بالا"
    tags: List[str] = field(default_factory=list)
    key_findings: List[str] = field(default_factory=list)
    analysis_summary: str = ""
    # Structured Template (قواره) — strictly for «فرهنگی» and «اجتماعی»
    template_applicable: bool = False
    template_fields: Optional[Dict[str, Any]] = None
    formatted_template_text: str = ""


_THEMATIC_KEYWORDS_12: Dict[str, List[str]] = {
    "هواگرد (پهپاد، ریزپرنده، جنگنده و ...)": [
        "هواگرد", "پهپاد", "ریزپرنده", "جنگنده", "بالگرد", "هوانوردی", "کوادکوپتر",
        "پهپادی", "شاهد", "مهاجر", "کمان", "ابابیل", "آرش", "فطرس", "سیمرغ",
        "سوخو", "میگ", "اف-14", "اف-4", "اف-5", "اف۱۴", "شکاری", "بمب‌افکن", "بمب افکن",
        "پرواز", "پرنده هدایت‌پذیر", "پرنده هدایت پذیر", "بدون سرنشین", "عمودپرواز",
        "ترابری هوایی", "نیروی هوایی", "نهاجا", "هوانیروز", "باند پرواز", "آشیانه",
        "رهگیری هوایی", "محموله هوایی", "بال ثابت", "ملخ", "موتور جت", "توربوفن",
        "uav", "drone", "quadcopter", "microdrone", "fighter", "aircraft", "aviation",
        "helicopter", "airforce", "shahed", "mohajer", "su-35", "f-14",
    ],
    "رزمایش": [
        "رزمایش", "مانور", "تمرین نظامی", "تمرین تاکتیکی", "رزمایش مشترک",
        "رزمایش دریایی", "رزمایش زمینی", "رزمایش هوایی", "رزمایش موشکی",
        "رزمایش پدافندی", "میدان تیر", "مرحله نهایی رزمایش", "منطقه عمومی رزمایش",
        "ذوالفقار", "پیامبر اعظم", "اقتدار", "مدافعان آسمان", "ولایت", "فاتحان خیبر",
        "امنیت پایدار", "تمرین رزم", "سناریوی رزمایش", "آتشبار در رزمایش",
        "military exercise", "wargame", "maneuver", "tactical drill", "joint drill",
    ],
    "دفاعی (نظامی، کویر و مرز)": [
        "دفاعی", "نظامی", "ارتش", "سپاه", "نیروهای مسلح", "مرز", "مرزبانی", "مرزی",
        "کویر", "پایش مرزی", "پاسگاه", "پادگان", "موشک", "موشکی", "پدافند", "رادار",
        "زرهی", "توپخانه", "تانک", "نفربر", "ناو", "ناوچه", "زیردریایی", "نیروی زمینی",
        "نیروی دریایی", "تکاور", "تیپ", "لشکر", "قرارگاه", "وزارت دفاع", "ودجا",
        "تسلیحات", "مهمات", "دفاع مقدس", "انسداد مرز", "برجک", "دیدبانی", "پهنه کویری",
        "defense", "military", "border", "desert", "missile", "radar", "artillery",
        "infantry", "navy", "armed forces", "battalion", "garrison",
    ],
    "سایبری": [
        "سایبری", "هک", "هکر", "هکری", "حمله سایبری", "بدافزار", "باج‌افزار", "باج افزار",
        "فیشینگ", "نشت داده", "دیتابیس", "امنیت سایبری", "نفوذ سایبری", "فایروال",
        "سرور", "آسیب‌پذیری", "آسیب پذیری", "زیرساخت دیجیتال", "پدافند سایبری",
        "ارتش سایبری", "مرکز ماهر", "تارنما", "سایت", "دامنه", "بات‌نت", "بات نت",
        "دی‌داس", "سورس کد", "اکسپلویت", "تروجان", "دارک وب", "فیلترینگ", "پورت",
        "cyber", "hacker", "hack", "malware", "ransomware", "phishing", "ddos",
        "exploit", "vulnerability", "firewall", "breach", "payload", "botnet", "cve",
    ],
    "جاسوسی": [
        "جاسوس", "جاسوسی", "ضدجاسوسی", "ضد جاسوسی", "موساد", "سیا", "ام‌آی‌۶",
        "سرویس اطلاعاتی", "سرویس بیگانه", "عامل نفوذی", "ستون پنجم", "تخلیه اطلاعاتی",
        "استراق سمع", "شنود", "خانه امن", "تله اطلاعاتی", "افشای اسناد", "فوق محرمانه",
        "به‌کلی سری", "به کلی سری", "مامور مخفی", "مأمور مخفی", "رابط اطلاعاتی",
        "سرپل", "پوشش دیپلماتیک", "خرابکاری صنعتی", "کشف شبکه جاسوسی",
        "espionage", "spy", "mossad", "cia", "mi6", "intelligence agency",
        "undercover", "classified", "top secret", "wiretap", "informant",
    ],
    "امنیتی": [
        "امنیتی", "امنیت ملی", "اطلاعات", "وزارت اطلاعات", "سازمان اطلاعات", "ضدتروریسم",
        "ضد تروریسم", "تروریستی", "ترور", "حفاظت اطلاعات", "فراجا", "انتظامی", "پلیس",
        "تهدید امنیتی", "بازداشت", "دستگیری", "شبکه سازمان‌یافته", "قاچاق سلاح",
        "اخلالگر", "شورش", "ناامنی", "عملیات امنیتی", "شورای عالی امنیت", "شورای تامین",
        "پاکسازی", "تعقیب و مراقبت", "کشف محموله", "اشرار", "گروهک",
        "security", "national security", "counterterrorism", "police", "threat",
        "arrest", "operation", "surveillance", "intelligence",
    ],
    "سیاسی": [
        "سیاسی", "دولت", "مجلس", "انتخابات", "دیپلماسی", "وزارت خارجه", "مذاکرات",
        "توافق", "برجام", "بین‌الملل", "بین الملل", "سازمان ملل", "شورای امنیت",
        "احزاب", "فراکسیون", "ریاست‌جمهوری", "ریاست جمهوری", "نخست‌وزیر", "سفارت",
        "سفیر", "قطعنامه", "تحریم سیاسی", "سیاست خارجی", "سیاست داخلی", "کابینه",
        "وزیر", "نماینده مجلس", "استیضاح", "رای اعتماد", "واشنگتن", "مسکو", "پکن",
        "قرارداد همکاری", "تفاهم‌نامه", "تفاهم نامه", "حقوقی", "ماده اول", "فسخ قرارداد",
        "political", "politics", "diplomacy", "parliament", "election", "government",
        "embassy", "treaty", "sanctions", "united nations", "foreign policy", "contract",
    ],
    "اقتصادی": [
        "اقتصادی", "اقتصاد", "بازار", "بورس", "ارز", "دلار", "یورو", "طلا", "سکه",
        "تورم", "بانک", "بانکی", "مالیات", "ارزش افزوده", "بودجه", "صادرات", "واردات",
        "تجارت", "گمرک", "سرمایه‌گذاری", "سرمایه گذاری", "قیمت", "کالا", "تولید",
        "صنعت", "کارخانه", "معیشت", "فاکتور", "صورتحساب", "صورت‌حساب", "مالي", "مالی",
        "مبلغ", "ریال", "تومان", "پرداخت", "حسابداری", "ترازنامه", "نفت", "پتروشیمی",
        "یارانه", "تسهیلات", "وام", "نقدینگی", "ركود", "رکود",
        "economy", "economic", "market", "currency", "inflation", "bank", "invoice",
        "payment", "tax", "finance", "financial", "trade", "export", "import", "budget",
    ],
    "دین و روحانیت": [
        "دین", "دینی", "مذهبی", "روحانیت", "روحانی", "حوزه علمیه", "مرجعیت", "مراجع",
        "آیت‌الله", "آیت الله", "حجت‌الاسلام", "حجت الاسلام", "فقه", "فقهی", "قرآن",
        "مسجد", "هیئت", "مداحی", "نماز", "نماز جمعه", "امام جمعه", "تبلیغات اسلامی",
        "زیارت", "اربعین", "محرم", "عاشورا", "رمضان", "اعتقادی", "طلبه", "علما",
        "حدیث", "روایت", "مهدویت", "وقف", "امامزاده", "حرم", "شعائر",
        "religion", "religious", "clergy", "seminary", "mosque", "quran", "islamic",
    ],
    "علم و فناوری": [
        "علم", "علمی", "فناوری", "تکنولوژی", "هوش مصنوعی", "نانو", "زیست‌فناوری",
        "فضایی", "ماهواره", "پرتابگر", "دانشگاه", "پژوهش", "پژوهشی", "اختراع",
        "دانش‌بنیان", "دانش بنیان", "رباتیک", "کوانتوم", "پزشکی نوین", "سلول بنیادی",
        "آزمایشگاه", "الگوریتم", "نرم‌افزار", "نرم افزار", "سخت‌افزار", "پردازنده",
        "مقاله علمی", "پارک علم و فناوری", "استارتاپ", "نوآوری", "مخابرات", "لیزر",
        "science", "technology", "ai", "artificial intelligence", "satellite",
        "research", "university", "innovation", "robotics", "quantum", "software",
    ],
    "فرهنگی": [
        "فرهنگی", "فرهنگ", "هنر", "هنری", "سینما", "فیلم", "سریال", "کتاب", "نشر",
        "رسانه", "میراث فرهنگی", "گردشگری", "شعر", "ادبیات", "تئاتر", "موسیقی",
        "جشنواره", "فجر", "سبک زندگی", "تاریخ", "تاریخی", "هویت فرهنگی", "صداوسیما",
        "مطبوعات", "نمایشگاه", "نگارخانه", "موزه", "خطاطی", "معماری ایرانی",
        "ابتذال", "ترویج ابتذال", "مبتذل", "هنجارشکنی", "عفاف", "حجاب", "کشف حجاب",
        "مدلینگ", "بلاگر", "مزون", "سالن زیبایی", "آرایشگاه", "استوری", "ریلز",
        "اینستاگرام", "instagram.com", "مسدودی سیم کارت",
        "culture", "cultural", "art", "cinema", "book", "media", "heritage",
        "literature", "music", "festival", "museum", "instagram", "blogger",
    ],
    "اجتماعی": [
        "اجتماعی", "جامعه", "شهروند", "شهروندان", "خانواده", "جمعیت", "جوانان",
        "زنان", "بهداشت", "سلامت", "بیمارستان", "آموزش و پرورش", "مدرسه", "دانش‌آموز",
        "حوادث", "امداد", "هلال احمر", "محیط زیست", "آلودگی هوا", "ترافیک", "شهرداری",
        "خدمات شهری", "مسکن", "رفاه", "تامین اجتماعی", "بازنشستگان", "کارگران",
        "مطالبات مردمی", "آسیب اجتماعی", "خیریه", "مردم", "زندگی", "همگانی",
        "ناهنجاری اجتماعی", "تخلف اجتماعی", "مسدودی سیم کارت", "سیم کارت", "کدملی",
        "شماره تماس", "شماره تماس/حساب", "تاریخ ارشاد", "آیدی عددی", "آدرس اینترنتی",
        "مسدودسازی", "کاشمر", "خراسان رضوی",
        "social", "society", "citizen", "family", "health", "environment", "urban",
    ],
}

_HANDLE_REGEX = re.compile(
    r"(?:(?<![A-Za-z0-9._])@([A-Za-z][A-Za-z0-9_.]{2,36})|(?<![A-Za-z0-9._@])([A-Za-z][A-Za-z0-9_.]{2,36})@(?![A-Za-z0-9_.]))"
)
_SOCIAL_URL_REGEX = re.compile(
    r"(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me|instagram\.com|instagr\.am|x\.com|twitter\.com|eitaa\.com|rubika\.ir|bale\.ai|splus\.ir)/([A-Za-z0-9_.]{3,40})(?:\?[^\s\"'<>)]*)?",
    re.IGNORECASE,
)
_FULL_INSTAGRAM_URL_REGEX = re.compile(
    r"(https?://(?:www\.)?(?:instagram\.com|instagr\.am)/[A-Za-z0-9_.]+(?:\?[^\s\"'<>)]*)?|(?:www\.)?(?:instagram\.com|instagr\.am)/[A-Za-z0-9_.]+(?:\?[^\s\"'<>)]*)?)",
    re.IGNORECASE,
)
_EXPLICIT_ID_LINE_REGEX = re.compile(
    r"(?:آیدی|ایدی|شناسه(?:\s*کاربری)?|نام\s*کاربری|اکانت|کانال|صفحه|پیج|کاربر|منبع|id|user\s*id|username|account|channel)\s*[:：\-]\s*([^\n\r|·•]{2,50})",
    re.IGNORECASE,
)

_PERSIAN_DIGIT_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def _to_ascii_digits(text: str) -> str:
    return (text or "").translate(_PERSIAN_DIGIT_MAP)


def _extract_handles_from_text(text: str) -> List[str]:
    raw_pairs = _HANDLE_REGEX.findall(text or "")
    out: List[str] = []
    for g1, g2 in raw_pairs:
        h = (g1 or g2 or "").rstrip("._")
        if h.lower() not in ("vite", "react", "types", "playwright", "gmail", "yahoo", "outlook", "example") and len(h) >= 3:
            out.append(h)
    return out


def _extract_account_identity(
    title: str,
    relative_path: str,
    norm_text: str,
    source_url: str = "",
) -> Tuple[str, str, str, str]:
    """
    Priority 1 Classifier: Extracts the Screenshot's Account ID (@handle / ID)
    and Username / Channel Name, plus the detected social/messenger platform.
    Returns: (account_id, account_username, account_label, platform_source)
    """
    combined_meta = f"{source_url} {relative_path} {title}"
    full_text = f"{norm_text}\n{combined_meta}"
    lower_all = full_text.lower()

    # 1. Detect platform source
    if any(k in lower_all for k in ("instagram", "instagr.am", "اینستاگرام", "followers", "following", "دنبال‌کننده", "پست", "استوری", "ریلز")):
        platform_source = "اینستاگرام (Instagram)"
    elif any(k in lower_all for k in ("telegram", "t.me", "تلگرام", "فوروارد", "forwarded from", "subscribers", "مشترک")):
        platform_source = "تلگرام (Telegram)"
    elif any(k in lower_all for k in ("twitter", "x.com", "توییتر", "ایکس", "retweet", "ری‌پست")):
        platform_source = "ایکس / توییتر (X)"
    elif any(k in lower_all for k in ("eitaa", "rubika", "bale.ai", "splus", "ایتا", "روبیکا", "بله", "سروش")):
        platform_source = "پیام‌رسان بومی (ایتا/روبیکا/بله)"
    elif any(k in lower_all for k in ("whatsapp", "واتساپ", "واتس‌اپ")):
        platform_source = "واتس‌اپ (WhatsApp)"
    else:
        platform_source = "اسکرین‌شات / تصویر عمومی"

    account_id = ""
    account_username = ""

    # 2. Check for social URLs first if an Instagram/Telegram link was provided or found in text
    url_matches = _SOCIAL_URL_REGEX.findall(full_text)
    if url_matches:
        for cand in url_matches:
            clean_u = cand.rstrip("._/")
            if clean_u.lower() not in ("joinchat", "share", "intent", "home", "explore", "p", "reel", "reels", "stories"):
                account_id = f"@{clean_u}"
                break

    # 3. Check for @handle (or RTL BiDi-flipped handle@) in OCR text or relative_path / filename
    if not account_id:
        filtered_handles = _extract_handles_from_text(full_text)
        if filtered_handles:
            account_id = f"@{filtered_handles[0]}"

    # 4. Check explicit labels ("نام کاربری: ...", "آیدی: ...", "کانال: ...", "ID: ...")
    lines = [ln.strip() for ln in (norm_text or "").splitlines() if ln.strip()]
    for ln in lines[:15]:
        # Ignore purely numeric IDs ("آیدی عددی: 123456") when extracting @handle
        if re.search(r"(?:آیدی|ایدی|شناسه)\s*عددی", ln):
            continue
        for m in _EXPLICIT_ID_LINE_REGEX.finditer(ln):
            val = m.group(1).strip().strip("«»\"'()[]")
            if not val or val.isdigit():
                continue
            handles_in_val = _extract_handles_from_text(val)
            if handles_in_val and not account_id:
                account_id = f"@{handles_in_val[0]}"
                rem = _HANDLE_REGEX.sub("", val).strip(" -–—:()[]")
                if rem and not account_username:
                    account_username = rem[:40]
            elif (val.startswith("@") or val.endswith("@")) and not account_id:
                clean_handle = val.split()[0].strip("@")[:40]
                if clean_handle and not clean_handle.isdigit():
                    account_id = f"@{clean_handle}"
            elif re.match(r"^[A-Za-z][A-Za-z0-9_.-]{2,35}$", val) and not account_id:
                account_id = f"@{val}"
            elif not account_username:
                account_username = val[:40]

    # 5. Check folder hierarchy if organized by account folder (e.g. "accounts/@sepah_news/shot1.png" or "user_ali_reza/img.png")
    if relative_path and "/" in relative_path:
        parts = [p.strip() for p in relative_path.replace("\\", "/").split("/")[:-1] if p.strip()]
        for part in parts:
            if part.startswith("@") and len(part) >= 4 and not account_id:
                account_id = part[:40]
            elif re.match(r"^(?:id|user|account|channel)[_-]([A-Za-z0-9_.-]{2,35})$", part, re.IGNORECASE):
                extracted = re.sub(r"^(?:id|user|account|channel)[_-]", "", part, flags=re.IGNORECASE)
                if not account_id:
                    account_id = f"@{extracted}"
            elif not account_username and len(parts) >= 2 and part == parts[-1]:
                account_username = part[:40]

    # 6. Check filename pattern like "@handle_2026.png" or "id_cyber_ir__01.png" or "mira_rjbpr_01.png"
    base_no_ext = os.path.splitext(os.path.basename(title))[0]
    if not account_id:
        m_file_id = re.search(r"(?:^|[_ -])(?:id|user|account|channel)[_ -]([A-Za-z0-9_.]{3,32})", base_no_ext, re.IGNORECASE)
        if m_file_id:
            account_id = f"@{m_file_id.group(1)}"

    # 7. If we found an account_id in OCR text, look for a companion display name on the same or first header line
    if account_id and not account_username and lines:
        raw_handle = account_id.lstrip("@")
        for idx, ln in enumerate(lines[:6]):
            if raw_handle in ln and "http" not in ln.lower() and "instagram.com" not in ln.lower():
                cleaned_line = re.sub(r"@?[A-Za-z0-9_.]{3,40}", "", ln)
                cleaned_line = re.sub(
                    r"(?:آیدی|ایدی|شناسه|نام کاربری|کانال|صفحه|پیج|کاربر|id|username|channel|account)\s*[:：\-]?",
                    "",
                    cleaned_line,
                    flags=re.IGNORECASE,
                ).strip(" -–—:()[]«»|·•")
                if 2 <= len(cleaned_line) <= 42:
                    account_username = cleaned_line
                    break
        if not account_username and len(lines[0]) <= 38 and raw_handle not in lines[0] and "http" not in lines[0].lower():
            first_candidate = lines[0].strip(" -–—:()[]«»|·•")
            if 2 <= len(first_candidate) <= 35 and ":" not in first_candidate:
                account_username = first_candidate

    # Build unified Priority-1 Account Label
    if account_id and account_username and account_username.lower() != account_id.lstrip("@").lower():
        account_label = f"{account_id} ({account_username})"
    elif account_id:
        account_label = account_id
        if not account_username:
            account_username = account_id.lstrip("@")
    elif account_username:
        account_label = f"کاربر / کانال: {account_username}"
        account_id = account_username
    else:
        account_label = "بدون نام کاربری / آیدی مشخص"

    return account_id, account_username, account_label, platform_source


_OCCUPATION_KEYWORDS = [
    "بلاگر", "مدل", "مدلینگ", "آرایشگر", "سالن زیبایی", "میکاپ آرتیست", "میکاپ",
    "مزون", "طراح لباس", "بوتیک", "فروشگاه آنلاین", "فروشگاه پوشاک", "عکاس", "آتلیه",
    "مربی", "مربی بدنسازی", "باشگاه", "تتو آرتیست", "تتوکار", "تتو", "خواننده",
    "موزیسین", "دی‌جی", "کافه", "رستوران", "مشاور", "پزشک", "وکیل", "دانشجو", "آزاد",
]

_PROVINCE_HASHTAG_MAP = {
    "خراسان رضوی": "#خراسان_رضوی",
    "خراسان شمالی": "#خراسان_شمالی",
    "خراسان جنوبی": "#خراسان_جنوبی",
    "تهران": "#تهران",
    "اصفهان": "#اصفهان",
    "فارس": "#فارس",
    "مازندران": "#مازندران",
    "گیلان": "#گیلان",
    "آذربایجان شرقی": "#آذربایجان_شرقی",
    "آذربایجان غربی": "#آذربایجان_غربی",
    "خوزستان": "#خوزستان",
    "کرمان": "#کرمان",
    "البرز": "#البرز",
    "قم": "#قم",
    "یزد": "#یزد",
    "همدان": "#همدان",
    "کرمانشاه": "#کرمانشاه",
    "لرستان": "#لرستان",
    "هرمزگان": "#هرمزگان",
    "سیستان و بلوچستان": "#سیستان_و_بلوچستان",
    "کردستان": "#کردستان",
    "مرکزی": "#مرکزی",
    "قزوین": "#قزوین",
    "گلستان": "#گلستان",
    "اردبیل": "#اردبیل",
    "زنجان": "#زنجان",
    "بوشهر": "#بوشهر",
    "سمنان": "#سمنان",
    "چهارمحال و بختیاری": "#چهارمحال_و_بختیاری",
    "ایلام": "#ایلام",
    "کهگیلویه و بویراحمد": "#کهگیلویه_و_بویراحمد",
}

_CITY_TO_PROVINCE_AND_TAG = {
    "کاشمر": ("#خراسان_رضوی", "#شهرستان_کاشمر"),
    "مشهد": ("#خراسان_رضوی", "#شهرستان_مشهد"),
    "نیشابور": ("#خراسان_رضوی", "#شهرستان_نیشابور"),
    "سبزوار": ("#خراسان_رضوی", "#شهرستان_سبزوار"),
    "تربت حیدریه": ("#خراسان_رضوی", "#شهرستان_تربت_حیدریه"),
    "قوچان": ("#خراسان_رضوی", "#شهرستان_قوچان"),
    "بردسکن": ("#خراسان_رضوی", "#شهرستان_بردسکن"),
    "خلیل آباد": ("#خراسان_رضوی", "#شهرستان_خلیل_آباد"),
    "خلیل‌آباد": ("#خراسان_رضوی", "#شهرستان_خلیل_آباد"),
    "طرقبه": ("#خراسان_رضوی", "#شهرستان_طرقبه_شاندیز"),
    "شاندیز": ("#خراسان_رضوی", "#شهرستان_طرقبه_شاندیز"),
    "شیراز": ("#فارس", "#شهرستان_شیراز"),
    "تبریز": ("#آذربایجان_شرقی", "#شهرستان_تبریز"),
    "اهواز": ("#خوزستان", "#شهرستان_اهواز"),
    "رشت": ("#گیلان", "#شهرستان_رشت"),
    "ساری": ("#مازندران", "#شهرستان_ساری"),
    "کرج": ("#البرز", "#شهرستان_کرج"),
}


def format_cultural_template(fields: Dict[str, Any]) -> str:
    """
    Formats Template 1 (قوارهٔ ۱ — فرهنگی: ترویج ابتذال / درخواست مسدودی سیم کارت):

    نام و نام خانوادگی: ...
    کدملی: ...
    شماره تماس: ...
    شغل: ...
    تخلف: ترویج ابتذال
    درخواست مسدودی سیم کارت
    https://www.instagram.com/...

    #ابتذال 
    #خراسان_رضوی 
    #شهرستان_کاشمر
    """
    full_name = (fields.get("full_name") or "").strip()
    national_id = (fields.get("national_id") or "").strip()
    phone_number = (fields.get("phone_number") or "").strip()
    occupation = (fields.get("occupation") or "").strip()
    violation = (fields.get("violation") or "ترویج ابتذال").strip() or "ترویج ابتذال"
    action_request = (fields.get("action_request") or "درخواست مسدودی سیم کارت").strip() or "درخواست مسدودی سیم کارت"
    profile_url = (fields.get("profile_url") or "").strip()
    hashtags = fields.get("hashtags") or ["#ابتذال", "#خراسان_رضوی", "#شهرستان_کاشمر"]
    if isinstance(hashtags, str):
        hashtags = [h.strip() for h in hashtags.split() if h.strip()]

    lines = [
        f"نام و نام خانوادگی: {full_name}",
        f"کدملی: {national_id}",
        f"شماره تماس: {phone_number}",
        f"شغل: {occupation}",
        f"تخلف: {violation}",
        action_request,
    ]
    if profile_url:
        lines.append(profile_url)
    lines.append("")
    for tag in hashtags:
        clean_tag = tag if tag.startswith("#") else f"#{tag}"
        lines.append(clean_tag)

    return "\n".join(lines)


def format_social_blocking_template(fields: Dict[str, Any]) -> str:
    """
    Formats Template 2 (قوارهٔ ۲ — ویژهٔ دسته‌بندی اجتماعی: #مسدودسازی #اینستاگرام):

    〰️〰️〰️〰️〰️〰️〰️〰️〰️
    #مسدودسازی
    #اینستاگرام

    ✅نام و نام خانوادگی: 
    ✅کدملی: 
    ✅ شماره تماس/حساب: 
    ✅ تاریخ ارشاد: 
    ✅ آیدی عددی: 
    ✅ آدرس اینترنتی:
    @
    توضیحات:
     

    #کاشمر
    〰️〰️〰️〰️〰️〰️〰️〰️〰️
    """
    full_name = (fields.get("full_name") or "").strip()
    national_id = (fields.get("national_id") or "").strip()
    phone_number = (fields.get("phone_number") or "").strip()
    guidance_date = (fields.get("guidance_date") or "").strip()
    numeric_id = (fields.get("numeric_id") or "").strip()
    profile_url = (fields.get("profile_url") or "").strip()

    raw_handle = (fields.get("account_handle") or "").strip().lstrip("@")
    if not raw_handle and profile_url:
        m_u = _SOCIAL_URL_REGEX.search(profile_url)
        if m_u:
            raw_handle = m_u.group(1).rstrip("._/")
    handle_line = f"@{raw_handle}" if raw_handle else "@"

    description = (fields.get("description") or "").strip()
    city_hashtag = (fields.get("city_hashtag") or "#کاشمر").strip() or "#کاشمر"
    if not city_hashtag.startswith("#"):
        city_hashtag = f"#{city_hashtag}"

    lines = [
        "〰️〰️〰️〰️〰️〰️〰️〰️〰️",
        "#مسدودسازی",
        "#اینستاگرام",
        "",
        f"✅نام و نام خانوادگی: {full_name}",
        f"✅کدملی: {national_id}",
        f"✅ شماره تماس/حساب: {phone_number}",
        f"✅ تاریخ ارشاد: {guidance_date}",
        f"✅ آیدی عددی: {numeric_id}",
        f"✅ آدرس اینترنتی: {profile_url}" if profile_url else "✅ آدرس اینترنتی:",
        handle_line,
        f"توضیحات: {description}",
        "",
        city_hashtag,
        "〰️〰️〰️〰️〰️〰️〰️〰️〰️",
    ]
    return "\n".join(lines)


def format_cultural_social_template(fields: Dict[str, Any], thematic_category: str = "") -> str:
    """
    Produces the combined formatted template text for Cultural (فرهنگی) and Social (اجتماعی)
    categories so both Template 1 (فرهنگی) and Template 2 (اجتماعی — #مسدودسازی) are
    populated and ordered according to the image's primary thematic category.
    """
    cultural_txt = format_cultural_template(fields)
    social_txt = format_social_blocking_template(fields)
    fields["cultural_template_text"] = cultural_txt
    fields["social_template_text"] = social_txt

    if thematic_category == "اجتماعی":
        return f"{social_txt}\n\n{cultural_txt}"
    return f"{cultural_txt}\n\n{social_txt}"


def build_cultural_social_template(
    norm_text: str,
    account_id: str,
    account_username: str,
    relative_path: str = "",
    source_url: str = "",
    overrides: Optional[Dict[str, Any]] = None,
    thematic_category: str = "",
) -> Tuple[Dict[str, Any], str]:
    """
    Extracts the fields for both Cultural (فرهنگی) and Social (اجتماعی) report templates
    from screenshot OCR text, account handle, and Instagram URL.
    """
    overrides = overrides or {}
    ascii_text = _to_ascii_digits(norm_text or "")
    combined_source = f"{source_url}\n{norm_text or ''}\n{relative_path or ''}"

    # 1. Extract Full Name (نام و نام خانوادگی)
    full_name = ""
    m_name = re.search(
        r"(?:نام\s*و\s*نام\s*خانوادگی|نام\s*کامل|هویت|نام\s*صاحب\s*صفحه)\s*[:：\-]\s*([^\n\r|·•✅]{2,45})",
        norm_text or "",
    )
    if m_name:
        cand = m_name.group(1).strip()
        if not any(cand.startswith(k) for k in ("کدملی", "کد ملی", "شماره", "شغل", "تخلف", "تاریخ", "آیدی")):
            full_name = cand
    if not full_name:
        m_first = re.search(r"(?:^|\n)\s*(?:✅\s*)?نام\s*[:：\-]\s*([^\n\r|·•✅]{2,25})", norm_text or "")
        m_last = re.search(r"(?:^|\n)\s*(?:✅\s*)?نام\s*خانوادگی\s*[:：\-]\s*([^\n\r|·•✅]{2,30})", norm_text or "")
        if m_first and m_last:
            full_name = f"{m_first.group(1).strip()} {m_last.group(1).strip()}".strip()
        elif m_first:
            full_name = m_first.group(1).strip()

    if not full_name and account_username:
        clean_u = account_username.strip("@ ")
        # If account_username contains Persian letters (display name from profile header)
        if re.search(r"[\u0600-\u06FF]", clean_u) and clean_u not in ("بدون نام کاربری / آیدی مشخص", "نامشخص"):
            if not any(k in clean_u for k in ("نام و نام خانوادگی", "کدملی", "شماره تماس", "تخلف", "تاریخ ارشاد", "آیدی عددی")):
                full_name = clean_u

    # 2. Extract National ID (کدملی)
    national_id = ""
    m_nid = re.search(
        r"(?:کد\s*ملی|کدملی|شماره\s*ملی)\s*[:：\-]?\s*(\d{8,10})",
        ascii_text,
    )
    if m_nid:
        national_id = m_nid.group(1).strip()
    else:
        for m10 in re.finditer(r"(?<!\d)(\d{10})(?!\d)", ascii_text):
            cand_10 = m10.group(1)
            if not cand_10.startswith(("09", "98")):
                national_id = cand_10
                break

    # 3. Extract Phone Number / Account Number (شماره تماس / شماره تماس/حساب)
    phone_number = ""
    m_phone_lbl = re.search(
        r"(?:شماره\s*تماس\s*/\s*حساب|شماره\s*تماس|شماره\s*حساب|شماره\s*کارت|شماره\s*همراه|شماره\s*موبایل|تلفن\s*همراه|شماره\s*تلفن|موبایل|همراه|تلفن)\s*[:：\-]?\s*(\+?\d[\d\-\s]{7,18}\d)",
        ascii_text,
    )
    if m_phone_lbl:
        phone_number = re.sub(r"[\s\-]", "", m_phone_lbl.group(1))
    else:
        m_mob = re.search(r"(?<!\d)((?:\+98|0098|0)9\d{9})(?!\d)", re.sub(r"[\s\-]", "", ascii_text))
        if m_mob:
            raw_mob = m_mob.group(1)
            if raw_mob.startswith("+98"):
                raw_mob = "0" + raw_mob[3:]
            elif raw_mob.startswith("0098"):
                raw_mob = "0" + raw_mob[4:]
            phone_number = raw_mob

    # 4. Extract Guidance Date (تاریخ ارشاد)
    guidance_date = ""
    m_gdate = re.search(
        r"(?:تاریخ\s*ارشاد|تاریخ\s*تذکر|تاریخ\s*احضار|تاریخ\s*ابلاغ)\s*[:：\-]?\s*([^\n\r|·•✅]{3,30})",
        ascii_text,
    )
    if m_gdate:
        cand_date = m_gdate.group(1).strip()
        if not any(cand_date.startswith(k) for k in ("آیدی", "ایدی", "آدرس", "توضیحات")):
            guidance_date = cand_date
    if not guidance_date:
        m_solar = re.search(r"\b(1[34]\d{2}/[01]?\d/[0-3]?\d)\b", ascii_text)
        if m_solar:
            guidance_date = m_solar.group(1)

    # 5. Extract Numeric ID (آیدی عددی)
    numeric_id = ""
    m_num_id = re.search(
        r"(?:آیدی\s*عددی|ایدی\s*عددی|شناسه\s*عددی|کد\s*عددی|numeric\s*id|user\s*id)\s*[:：\-]?\s*(\d{4,18})",
        ascii_text,
        re.IGNORECASE,
    )
    if m_num_id:
        numeric_id = m_num_id.group(1).strip()

    # 6. Extract Occupation (شغل)
    occupation = ""
    m_occ = re.search(
        r"(?:شغل|حرفه|صنف|زمینه\s*فعالیت|فعالیت)\s*[:：\-]\s*([^\n\r|·•✅]{2,40})",
        norm_text or "",
    )
    if m_occ:
        cand_occ = m_occ.group(1).strip()
        if not any(cand_occ.startswith(k) for k in ("تخلف", "درخواست", "شماره", "کدملی", "تاریخ", "آیدی")):
            occupation = cand_occ
    if not occupation:
        for occ_kw in _OCCUPATION_KEYWORDS:
            if occ_kw in (norm_text or ""):
                occupation = occ_kw
                break

    # 7. Extract Violation (تخلف) — defaults to «ترویج ابتذال»
    violation = "ترویج ابتذال"
    m_viol = re.search(
        r"تخلف\s*[:：\-]\s*([^\n\r|·•✅]{2,50})",
        norm_text or "",
    )
    if m_viol and m_viol.group(1).strip():
        violation = m_viol.group(1).strip()
    elif "کشف حجاب" in (norm_text or "") and "ابتذال" not in (norm_text or ""):
        violation = "کشف حجاب و ترویج ابتذال"

    # 8. Action request line — defaults to «درخواست مسدودی سیم کارت»
    action_request = "درخواست مسدودی سیم کارت"
    m_act = re.search(r"(درخواست\s+مسدود[^\n\r]{2,40})", norm_text or "")
    if m_act:
        action_request = m_act.group(1).strip()

    # 9. Instagram / Profile URL & @handle
    profile_url = ""
    m_ig = _FULL_INSTAGRAM_URL_REGEX.search(combined_source)
    if m_ig:
        raw_url = m_ig.group(1).strip().rstrip(".,;)")
        if not raw_url.lower().startswith("http"):
            raw_url = "https://" + raw_url
        profile_url = raw_url
    elif source_url and source_url.strip():
        s_url = source_url.strip()
        if not s_url.lower().startswith("http") and "instagram.com" in s_url.lower():
            s_url = "https://" + s_url
        profile_url = s_url
    elif account_id and account_id != "نامشخص":
        clean_handle = account_id.lstrip("@").strip()
        if re.match(r"^[A-Za-z0-9_.]{2,40}$", clean_handle):
            profile_url = f"https://www.instagram.com/{clean_handle}"

    account_handle = ""
    if account_id and account_id != "نامشخص" and re.match(r"^@?[A-Za-z0-9_.]{2,40}$", account_id.strip()):
        account_handle = f"@{account_id.strip().lstrip('@')}"
    elif profile_url:
        m_u = _SOCIAL_URL_REGEX.search(profile_url)
        if m_u:
            account_handle = f"@{m_u.group(1).rstrip('._/')}"

    # 10. Extract Description (توضیحات)
    description = ""
    m_desc = re.search(
        r"(?:توضیحات|شرح\s*تخلف|ملاحظات)\s*[:：\-]\s*([^\n\r✅#]{2,140})",
        norm_text or "",
    )
    if m_desc and m_desc.group(1).strip():
        description = m_desc.group(1).strip()
    elif occupation and violation:
        description = f"{occupation} - {violation}"
    elif violation:
        description = violation

    # 11. Extract or infer Hashtags (#ابتذال, #خراسان_رضوی, #شهرستان_کاشمر) and City Hashtag (#کاشمر)
    found_hashtags: List[str] = []
    for m_tag in re.finditer(r"#([\w\u0600-\u06FF_]{2,40})", combined_source):
        tag_str = f"#{m_tag.group(1)}"
        if tag_str not in found_hashtags and tag_str not in ("#مسدودسازی", "#اینستاگرام"):
            found_hashtags.append(tag_str)

    detected_prov = ""
    detected_city_tag = ""
    detected_short_city_tag = "#کاشمر"
    for city_name, (prov_tag, city_tag) in _CITY_TO_PROVINCE_AND_TAG.items():
        if city_name in combined_source:
            detected_prov = prov_tag
            detected_city_tag = city_tag
            detected_short_city_tag = f"#{city_name.replace(' ', '_')}"
            break

    if not found_hashtags:
        found_hashtags.append("#ابتذال")
        if not detected_prov:
            for prov_name, prov_tag in _PROVINCE_HASHTAG_MAP.items():
                if prov_name in combined_source:
                    detected_prov = prov_tag
                    break
        m_county = re.search(r"شهرستان\s+([\u0600-\u06FF\s]{2,20})", combined_source)
        if m_county and not detected_city_tag:
            c_name = m_county.group(1).strip().split()[0]
            detected_city_tag = f"#شهرستان_{c_name}"
            detected_short_city_tag = f"#{c_name}"

        found_hashtags.append(detected_prov or "#خراسان_رضوی")
        found_hashtags.append(detected_city_tag or "#شهرستان_کاشمر")

    fields: Dict[str, Any] = {
        "full_name": overrides.get("full_name") if overrides.get("full_name") is not None else full_name,
        "national_id": overrides.get("national_id") if overrides.get("national_id") is not None else national_id,
        "phone_number": overrides.get("phone_number") if overrides.get("phone_number") is not None else phone_number,
        "guidance_date": overrides.get("guidance_date") if overrides.get("guidance_date") is not None else guidance_date,
        "numeric_id": overrides.get("numeric_id") if overrides.get("numeric_id") is not None else numeric_id,
        "account_handle": overrides.get("account_handle") if overrides.get("account_handle") is not None else account_handle,
        "description": overrides.get("description") if overrides.get("description") is not None else description,
        "city_hashtag": overrides.get("city_hashtag") or detected_short_city_tag or "#کاشمر",
        "occupation": overrides.get("occupation") if overrides.get("occupation") is not None else occupation,
        "violation": overrides.get("violation") or violation,
        "action_request": overrides.get("action_request") or action_request,
        "profile_url": overrides.get("profile_url") if overrides.get("profile_url") is not None else profile_url,
        "hashtags": overrides.get("hashtags") or found_hashtags,
    }
    formatted = format_cultural_social_template(fields, thematic_category=thematic_category)
    return fields, formatted


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


def _classify_nature_and_12_categories(
    title: str,
    relative_path: str,
    norm_text: str,
    visual: Dict[str, Any],
    word_count: int,
    line_count: int,
    account_id: str,
    account_label: str,
) -> Tuple[str, str, List[str]]:
    """
    Determines:
    1. `image_nature` (ماهیت بصری تصویر / اسکرین‌شات)
    2. `thematic_category` (یکی از ۱۲ دسته‌بندی موضوعی مشخص‌شده پس از تفکیک نام کاربری/آیدی):
       - اجتماعی
       - اقتصادی
       - امنیتی
       - جاسوسی
       - دفاعی (نظامی، کویر و مرز)
       - دین و روحانیت
       - رزمایش
       - سایبری
       - سیاسی
       - علم و فناوری
       - فرهنگی
       - هواگرد (پهپاد، ریزپرنده، جنگنده و ...)
    3. `tags` (برچسب‌های تحلیلی شامل آیدی/نام کاربری و دسته‌بندی موضوعی)
    """
    combined_lower = f"{relative_path} {title} {norm_text}".lower()
    digits_found = len(re.findall(r"\d", combined_lower))

    # Score the 12 thematic categories
    cat_scores: Dict[str, int] = {k: 0 for k in THEMATIC_CATEGORIES_12}
    matched_keywords: List[str] = []

    for cat, kw_list in _THEMATIC_KEYWORDS_12.items():
        for kw in kw_list:
            if kw in combined_lower:
                weight = 4 if kw in norm_text.lower() else 2
                # Boost highly specific multi-word or domain terms
                if len(kw) >= 6:
                    weight += 1
                cat_scores[cat] += weight
                if len(kw) >= 3 and kw not in matched_keywords and not kw.isascii():
                    matched_keywords.append(kw)

    paper_ratio = visual["paper_bg_ratio"]
    dark_ratio = visual["dark_bg_ratio"]
    mean_sat = visual["mean_saturation"]
    ratio = visual["aspect_ratio"]
    edge_density = visual["edge_density"]

    is_screenshot_name = any(
        w in combined_lower
        for w in ("screenshot", "screen", "اسکرین", "نماگرفت", "capture", "snap", "shot")
    ) or bool(account_id)

    has_econ_terms = cat_scores["اقتصادی"] >= 4
    has_pol_legal_terms = cat_scores["سیاسی"] >= 4
    has_cyber_terms = cat_scores["سایبری"] >= 4

    if has_econ_terms and (word_count >= 3 or digits_found >= 4) and paper_ratio >= 0.50:
        image_nature = "فاکتور، رسید یا صورت‌حساب مالی"
    elif any(w in combined_lower for w in ("قرارداد", "تفاهم‌نامه", "تفاهم نامه", "صورت‌جلسه", "حکم", "ابلاغیه")) and word_count >= 4:
        image_nature = "سند رسمی، قرارداد یا صورت‌جلسهٔ اسکن‌شده"
    elif is_screenshot_name or (dark_ratio >= 0.35 and word_count >= 2) or (ratio < 0.72 and word_count >= 3):
        if account_id:
            image_nature = f"اسکرین‌شات شبکهٔ اجتماعی / پیام‌رسان ({account_id})"
        else:
            image_nature = "اسکرین‌شات رابط کاربری یا پیام‌رسان"
    elif paper_ratio >= 0.55 and edge_density >= 0.14 and word_count < 25:
        image_nature = "نقشه، نمودار یا طرح فنی و عملیاتی"
    elif paper_ratio >= 0.55 and word_count >= 4:
        image_nature = "سند یا برگهٔ متنی اسکن‌شده"
    elif word_count >= 5:
        image_nature = "تصویر حاوی نوشتار و محتوای خبری / تحلیلی"
    else:
        if mean_sat >= 35:
            if ratio > 1.2:
                image_nature = "تصویر عکاسی یا منظره با کادر افقی (فاقد متن غالب)"
            else:
                image_nature = "تصویر عکاسی یا سوژهٔ بصری"
        else:
            image_nature = "تصویر گرافیکی یا نماگرفت بصری"

    # Choose the winning category among the 12 user-specified categories
    best_cat, best_score = max(cat_scores.items(), key=lambda kv: kv[1])
    if best_score >= 2:
        thematic_category = best_cat
    else:
        # Fallback within the 12 categories based on visual nature
        if "مالی" in image_nature or "فاکتور" in image_nature:
            thematic_category = "اقتصادی"
        elif "قرارداد" in image_nature:
            thematic_category = "سیاسی"
        elif "اسکرین‌شات" in image_nature and has_cyber_terms:
            thematic_category = "سایبری"
        elif "نقشه" in image_nature:
            thematic_category = "دفاعی (نظامی، کویر و مرز)"
        elif "عکاسی" in image_nature or "گرافیکی" in image_nature:
            thematic_category = "فرهنگی"
        else:
            thematic_category = "اجتماعی"

    # Build tags starting with Priority 1 (Account ID/Username) and Priority 2 (12 Category)
    tags: List[str] = []
    if account_id:
        tags.append(f"آیدی: {account_id}")
    elif account_label and account_label != "بدون نام کاربری / آیدی مشخص":
        tags.append(account_label)
    if thematic_category not in tags:
        tags.append(thematic_category)
    short_nature = image_nature.split("(")[0].strip()
    if short_nature and short_nature not in tags:
        tags.append(short_nature)
    for kw in matched_keywords[:4]:
        if kw not in tags:
            tags.append(kw)

    return image_nature, thematic_category, tags[:7]


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
    source_url: str = "",
    template_overrides: Optional[Dict[str, Any]] = None,
) -> ImageAnalysisResult:
    """
    Performs a two-level hierarchical analysis of a screenshot / image:
    - Priority 1: Username & Account ID (`account_id`, `account_username`, `account_label`)
    - Priority 2: 12 Thematic Categories (`اجتماعی`, `اقتصادی`, `امنیتی`, `جاسوسی`,
      `دفاعی (نظامی، کویر و مرز)`, `دین و روحانیت`, `رزمایش`, `سایبری`, `سیاسی`,
      `علم و فناوری`, `فرهنگی`, `هواگرد (پهپاد، ریزپرنده، جنگنده و ...)`)
    along with visual nature (`image_nature`), offline OCR text, and the structured
    report template (قواره) strictly for «فرهنگی» and «اجتماعی».
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

    account_id, account_username, account_label, platform_source = _extract_account_identity(
        title=title,
        relative_path=relative_path,
        norm_text=norm_text,
        source_url=source_url,
    )

    visual = _compute_visual_metrics(image_path)
    image_nature, thematic_category, tags = _classify_nature_and_12_categories(
        title=title,
        relative_path=f"{source_url} {relative_path}".strip(),
        norm_text=norm_text,
        visual=visual,
        word_count=word_count,
        line_count=line_count,
        account_id=account_id,
        account_label=account_label,
    )

    if (ocr_confidence and ocr_confidence >= 80) or word_count >= 8 or visual["paper_bg_ratio"] >= 0.7:
        confidence_label = "بالا"
    elif word_count >= 2 or visual["width"] >= 200:
        confidence_label = "متوسط"
    else:
        confidence_label = "پایین (تصویر بسیار کوچک یا فاقد جزئیات)"

    # Strictly apply the structured Cultural & Social template ONLY for «فرهنگی» and «اجتماعی»
    template_applicable = thematic_category in ("فرهنگی", "اجتماعی")
    template_fields: Optional[Dict[str, Any]] = None
    formatted_template_text = ""

    if template_applicable:
        template_fields, formatted_template_text = build_cultural_social_template(
            norm_text=norm_text,
            account_id=account_id,
            account_username=account_username,
            relative_path=relative_path,
            source_url=source_url,
            overrides=template_overrides,
            thematic_category=thematic_category,
        )

    key_findings: List[str] = [
        f"اولویت اول دسته‌بندی (نام کاربری و آیدی): {account_label} · بستر: {platform_source}",
        f"اولویت دوم دسته‌بندی (سرفصل موضوعی ۱۲گانه): {thematic_category}",
        f"ماهیت بصری و ساختاری: {image_nature}",
        f"ابعاد و هندسهٔ تصویر: {visual['width']}×{visual['height']} پیکسل ({visual['orientation']}، نسبت ابعاد {visual['aspect_ratio']})",
        f"پروفایل رنگی و روشنایی: {visual['color_profile_label']} (میانگین روشنایی {visual['mean_brightness']} از ۲۵۵، رنگ غالب {visual['dominant_color_hex']})",
    ]

    if template_applicable and template_fields:
        key_findings.append(
            f"قوارهٔ ویژهٔ دسته‌بندی {thematic_category}: تخلف «{template_fields.get('violation', 'ترویج ابتذال')}» · "
            f"{template_fields.get('action_request', 'درخواست مسدودی سیم کارت')} · لینک: {template_fields.get('profile_url') or 'ثبت‌نشده'}"
        )

    if word_count > 0:
        conf_str = f" با میانگین اطمینان {ocr_confidence:.1f}٪" if ocr_confidence is not None else ""
        key_findings.append(
            f"تحلیل نوشتاری (OCR): دارای {word_count} کلمه در قالب {line_count} سطر متنی{conf_str}."
        )
        preview_excerpt = " / ".join(lines[:2])[:160]
        key_findings.append(f"گزیدهٔ شاخص متن داخل تصویر: «{preview_excerpt}»")
    else:
        key_findings.append(
            "تحلیل نوشتاری (OCR): هیچ لایهٔ متنی یا نوشتار قابل استخراجی در این تصویر مشاهده نشد."
        )

    if word_count > 0:
        first_line = lines[0][:110] if lines else ""
        summary = (
            f"در سطح اول دسته‌بندی (نام کاربری و آیدی)، این تصویر به «{account_label}» ({platform_source}) تعلق دارد و "
            f"در سطح دوم دسته‌بندی موضوعی در سرفصل «{thematic_category}» جای می‌گیرد. "
            f"از نظر ماهیت بصری، فایل «{title}» یک «{image_nature}» با ابعاد {visual['width']}×{visual['height']} پیکسل "
            f"({visual['orientation']}) و {visual['color_profile_label']} است. "
            f"موتور تشخیص متن آفلاین ساهر در مجموع {word_count} کلمه ({line_count} سطر) را از داخل این تصویر استخراج کرده است"
            f"{f' که بخش آغازین آن شامل عبارت «{first_line}» است' if first_line else ''}."
        )
    else:
        summary = (
            f"در سطح اول دسته‌بندی (نام کاربری و آیدی)، این تصویر در گروه «{account_label}» و در سطح دوم در سرفصل موضوعی "
            f"«{thematic_category}» طبقه‌بندی شده است. فایل «{title}» دارای ماهیت «{image_nature}» با ابعاد "
            f"{visual['width']}×{visual['height']} پیکسل ({visual['orientation']}) بوده و فاقد نوشتار چاپی غالب است."
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
        account_id=account_id,
        account_username=account_username,
        account_label=account_label,
        platform_source=platform_source,
        thematic_category=thematic_category,
        image_nature=image_nature,
        detected_topic=thematic_category,
        confidence_label=confidence_label,
        tags=tags,
        key_findings=key_findings,
        analysis_summary=summary,
        template_applicable=template_applicable,
        template_fields=template_fields,
        formatted_template_text=formatted_template_text,
    )


def merge_batch_cultural_social_templates(analyses: List[ImageAnalysisResult]) -> None:
    """
    When multiple screenshots in a folder belong to the same account_id, combines
    their extracted Cultural/Social template fields (full_name, national_id, phone_number,
    guidance_date, numeric_id, account_handle, description, city_hashtag,
    occupation, profile_url, hashtags) so every screenshot of that account has the most
    complete template possible.
    """
    merged_by_account: Dict[str, Dict[str, Any]] = {}
    for item in analyses:
        if not item.template_applicable or not item.template_fields:
            continue
        acc_key = (item.account_id or "").strip().lower()
        if not acc_key or acc_key == "نامشخص":
            continue
        bucket = merged_by_account.setdefault(
            acc_key,
            {
                "full_name": "",
                "national_id": "",
                "phone_number": "",
                "guidance_date": "",
                "numeric_id": "",
                "account_handle": "",
                "description": "",
                "city_hashtag": "#کاشمر",
                "occupation": "",
                "violation": "ترویج ابتذال",
                "action_request": "درخواست مسدودی سیم کارت",
                "profile_url": "",
                "hashtags": [],
            },
        )
        tf = item.template_fields
        for k in ("full_name", "national_id", "phone_number", "guidance_date", "numeric_id", "account_handle", "occupation"):
            val = (tf.get(k) or "").strip()
            if val and not bucket[k]:
                bucket[k] = val
        desc_val = (tf.get("description") or "").strip()
        if desc_val and (not bucket["description"] or (bucket["description"] == "ترویج ابتذال" and desc_val != "ترویج ابتذال") or len(desc_val) > len(bucket["description"])):
            bucket["description"] = desc_val
        city_val = (tf.get("city_hashtag") or "").strip()
        if city_val and city_val != "#کاشمر":
            bucket["city_hashtag"] = city_val
        # Prefer URL with query parameters (like ?stkn=...) over bare URL
        url_val = (tf.get("profile_url") or "").strip()
        if url_val and (not bucket["profile_url"] or len(url_val) > len(bucket["profile_url"])):
            bucket["profile_url"] = url_val
        if tf.get("violation") and tf["violation"] != "ترویج ابتذال":
            bucket["violation"] = tf["violation"]
        if tf.get("action_request") and tf["action_request"] != "درخواست مسدودی سیم کارت":
            bucket["action_request"] = tf["action_request"]
        for tag in tf.get("hashtags") or []:
            if tag not in bucket["hashtags"]:
                bucket["hashtags"].append(tag)

    for item in analyses:
        if not item.template_applicable or not item.template_fields:
            continue
        acc_key = (item.account_id or "").strip().lower()
        if acc_key in merged_by_account:
            b = merged_by_account[acc_key]
            updated_fields = dict(item.template_fields)
            for k in (
                "full_name",
                "national_id",
                "phone_number",
                "guidance_date",
                "numeric_id",
                "account_handle",
                "description",
                "city_hashtag",
                "occupation",
                "violation",
                "action_request",
                "profile_url",
            ):
                if not updated_fields.get(k) and b.get(k):
                    updated_fields[k] = b[k]
                elif k in ("profile_url", "description") and len(b.get(k, "")) > len(updated_fields.get(k, "")):
                    updated_fields[k] = b[k]
            if b.get("hashtags"):
                updated_fields["hashtags"] = list(b["hashtags"])
            cat = getattr(item, "thematic_category", "") or item.detected_topic
            item.formatted_template_text = format_cultural_social_template(updated_fields, thematic_category=cat)
            item.template_fields = updated_fields


