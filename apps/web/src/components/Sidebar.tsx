import React from "react";

interface SidebarProps {
  page: string;
  setPage: (p: string) => void;
  setQuery: (q: string) => void;
  attentionCount: number;
  digits: (n: number) => string;
}

const nav = [
  "کتابخانه",
  "جست‌وجو",
  "دسته‌بندی‌ها",
  "صف پردازش",
  "بازبینی",
  "منابع",
];

export function Sidebar({ page, setPage, setQuery, attentionCount, digits }: SidebarProps) {
  return (
    <aside className="sidebar">
      <a className="brand" href="#" onClick={(e) => { e.preventDefault(); setPage("کتابخانه"); }}>
        <span className="brandmark">سـ</span>
        <span>
          ساهر<small>آرشیو شخصی هوشمند</small>
        </span>
      </a>
      <div className="workspace">
        <span className="avatar">م</span>
        <div>
          فضای شخصی من<small>آرشیو محلی</small>
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
            {name === "بازبینی" && (
              <b>
                {digits(attentionCount)}
              </b>
            )}
          </button>
        ))}
      </nav>
      <div className="bottomnav">
        {["پشتیبان‌گیری", "تنظیمات"].map((name, i) => (
          <button key={name} className={page === name ? "active" : ""} onClick={() => setPage(name)}>
            <span className="navicon">{i ? "⚙" : "◷"}</span>
            {name}
          </button>
        ))}
      </div>
      <div className="local">
        <span className="dot" />
        ذخیره‌سازی و پردازش آفلاین
        <small>داده‌ها به طور پایدار در آرشیو ثبت می‌شوند</small>
      </div>
    </aside>
  );
}
