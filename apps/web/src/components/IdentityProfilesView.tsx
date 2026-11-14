import React, { useEffect, useMemo, useState } from "react";
import {
  IdentityProfileItem,
  THEMATIC_CATEGORIES_12,
} from "../types/archive";
import { ArchiveApiClient } from "../services/apiClient";

interface IdentityProfilesViewProps {
  digits: (n: string | number) => string;
  onNotify?: (msg: string) => void;
}

const EMPTY_PROFILE_FORM: Omit<IdentityProfileItem, "id"> = {
  source_file_id: null,
  first_name: "",
  last_name: "",
  full_name: "",
  father_name: "",
  national_id: "",
  birth_certificate_no: "",
  birth_date: "",
  birth_place: "",
  occupation: "",
  mobile_phone: "",
  secondary_mobile: "",
  landline_phone: "",
  province: "خراسان رضوی",
  city: "کاشمر",
  address: "",
  postal_code: "",
  gps_coordinates: "",
  location_name: "",
  account_handle: "",
  numeric_id: "",
  profile_url: "",
  personal_folder: "",
  thematic_category: "اجتماعی",
  risk_level: "متوسط (نیازمند مستندسازی و صدور دستور مسدودسازی/تذکر)",
  judicial_notes: "",
};

export function IdentityProfilesView({
  digits,
  onNotify,
}: IdentityProfilesViewProps) {
  const [profiles, setProfiles] = useState<IdentityProfileItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);
  const [isExportingWord, setIsExportingWord] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [categoryFilter, setCategoryFilter] = useState<string>("همه");
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState<string>("");
  const [formData, setFormData] =
    useState<Omit<IdentityProfileItem, "id">>(EMPTY_PROFILE_FORM);

  const notify = (msg: string) => {
    setStatusMessage(msg);
    onNotify?.(msg);
  };

  const loadProfiles = async (q?: string) => {
    setIsLoading(true);
    try {
      const res = await ArchiveApiClient.listIdentityProfiles(q);
      setProfiles(res.items || []);
    } catch {
      notify("خطا در بارگذاری فهرست مشخصات انفرادی و شناسنامه‌ای.");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void loadProfiles();
  }, []);

  const handleSyncFromArchive = async () => {
    setIsSyncing(true);
    try {
      const res = await ArchiveApiClient.syncIdentityProfilesFromArchive();
      setProfiles(res.items || []);
      notify(
        `همگام‌سازی خودکار از تصاویر آرشیو انجام شد (${digits(res.total)} پروندهٔ انفرادی).`,
      );
    } catch {
      notify("خطا در همگام‌سازی خودکار مشخصات از تصاویر آرشیو.");
    } finally {
      setIsSyncing(false);
    }
  };

  const handleExportWord = async (specificIds?: string[], customTitle?: string) => {
    setIsExportingWord(true);
    try {
      const blob = await ArchiveApiClient.downloadIdentityProfilesWordReport(
        specificIds,
        customTitle ||
          "گزارش جامع مشخصات انفرادی، شناسنامه‌ای، شماره موبایل و آدرس",
      );
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download =
        specificIds && specificIds.length === 1
          ? `saher-identity-dossier-${specificIds[0].slice(0, 6)}.docx`
          : "saher-identity-profiles-report.docx";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      notify("سند Word مشخصات انفرادی و شناسنامه‌ای (.docx) با موفقیت تولید شد.");
    } catch {
      notify("خطا در تولید سند Word مشخصات انفرادی.");
    } finally {
      setIsExportingWord(false);
    }
  };

  const handleOpenCreate = () => {
    setEditingId(null);
    setFormData({ ...EMPTY_PROFILE_FORM });
    setShowForm(true);
  };

  const handleOpenEdit = (item: IdentityProfileItem) => {
    setEditingId(item.id);
    setFormData({
      source_file_id: item.source_file_id || null,
      first_name: item.first_name || "",
      last_name: item.last_name || "",
      full_name: item.full_name || "",
      father_name: item.father_name || "",
      national_id: item.national_id || "",
      birth_certificate_no: item.birth_certificate_no || "",
      birth_date: item.birth_date || "",
      birth_place: item.birth_place || "",
      occupation: item.occupation || "",
      mobile_phone: item.mobile_phone || "",
      secondary_mobile: item.secondary_mobile || "",
      landline_phone: item.landline_phone || "",
      province: item.province || "",
      city: item.city || "",
      address: item.address || "",
      postal_code: item.postal_code || "",
      gps_coordinates: item.gps_coordinates || "",
      location_name: item.location_name || "",
      account_handle: item.account_handle || "",
      numeric_id: item.numeric_id || "",
      profile_url: item.profile_url || "",
      personal_folder: item.personal_folder || "",
      thematic_category: item.thematic_category || "اجتماعی",
      risk_level: item.risk_level || "عادی",
      judicial_notes: item.judicial_notes || "",
    });
    setShowForm(true);
  };

  const handleSaveForm = async (e: React.FormEvent) => {
    e.preventDefault();
    const computedFullName =
      formData.full_name.trim() ||
      `${formData.first_name.trim()} ${formData.last_name.trim()}`.trim();

    if (
      !computedFullName &&
      !formData.national_id.trim() &&
      !formData.mobile_phone.trim() &&
      !formData.account_handle.trim()
    ) {
      notify(
        "لطفاً حداقل یکی از مشخصات اصلی (نام و نام خانوادگی، کد ملی، شماره موبایل یا آیدی) را وارد کنید.",
      );
      return;
    }

    try {
      const payload = {
        ...formData,
        full_name: computedFullName,
      };
      if (editingId) {
        await ArchiveApiClient.updateIdentityProfile(editingId, payload);
        notify(`پروندهٔ مشخصات انفرادی «${computedFullName || editingId}» بروزرسانی شد.`);
      } else {
        await ArchiveApiClient.createIdentityProfile(payload);
        notify(`پروندهٔ جدید مشخصات انفرادی «${computedFullName}» ثبت شد.`);
      }
      setShowForm(false);
      setEditingId(null);
      await loadProfiles(searchQuery);
    } catch {
      notify("خطا در ذخیرهٔ پروندهٔ مشخصات انفرادی و شناسنامه‌ای.");
    }
  };

  const handleDelete = async (id: string, name: string) => {
    try {
      await ArchiveApiClient.deleteIdentityProfile(id);
      setProfiles((prev) => prev.filter((p) => p.id !== id));
      notify(`پروندهٔ انفرادی «${name || id}» حذف شد.`);
    } catch {
      notify("خطا در حذف پروندهٔ مشخصات انفرادی.");
    }
  };

  const filteredProfiles = useMemo(() => {
    return profiles.filter((p) => {
      if (categoryFilter !== "همه" && p.thematic_category !== categoryFilter) {
        return false;
      }
      if (!searchQuery.trim()) return true;
      const q = searchQuery.trim().toLowerCase();
      const hay = [
        p.full_name,
        p.first_name,
        p.last_name,
        p.father_name,
        p.national_id,
        p.birth_certificate_no,
        p.mobile_phone,
        p.secondary_mobile,
        p.landline_phone,
        p.province,
        p.city,
        p.address,
        p.postal_code,
        p.account_handle,
        p.numeric_id,
        p.occupation,
        p.judicial_notes,
      ]
        .join(" ")
        .toLowerCase();
      return hay.includes(q);
    });
  }, [profiles, categoryFilter, searchQuery]);

  const withMobileCount = useMemo(
    () => profiles.filter((p) => Boolean(p.mobile_phone || p.secondary_mobile)).length,
    [profiles],
  );
  const withNationalIdCount = useMemo(
    () =>
      profiles.filter((p) => Boolean(p.national_id || p.birth_certificate_no))
        .length,
    [profiles],
  );
  const withAddressCount = useMemo(
    () =>
      profiles.filter((p) => Boolean(p.address || p.city || p.gps_coordinates))
        .length,
    [profiles],
  );

  return (
    <section
      className="batch-analysis-page"
      data-testid="identity-profiles-view"
    >
      {statusMessage && (
        <div
          data-testid="identity-status-banner"
          style={{
            marginBottom: "14px",
            padding: "10px 14px",
            borderRadius: "10px",
            background: "rgba(30, 58, 95, 0.08)",
            border: "1px solid rgba(30, 58, 95, 0.22)",
            color: "#1e3a5f",
            fontSize: "0.9rem",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <span>{statusMessage}</span>
          <button
            type="button"
            onClick={() => setStatusMessage("")}
            style={{
              background: "transparent",
              border: "none",
              cursor: "pointer",
              color: "#1e3a5f",
              fontWeight: 700,
            }}
          >
            ✕
          </button>
        </div>
      )}
      <div className="sectionhead">
        <div>
          <h2>
            صفحهٔ مشخصات انفرادی، شناسنامه‌ای، شماره موبایل، تلفن همراه و آدرس
          </h2>
          <p>
            مدیریت یکپارچهٔ پرونده‌های هویتی و شناسنامه‌ای استخراج‌شده از تصاویر و
            اسکرین‌شات‌ها یا ثبت‌شدهٔ مستقیم، همراه با شماره موبایل، تلفن ثابت،
            آدرس محل سکونت، موقعیت مکانی و خروجی سند فارسی Word (.docx)
          </p>
        </div>
        <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
          <button
            type="button"
            className="ghost"
            onClick={handleSyncFromArchive}
            disabled={isSyncing}
            data-testid="sync-identity-profiles-btn"
          >
            {isSyncing
              ? "در حال استخراج از تصاویر…"
              : "↻ استخراج خودکار از تصاویر آرشیو"}
          </button>
          <button
            type="button"
            className="ghost"
            onClick={() => handleExportWord()}
            disabled={isExportingWord || profiles.length === 0}
            data-testid="export-identity-word-btn"
          >
            {isExportingWord
              ? "در حال ساخت Word…"
              : "⬇ خروجی سند Word مشخصات انفرادی (.docx)"}
          </button>
          <button
            type="button"
            className="primary"
            onClick={handleOpenCreate}
            data-testid="new-identity-profile-btn"
          >
            + ثبت مشخصات انفرادی جدید
          </button>
        </div>
      </div>

      {/* KPI Cards */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
          gap: "12px",
          marginBottom: "16px",
        }}
      >
        <div className="panel" style={{ padding: "14px" }}>
          <small style={{ color: "var(--muted)" }}>کل پرونده‌های انفرادی</small>
          <div style={{ fontSize: "1.45rem", fontWeight: 700, marginTop: "4px" }}>
            {digits(profiles.length)} پرونده
          </div>
        </div>
        <div className="panel" style={{ padding: "14px" }}>
          <small style={{ color: "var(--muted)" }}>
            دارای شماره موبایل / تلفن همراه
          </small>
          <div
            style={{
              fontSize: "1.45rem",
              fontWeight: 700,
              marginTop: "4px",
              color: "var(--accent)",
            }}
          >
            {digits(withMobileCount)} مورد
          </div>
        </div>
        <div className="panel" style={{ padding: "14px" }}>
          <small style={{ color: "var(--muted)" }}>
            دارای کد ملی / شماره شناسنامه
          </small>
          <div style={{ fontSize: "1.45rem", fontWeight: 700, marginTop: "4px" }}>
            {digits(withNationalIdCount)} مورد
          </div>
        </div>
        <div className="panel" style={{ padding: "14px" }}>
          <small style={{ color: "var(--muted)" }}>
            دارای آدرس، شهر یا مختصات مکانی
          </small>
          <div style={{ fontSize: "1.45rem", fontWeight: 700, marginTop: "4px" }}>
            {digits(withAddressCount)} مورد
          </div>
        </div>
      </div>

      {/* Search & Category Filter */}
      <div
        className="panel"
        style={{
          padding: "14px",
          marginBottom: "16px",
          display: "flex",
          gap: "12px",
          flexWrap: "wrap",
          alignItems: "center",
        }}
      >
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="جست‌وجو در نام، نام پدر، کد ملی، شماره شناسنامه، موبایل، تلفن ثابت، آدرس یا آیدی…"
          style={{
            flex: "1 1 320px",
            padding: "9px 12px",
            borderRadius: "8px",
            border: "1px solid var(--line)",
            fontFamily: "inherit",
          }}
          data-testid="identity-search-input"
        />
        <select
          value={categoryFilter}
          onChange={(e) => setCategoryFilter(e.target.value)}
          style={{
            padding: "9px 12px",
            borderRadius: "8px",
            border: "1px solid var(--line)",
            fontFamily: "inherit",
            background: "var(--panel)",
          }}
          data-testid="identity-category-select"
        >
          <option value="همه">همهٔ ۱۲ سرفصل موضوعی</option>
          {THEMATIC_CATEGORIES_12.map((cat) => (
            <option key={cat} value={cat}>
              {cat}
            </option>
          ))}
        </select>
      </div>

      {/* Create / Edit Identity Profile Form */}
      {showForm && (
        <form
          onSubmit={handleSaveForm}
          className="panel"
          style={{
            padding: "18px",
            marginBottom: "20px",
            border: "1px solid var(--accent)",
          }}
          data-testid="identity-profile-form"
        >
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              marginBottom: "14px",
            }}
          >
            <h3 style={{ margin: 0 }}>
              {editingId
                ? "ویرایش پروندهٔ مشخصات انفرادی و شناسنامه‌ای"
                : "ثبت پروندهٔ جدید مشخصات انفرادی، شناسنامه‌ای، موبایل و آدرس"}
            </h3>
            <button
              type="button"
              className="ghost"
              onClick={() => {
                setShowForm(false);
                setEditingId(null);
              }}
            >
              بستن فرم ✕
            </button>
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))",
              gap: "12px",
            }}
          >
            <label style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
              <small>نام</small>
              <input
                type="text"
                value={formData.first_name}
                onChange={(e) =>
                  setFormData((p) => ({ ...p, first_name: e.target.value }))
                }
                placeholder="مثلاً: علی"
                data-testid="id-form-first-name"
              />
            </label>
            <label style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
              <small>نام خانوادگی</small>
              <input
                type="text"
                value={formData.last_name}
                onChange={(e) =>
                  setFormData((p) => ({ ...p, last_name: e.target.value }))
                }
                placeholder="مثلاً: رجبی‌پور"
                data-testid="id-form-last-name"
              />
            </label>
            <label style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
              <small>نام و نام خانوادگی کامل</small>
              <input
                type="text"
                value={formData.full_name}
                onChange={(e) =>
                  setFormData((p) => ({ ...p, full_name: e.target.value }))
                }
                placeholder="مثلاً: علی رجبی‌پور"
                data-testid="id-form-full-name"
              />
            </label>
            <label style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
              <small>نام پدر</small>
              <input
                type="text"
                value={formData.father_name}
                onChange={(e) =>
                  setFormData((p) => ({ ...p, father_name: e.target.value }))
                }
                placeholder="مثلاً: محمد"
                data-testid="id-form-father-name"
              />
            </label>
            <label style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
              <small>کد ملی (۱۰ رقمی)</small>
              <input
                type="text"
                value={formData.national_id}
                onChange={(e) =>
                  setFormData((p) => ({ ...p, national_id: e.target.value }))
                }
                placeholder="مثلاً: 0921456789"
                data-testid="id-form-national-id"
              />
            </label>
            <label style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
              <small>شماره شناسنامه</small>
              <input
                type="text"
                value={formData.birth_certificate_no}
                onChange={(e) =>
                  setFormData((p) => ({
                    ...p,
                    birth_certificate_no: e.target.value,
                  }))
                }
                placeholder="مثلاً: 4512"
                data-testid="id-form-sh-number"
              />
            </label>
            <label style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
              <small>تاریخ تولد</small>
              <input
                type="text"
                value={formData.birth_date}
                onChange={(e) =>
                  setFormData((p) => ({ ...p, birth_date: e.target.value }))
                }
                placeholder="مثلاً: 1375/04/12"
              />
            </label>
            <label style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
              <small>محل تولد / صدور شناسنامه</small>
              <input
                type="text"
                value={formData.birth_place}
                onChange={(e) =>
                  setFormData((p) => ({ ...p, birth_place: e.target.value }))
                }
                placeholder="مثلاً: کاشمر"
              />
            </label>
            <label style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
              <small>شغل و حرفه</small>
              <input
                type="text"
                value={formData.occupation}
                onChange={(e) =>
                  setFormData((p) => ({ ...p, occupation: e.target.value }))
                }
                placeholder="مثلاً: بلاگر و مدلینگ"
              />
            </label>
            <label style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
              <small>شماره موبایل (تلفن همراه اول)</small>
              <input
                type="text"
                value={formData.mobile_phone}
                onChange={(e) =>
                  setFormData((p) => ({ ...p, mobile_phone: e.target.value }))
                }
                placeholder="مثلاً: 09153456789"
                data-testid="id-form-mobile"
              />
            </label>
            <label style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
              <small>تلفن همراه دوم / شماره حساب</small>
              <input
                type="text"
                value={formData.secondary_mobile}
                onChange={(e) =>
                  setFormData((p) => ({
                    ...p,
                    secondary_mobile: e.target.value,
                  }))
                }
                placeholder="مثلاً: 09351112233"
              />
            </label>
            <label style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
              <small>تلفن ثابت</small>
              <input
                type="text"
                value={formData.landline_phone}
                onChange={(e) =>
                  setFormData((p) => ({ ...p, landline_phone: e.target.value }))
                }
                placeholder="مثلاً: 05155223344"
                data-testid="id-form-landline"
              />
            </label>
            <label style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
              <small>استان</small>
              <input
                type="text"
                value={formData.province}
                onChange={(e) =>
                  setFormData((p) => ({ ...p, province: e.target.value }))
                }
                placeholder="مثلاً: خراسان رضوی"
              />
            </label>
            <label style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
              <small>شهرستان / شهر</small>
              <input
                type="text"
                value={formData.city}
                onChange={(e) =>
                  setFormData((p) => ({ ...p, city: e.target.value }))
                }
                placeholder="مثلاً: کاشمر"
              />
            </label>
            <label style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
              <small>کد پستی (۱۰ رقمی)</small>
              <input
                type="text"
                value={formData.postal_code}
                onChange={(e) =>
                  setFormData((p) => ({ ...p, postal_code: e.target.value }))
                }
                placeholder="مثلاً: 9671612345"
              />
            </label>
            <label style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
              <small>مختصات جغرافیایی (GPS)</small>
              <input
                type="text"
                value={formData.gps_coordinates}
                onChange={(e) =>
                  setFormData((p) => ({
                    ...p,
                    gps_coordinates: e.target.value,
                  }))
                }
                placeholder="مثلاً: 35.2384, 58.4656"
              />
            </label>
            <label style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
              <small>شناسه آی‌دی فضای مجازی (@handle)</small>
              <input
                type="text"
                value={formData.account_handle}
                onChange={(e) =>
                  setFormData((p) => ({ ...p, account_handle: e.target.value }))
                }
                placeholder="مثلاً: @mira_rjbpr"
              />
            </label>
            <label style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
              <small>آیدی عددی</small>
              <input
                type="text"
                value={formData.numeric_id}
                onChange={(e) =>
                  setFormData((p) => ({ ...p, numeric_id: e.target.value }))
                }
                placeholder="مثلاً: 583920147"
              />
            </label>
            <label style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
              <small>لینک صفحه / آدرس اینترنتی</small>
              <input
                type="text"
                value={formData.profile_url}
                onChange={(e) =>
                  setFormData((p) => ({ ...p, profile_url: e.target.value }))
                }
                placeholder="https://www.instagram.com/..."
              />
            </label>
            <label style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
              <small>سرفصل موضوعی ۱۲گانه</small>
              <select
                value={formData.thematic_category}
                onChange={(e) =>
                  setFormData((p) => ({
                    ...p,
                    thematic_category: e.target.value,
                  }))
                }
                style={{
                  padding: "8px",
                  borderRadius: "6px",
                  border: "1px solid var(--line)",
                  fontFamily: "inherit",
                }}
              >
                {THEMATIC_CATEGORIES_12.map((cat) => (
                  <option key={cat} value={cat}>
                    {cat}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: "12px",
              marginTop: "12px",
            }}
          >
            <label style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
              <small>آدرس کامل محل سکونت / فعالیت</small>
              <input
                type="text"
                value={formData.address}
                onChange={(e) =>
                  setFormData((p) => ({ ...p, address: e.target.value }))
                }
                placeholder="مثلاً: خراسان رضوی، کاشمر، خیابان امام خمینی، کوچه ۴، پلاک ۱۲"
                data-testid="id-form-address"
              />
            </label>
            <label style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
              <small>سوابق، مستندات و بررسی موارد مجرمانه (حقوقی و قضایی)</small>
              <input
                type="text"
                value={formData.judicial_notes}
                onChange={(e) =>
                  setFormData((p) => ({ ...p, judicial_notes: e.target.value }))
                }
                placeholder="مثلاً: ماده ۱۴ قانون جرایم رایانه‌ای — درخواست مسدودی سیم‌کارت و صفحه"
                data-testid="id-form-judicial"
              />
            </label>
          </div>

          <div
            style={{
              display: "flex",
              justifyContent: "flex-end",
              gap: "10px",
              marginTop: "16px",
            }}
          >
            <button
              type="button"
              className="ghost"
              onClick={() => {
                setShowForm(false);
                setEditingId(null);
              }}
            >
              انصراف
            </button>
            <button
              type="submit"
              className="primary"
              data-testid="save-identity-profile-btn"
            >
              {editingId ? "ذخیرهٔ تغییرات پرونده" : "ثبت پرونده در پایگاه‌داده"}
            </button>
          </div>
        </form>
      )}

      {/* Profiles List */}
      {isLoading ? (
        <div className="panel" style={{ padding: "28px", textAlign: "center" }}>
          در حال بارگذاری پرونده‌های مشخصات انفرادی و شناسنامه‌ای…
        </div>
      ) : filteredProfiles.length === 0 ? (
        <div
          className="panel"
          style={{ padding: "28px", textAlign: "center" }}
          data-testid="empty-identity-profiles"
        >
          <h3 style={{ marginTop: 0 }}>
            هنوز پرونده‌ای در فهرست مشخصات انفرادی و شناسنامه‌ای ثبت نشده است
          </h3>
          <p style={{ color: "var(--muted)", maxWidth: "620px", margin: "8px auto 16px" }}>
            می‌توانید با دکمهٔ «استخراج خودکار از تصاویر آرشیو» مشخصات انفرادی،
            کد ملی، شماره موبایل و آدرس را از روی اسکرین‌شات‌ها و اسناد موجود
            استخراج کنید یا به صورت مستقیم پروندهٔ جدید ثبت نمایید.
          </p>
          <div style={{ display: "flex", justifyContent: "center", gap: "10px" }}>
            <button
              type="button"
              className="ghost"
              onClick={handleSyncFromArchive}
            >
              ↻ استخراج خودکار از تصاویر آرشیو
            </button>
            <button
              type="button"
              className="primary"
              onClick={handleOpenCreate}
            >
              + ثبت مشخصات انفرادی جدید
            </button>
          </div>
        </div>
      ) : (
        <div
          style={{ display: "flex", flexDirection: "column", gap: "14px" }}
          data-testid="identity-profiles-list"
        >
          {filteredProfiles.map((prof, idx) => {
            const displayName =
              prof.full_name ||
              `${prof.first_name || ""} ${prof.last_name || ""}`.trim() ||
              prof.account_handle ||
              "پروندهٔ انفرادی بدون نام";
            return (
              <article
                key={prof.id}
                className="panel"
                style={{ padding: "16px 18px" }}
                data-testid={`identity-profile-card-${idx}`}
              >
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "flex-start",
                    gap: "12px",
                    flexWrap: "wrap",
                    borderBottom: "1px solid var(--line)",
                    paddingBottom: "10px",
                    marginBottom: "12px",
                  }}
                >
                  <div>
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "8px",
                        flexWrap: "wrap",
                      }}
                    >
                      <span
                        className="tag"
                        style={{
                          background: "var(--accent)",
                          color: "#fff",
                          fontWeight: 700,
                        }}
                      >
                        پروندهٔ شمارهٔ {digits(idx + 1)}
                      </span>
                      <h3 style={{ margin: 0, fontSize: "1.12rem" }}>
                        {displayName}
                      </h3>
                      {prof.account_handle && (
                        <span className="tag" dir="ltr">
                          {prof.account_handle}
                        </span>
                      )}
                      <span className="tag">{prof.thematic_category || "اجتماعی"}</span>
                    </div>
                    {prof.personal_folder && (
                      <small
                        style={{
                          display: "block",
                          color: "var(--muted)",
                          marginTop: "4px",
                        }}
                      >
                        {prof.personal_folder}
                      </small>
                    )}
                  </div>
                  <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                    <button
                      type="button"
                      className="ghost"
                      onClick={() =>
                        handleExportWord(
                          [prof.id],
                          `پروندهٔ مشخصات انفرادی و شناسنامه‌ای — ${displayName}`,
                        )
                      }
                    >
                      ⬇ خروجی Word پرونده (.docx)
                    </button>
                    <button
                      type="button"
                      className="ghost"
                      onClick={() => handleOpenEdit(prof)}
                    >
                      ✎ ویرایش مشخصات
                    </button>
                    <button
                      type="button"
                      className="ghost"
                      onClick={() => handleDelete(prof.id, displayName)}
                    >
                      حذف
                    </button>
                  </div>
                </div>

                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                    gap: "10px 16px",
                    fontSize: "0.92rem",
                  }}
                >
                  <div>
                    <strong style={{ color: "var(--muted)" }}>
                      نام و نام خانوادگی:{" "}
                    </strong>
                    <span>{displayName}</span>
                  </div>
                  <div>
                    <strong style={{ color: "var(--muted)" }}>نام پدر: </strong>
                    <span>{prof.father_name || "ثبت‌نشده"}</span>
                  </div>
                  <div>
                    <strong style={{ color: "var(--muted)" }}>کد ملی: </strong>
                    <span>{prof.national_id ? digits(prof.national_id) : "ثبت‌نشده"}</span>
                  </div>
                  <div>
                    <strong style={{ color: "var(--muted)" }}>
                      شماره شناسنامه:{" "}
                    </strong>
                    <span>
                      {prof.birth_certificate_no
                        ? digits(prof.birth_certificate_no)
                        : "ثبت‌نشده"}
                    </span>
                  </div>
                  <div>
                    <strong style={{ color: "var(--muted)" }}>
                      تاریخ و محل تولد:{" "}
                    </strong>
                    <span>
                      {[prof.birth_date && digits(prof.birth_date), prof.birth_place]
                        .filter(Boolean)
                        .join(" · ") || "ثبت‌نشده"}
                    </span>
                  </div>
                  <div>
                    <strong style={{ color: "var(--muted)" }}>
                      شغل و فعالیت:{" "}
                    </strong>
                    <span>{prof.occupation || "ثبت‌نشده"}</span>
                  </div>
                  <div>
                    <strong style={{ color: "var(--muted)" }}>
                      شماره موبایل (تلفن همراه):{" "}
                    </strong>
                    <span style={{ fontWeight: 700, color: "var(--accent)" }}>
                      {prof.mobile_phone ? digits(prof.mobile_phone) : "ثبت‌نشده"}
                    </span>
                  </div>
                  <div>
                    <strong style={{ color: "var(--muted)" }}>
                      تلفن همراه دوم / حساب:{" "}
                    </strong>
                    <span>
                      {prof.secondary_mobile
                        ? digits(prof.secondary_mobile)
                        : "ثبت‌نشده"}
                    </span>
                  </div>
                  <div>
                    <strong style={{ color: "var(--muted)" }}>تلفن ثابت: </strong>
                    <span>
                      {prof.landline_phone ? digits(prof.landline_phone) : "ثبت‌نشده"}
                    </span>
                  </div>
                  <div>
                    <strong style={{ color: "var(--muted)" }}>
                      استان و شهرستان:{" "}
                    </strong>
                    <span>
                      {[prof.province, prof.city].filter(Boolean).join(" ، ") ||
                        "ثبت‌نشده"}
                    </span>
                  </div>
                  <div>
                    <strong style={{ color: "var(--muted)" }}>کد پستی: </strong>
                    <span>
                      {prof.postal_code ? digits(prof.postal_code) : "ثبت‌نشده"}
                    </span>
                  </div>
                  <div>
                    <strong style={{ color: "var(--muted)" }}>
                      مختصات مکانی (GPS):{" "}
                    </strong>
                    <span dir="ltr">{prof.gps_coordinates || "—"}</span>
                  </div>
                  <div>
                    <strong style={{ color: "var(--muted)" }}>آیدی عددی: </strong>
                    <span>
                      {prof.numeric_id ? digits(prof.numeric_id) : "ثبت‌نشده"}
                    </span>
                  </div>
                  <div>
                    <strong style={{ color: "var(--muted)" }}>
                      آدرس اینترنتی صفحه:{" "}
                    </strong>
                    <span dir="ltr">{prof.profile_url || "—"}</span>
                  </div>
                </div>

                <div
                  style={{
                    marginTop: "10px",
                    paddingTop: "10px",
                    borderTop: "1px dashed var(--line)",
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
                    gap: "10px",
                    fontSize: "0.91rem",
                  }}
                >
                  <div>
                    <strong style={{ color: "var(--muted)" }}>
                      آدرس دقیق محل سکونت / فعالیت:{" "}
                    </strong>
                    <span>
                      {prof.address ||
                        [prof.province, prof.city].filter(Boolean).join(" ، ") ||
                        "ثبت‌نشده"}
                    </span>
                  </div>
                  <div>
                    <strong style={{ color: "var(--muted)" }}>
                      بررسی حقوقی و قضایی / سوابق:{" "}
                    </strong>
                    <span>{prof.judicial_notes || prof.risk_level || "عادی"}</span>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
