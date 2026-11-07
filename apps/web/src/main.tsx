import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";

type Item = {
  id: number;
  title: string;
  kind: string;
  topic: string;
  status: string;
  text: string;
  color: string;
  tags: string[];
};
const initial: Item[] = [
  {
    id: 1,
    title: "یادداشت‌های طراحی و معماری",
    kind: "سند",
    topic: "طراحی",
    status: "آماده",
    text: "طراحی خوب از شناخت مسئله آغاز می‌شود. در این یادداشت، اصول طراحی یک محصول ساده، خوانا و قابل استفاده را مرور می‌کنیم.",
    color: "paper",
    tags: ["طراحی محصول", "یادداشت"],
  },
  {
    id: 2,
    title: "رنگ، فضا و زندگی روزمره",
    kind: "تصویر",
    topic: "معماری",
    status: "آماده",
    text: "تصویری از یک فضای آرام با نور طبیعی، دیوارهای روشن و جزئیات سبز. این توصیف، برداشت نمایشی مدل است.",
    color: "room",
    tags: ["فضای داخلی", "الهام"],
  },
  {
    id: 3,
    title: "چطور بهتر یاد بگیریم؟",
    kind: "اسکرین‌شات",
    topic: "آموزش",
    status: "نیازمند بازبینی",
    text: "یادگیری عمیق با تمرین‌های کوتاه و پیوسته شکل می‌گیرد. بین مطالعه‌ها فاصله بگذارید و آنچه آموخته‌اید را با زبان خودتان بازگو کنید.",
    color: "social",
    tags: ["یادگیری", "مطالعه"],
  },
  {
    id: 4,
    title: "گزارش پژوهش‌های هوش مصنوعی",
    kind: "سند",
    topic: "فناوری",
    status: "آماده",
    text: "این گزارش به بررسی کاربرد مدل‌های زبانی در دسته‌بندی و بازیابی اسناد می‌پردازد.",
    color: "report",
    tags: ["پژوهش", "هوش مصنوعی"],
  },
  {
    id: 5,
    title: "سفر به جنگل‌های شمال",
    kind: "تصویر",
    topic: "زندگی",
    status: "آماده",
    text: "جنگلی مه‌آلود با درختان بلند و مسیر باریک میان پوشش سبز.",
    color: "forest",
    tags: ["طبیعت", "سفر"],
  },
  {
    id: 6,
    title: "دست‌نوشته‌های جلسهٔ محصول",
    kind: "سند",
    topic: "کار",
    status: "تحلیل ناقص",
    text: "موضوع جلسه، ساده‌سازی ورود فایل و نمایش روشن وضعیت پردازش بود. بخشی از نوشته در نمونه خوانا نیست.",
    color: "notes",
    tags: ["جلسه", "محصول"],
  },
];
const nav = [
  "کتابخانه",
  "جست‌وجو",
  "دسته‌بندی‌ها",
  "صف پردازش",
  "بازبینی",
  "منابع",
];
const digits = (value: number) => value.toLocaleString("fa-IR");

function App() {
  const [items, setItems] = useState(initial);
  const [page, setPage] = useState("کتابخانه");
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("همهٔ فایل‌ها");
  const [view, setView] = useState("grid");
  const [selected, setSelected] = useState<Item | null>(null);
  const [adding, setAdding] = useState(false);
  const [tag, setTag] = useState("");
  const [notice, setNotice] = useState("");
  const modalOpen = selected !== null || adding;
  useEffect(() => {
    if (!modalOpen) return;
    const previousFocus = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const dialog = document.querySelector<HTMLElement>('[role="dialog"]');
    const focusable = () =>
      Array.from(
        dialog?.querySelectorAll<HTMLElement>(
          "button, input, select, [href]",
        ) ?? [],
      );
    focusable()[0]?.focus();
    function handleKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setSelected(null);
        setAdding(false);
      }
      if (event.key === "Tab") {
        const controls = focusable();
        const first = controls[0];
        const last = controls[controls.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    }
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("keydown", handleKey);
      document.body.style.overflow = previousOverflow;
      previousFocus?.focus();
      setNotice("");
      setTag("");
    };
  }, [modalOpen]);
  const results = items.filter(
    (item) =>
      (kind === "همهٔ فایل‌ها" || item.kind === kind) &&
      `${item.title} ${item.text} ${item.tags.join(" ")}`.includes(query) &&
      (page !== "بازبینی" || item.status === "نیازمند بازبینی"),
  );
  function update(item: Item) {
    setItems((current) =>
      current.map((entry) => (entry.id === item.id ? item : entry)),
    );
    setSelected(item);
  }
  return (
    <div className="shell">
      <aside className="sidebar">
        <a className="brand" href="#" onClick={() => setPage("کتابخانه")}>
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
                  {digits(
                    items.filter((i) => i.status === "نیازمند بازبینی").length,
                  )}
                </b>
              )}
            </button>
          ))}
        </nav>
        <div className="bottomnav">
          {["پشتیبان‌گیری", "تنظیمات"].map((name, i) => (
            <button key={name} onClick={() => setPage(name)}>
              <span className="navicon">{i ? "⚙" : "◷"}</span>
              {name}
            </button>
          ))}
        </div>
        <div className="local">
          <span className="dot" />
          نمونهٔ نمایشی آفلاین
          <small>داده‌ها روی همین صفحه نمایش داده می‌شوند</small>
        </div>
      </aside>
      <main>
        <header>
          <span>
            فضای شخصی <span className="crumb">/</span> {page}
          </span>
          <div className="headerleft">
            <span className="privacy">◈ حریم خصوصی، پیش‌فرض ماست</span>
            <span className="avatar small">م</span>
          </div>
        </header>
        <div className="content">
          <section className="heading">
            <div>
              <div className="eyebrow">هر چیزی، در جای خودش</div>
              <h1>{page === "کتابخانه" ? "کتابخانهٔ من" : page}</h1>
              <p>اینجا جایی برای نگه‌داشتن، پیدا کردن و دوباره کشف کردن است.</p>
            </div>
            <button className="primary" onClick={() => setAdding(true)}>
              <span>＋</span> افزودن فایل
            </button>
          </section>
          <section className="stats">
            <div>
              <span className="statIcon">▤</span>
              <div>
                <small>تمام فایل‌ها</small>
                <strong>
                  {digits(items.length)}
                  <em>فایل در کتابخانه</em>
                </strong>
              </div>
            </div>
            <div>
              <span className="statIcon green">✓</span>
              <div>
                <small>آمادهٔ جست‌وجو</small>
                <strong>
                  {digits(items.filter((i) => i.status === "آماده").length)}
                  <em>پردازش کامل شده</em>
                </strong>
              </div>
            </div>
            <div>
              <span className="statIcon amber">◌</span>
              <div>
                <small>نیازمند توجه شما</small>
                <strong>
                  {digits(items.filter((i) => i.status !== "آماده").length)}
                  <em>بازبینی و تحلیل ناقص</em>
                </strong>
              </div>
            </div>
          </section>
          {["کتابخانه", "جست‌وجو", "بازبینی"].includes(page) ? (
            <>
              <section className="toolbar">
                <div className="search">
                  <span>⌕</span>
                  <input
                    aria-label="جست‌وجو در کتابخانه"
                    placeholder="در میان فایل‌ها، متن‌ها و برچسب‌ها بگردید…"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                  />
                  {query && (
                    <button
                      aria-label="پاک کردن جست‌وجو"
                      onClick={() => setQuery("")}
                    >
                      ×
                    </button>
                  )}
                </div>
                <select
                  aria-label="نوع فایل"
                  value={kind}
                  onChange={(e) => setKind(e.target.value)}
                >
                  {["همهٔ فایل‌ها", "سند", "تصویر", "اسکرین‌شات"].map((k) => (
                    <option key={k}>{k}</option>
                  ))}
                </select>
                <div className="viewtoggle">
                  <button
                    aria-label="نمای کارتی"
                    className={view === "grid" ? "chosen" : ""}
                    onClick={() => setView("grid")}
                  >
                    ▦
                  </button>
                  <button
                    aria-label="نمای فهرستی"
                    className={view === "list" ? "chosen" : ""}
                    onClick={() => setView("list")}
                  >
                    ☰
                  </button>
                </div>
              </section>
              <div className="sectionline">
                <h2>
                  {query ? "نتیجهٔ جست‌وجو" : "آخرین فایل‌های شما"}{" "}
                  <span>{digits(results.length)} فایل</span>
                </h2>
                <span>نمایش نمونه‌های کتابخانه</span>
              </div>
              <section className={`files ${view}`}>
                {results.map((item) => (
                  <button
                    className="filecard"
                    key={item.id}
                    onClick={() => {
                      setNotice("");
                      setSelected(item);
                    }}
                  >
                    <div className={`preview ${item.color}`}>
                      <Preview item={item} />
                      <span className="filekind">{item.kind}</span>
                    </div>
                    <div className="cardbody">
                      <span
                        className={`status ${item.status === "آماده" ? "ready" : "attention"}`}
                      >
                        {item.status === "آماده" ? "●" : "◌"} {item.status}
                      </span>
                      <h3>{item.title}</h3>
                      <div className="cardmeta">
                        <span>{item.topic}</span>
                        <span>
                          {item.id > 6
                            ? "همین حالا"
                            : `امروز · ${digits(item.id + 8)}:${digits(20 + item.id)}`}
                        </span>
                      </div>
                    </div>
                  </button>
                ))}
              </section>
              {!results.length && (
                <div className="empty">
                  فایلی با این مشخصات پیدا نشد.
                  <button
                    onClick={() => {
                      setQuery("");
                      setKind("همهٔ فایل‌ها");
                    }}
                  >
                    پاک کردن فیلترها
                  </button>
                </div>
              )}
            </>
          ) : (
            <section className="placeholder">
              <span>◇</span>
              <h2>{page}</h2>
              <p>
                {page === "صف پردازش"
                  ? "در این نمونه، پردازش واقعی انجام نمی‌شود. وضعیت فایل‌ها از نمای جزئیات قابل تغییر است."
                  : `این بخش در مرحلهٔ بعد طراحی می‌شود. فعلاً می‌توانید کتابخانه و جزئیات فایل‌ها را بررسی کنید.`}
              </p>
              <button onClick={() => setPage("کتابخانه")}>
                رفتن به کتابخانه
              </button>
            </section>
          )}
          <footer>
            <span>◈ محتوای شما، روی دستگاه شما</span>
            <span>نسخهٔ اولیهٔ طراحی · داده‌های نمایشی</span>
          </footer>
        </div>
      </main>
      {selected && (
        <div className="overlay" onClick={() => setSelected(null)}>
          <section
            className="detail"
            role="dialog"
            aria-modal="true"
            aria-label="جزئیات فایل"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="dialoghead">
              <div>
                <small>جزئیات فایل</small>
                <h2>{selected.title}</h2>
              </div>
              <button
                className="close"
                aria-label="بستن جزئیات"
                onClick={() => setSelected(null)}
              >
                ×
              </button>
            </div>
            <div className={`preview large ${selected.color}`}>
              <Preview item={selected} />
            </div>
            <span className="status">{selected.status}</span>
            <h3>متن استخراج‌شده · صفحهٔ ۱</h3>
            <p className="extracted">{selected.text}</p>
            <h3>موضوع پیشنهادی</h3>
            <select
              aria-label="موضوع فایل"
              value={selected.topic}
              onChange={(e) => update({ ...selected, topic: e.target.value })}
            >
              {["طراحی", "معماری", "آموزش", "فناوری", "زندگی", "کار"].map(
                (t) => (
                  <option key={t}>{t}</option>
                ),
              )}
            </select>
            <h3>برچسب‌ها</h3>
            <div className="tags">
              {selected.tags.map((t) => (
                <button
                  key={t}
                  title="حذف برچسب"
                  onClick={() =>
                    update({
                      ...selected,
                      tags: selected.tags.filter((x) => x !== t),
                    })
                  }
                >
                  {t} ×
                </button>
              ))}
            </div>
            <form
              className="tagform"
              onSubmit={(e) => {
                e.preventDefault();
                if (tag.trim() && !selected.tags.includes(tag.trim()))
                  update({ ...selected, tags: [...selected.tags, tag.trim()] });
                setTag("");
              }}
            >
              <input
                aria-label="برچسب جدید"
                placeholder="برچسب جدید…"
                value={tag}
                onChange={(e) => setTag(e.target.value)}
              />
              <button>افزودن</button>
            </form>
            <div className="evidence">
              این محتوا نمونهٔ نمایشی است. استخراج متن و تحلیل هوشمند هنوز به
              سرویس پردازش متصل نشده‌اند.
            </div>
            <div className="actions">
              <button
                className="primary"
                onClick={() => {
                  update({ ...selected, status: "آماده" });
                  setNotice("اصلاح شما در این نشست ثبت شد.");
                }}
              >
                تأیید و ثبت اصلاح
              </button>
              <button
                onClick={() => {
                  update({ ...selected, status: "در صف" });
                  setNotice("فایل به صف نمایشی اضافه شد.");
                }}
              >
                پردازش دوباره
              </button>
            </div>
            {notice && <p role="status">{notice}</p>}
          </section>
        </div>
      )}
      {adding && (
        <div className="overlay" onClick={() => setAdding(false)}>
          <section
            className="importdialog"
            role="dialog"
            aria-modal="true"
            aria-label="افزودن فایل"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="dialoghead">
              <h2>جای تازه‌ای برای فایل‌های شما</h2>
              <button
                className="close"
                aria-label="بستن"
                onClick={() => setAdding(false)}
              >
                ×
              </button>
            </div>
            <p>چند فایل انتخاب کنید تا به کتابخانهٔ نمایشی اضافه شوند.</p>
            <label className="dropzone">
              <span>＋</span>
              <strong>انتخاب فایل از دستگاه</strong>
              <small>سند، تصویر یا اسکرین‌شات</small>
              <input
                type="file"
                multiple
                onChange={(e) => {
                  const added = Array.from(e.target.files ?? []).map(
                    (f, index) => ({
                      id: Date.now() + index,
                      title: f.name,
                      kind: f.type.startsWith("image/") ? "تصویر" : "سند",
                      topic: "کار",
                      status: "در صف",
                      text: "فایل برای نمونهٔ رابط اضافه شده است. محتوای آن هنوز پردازش نشده است.",
                      color: "paper",
                      tags: [],
                    }),
                  );
                  setItems((current) => [...added, ...current]);
                  setAdding(false);
                }}
              />
            </label>
            <div className="evidence">
              در این نسخه فقط نام فایل ثبت می‌شود. وضعیت پردازش نمایشی است و با
              تازه‌کردن صفحه، داده‌های اولیه برمی‌گردند.
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
function Preview({ item }: { item: Item }) {
  if (item.color === "room")
    return (
      <div className="roomscene">
        <div className="window" />
        <div className="arch" />
        <div className="table" />
        <div className="vase" />
      </div>
    );
  if (item.color === "forest")
    return (
      <div className="forestscene">
        {[0, 1, 2, 3, 4, 5, 6].map((i) => (
          <i
            key={i}
            style={{ left: `${i * 16 - 5}%`, height: `${100 + (i % 3) * 20}%` }}
          />
        ))}
      </div>
    );
  if (item.color === "social")
    return (
      <div className="socialsheet">
        <small>یادداشت‌های یک ذهن کنجکاو</small>
        <b>
          کمتر بخوان،
          <br />
          عمیق‌تر یاد بگیر.
        </b>
        <span>هر روز، یک قدم کوچک</span>
      </div>
    );
  return (
    <div className="document">
      <small>
        {item.color === "report" ? "پژوهش و فناوری" : "دفتر یادداشت‌ها"}
      </small>
      <strong>{item.title}</strong>
      <div className="doclines">
        {[1, 2, 3, 4, 5].map((n) => (
          <i key={n} style={{ width: `${90 - (n % 3) * 12}%` }} />
        ))}
      </div>
      <span className="docseal">{item.color === "notes" ? "✎" : "ساهر"}</span>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
