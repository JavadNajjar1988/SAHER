import React from "react";
import { ConnectionMode } from "../types/archive";

interface SidebarProps {
  page: string;
  setPage: (p: string) => void;
  setQuery: (q: string) => void;
  attentionCount: number;
  digits: (n: number) => string;
  connectionMode: ConnectionMode;
  backendVersion?: string;
}

const nav = [
  "کتابخانه",
  "جست‌وجو",
  "دسته‌بندی‌ها",
  "صف پردازش",
  "بازبینی",
  "منابع",
];

export function Sidebar({
  page,
  setPage,
  setQuery,
  attentionCount,
  digits,
  connectionMode,
  backendVersion,
}: SidebarProps) {
  const statusLabel =
    connectionMode === "connected"
      ? "متصل به سرویس محلی ساهر"
      : connectionMode === "disconnected"
        ? "قطع ارتباط با سرویس محلی"
        : connectionMode === "demo"
          ? "حالت نمایشی آزمایشی (مجزا)"
          : "در حال بررسی سرویس محلی…";

  const statusSubtext =
    connectionMode === "connected"
      ? `پایگاه‌داده SQLite + FTS5 فعال${backendVersion ? ` · v${backendVersion}` : ""}`
      : connectionMode === "disconnected"
        ? "سرویس بک‌اند FastAPI در دسترس نیست"
        : connectionMode === "demo"
          ? "داده‌های نمایشی بدون ذخیره‌سازی دیسک"
          : "بررسی ارتباط با بک‌اند…";

  const dotColor =
    connectionMode === "connected"
      ? "#38b27b"
      : connectionMode === "disconnected"
        ? "#e05a47"
        : "#d99b26";

  return (
    <aside className="sidebar">
      <a
        className="brand"
        href="#"
        onClick={(e) => {
          e.preventDefault();
          setPage("کتابخانه");
        }}
      >
        <span className="brandmark">سـ</span>
        <span>
          ساهر<small>آرشیو شخصی هوشمند</small>
        </span>
      </a>
      <div className="workspace">
        <span className="avatar">م</span>
        <div>
          {connectionMode === "demo" ? "فضای نمایشی آزمایشی" : "فضای شخصی من"}
          <small>{connectionMode === "demo" ? "بدون ذخیره‌سازی پایدار" : "آرشیو محلی"}</small>
        </div>
        <span className="chevron">⌄</span>
      </div>
      <div className="navlabel">فضای کار</div>
      <nav>
        {nav.map((name, index) => (
          <button
            key={name}
            className={page === name ? "active" : ""}
            onClick={() => {
              setPage(name);
              setQuery("");
            }}
          >
            <span className="navicon">
              {["▦", "⌕", "◇", "≋", "☑", "▱"][index]}
            </span>
            <span>{name}</span>
            {name === "بازبینی" && <b>{digits(attentionCount)}</b>}
          </button>
        ))}
      </nav>
      <div className="bottomnav">
        {["پشتیبان‌گیری", "تنظیمات"].map((name, i) => (
          <button
            key={name}
            className={page === name ? "active" : ""}
            onClick={() => setPage(name)}
          >
            <span className="navicon">{i ? "⚙" : "◷"}</span>
            {name}
          </button>
        ))}
      </div>
      <div className="local" data-testid="service-health-indicator">
        <span className="dot" style={{ background: dotColor }} />
        {statusLabel}
        <small>{statusSubtext}</small>
      </div>
    </aside>
  );
}
