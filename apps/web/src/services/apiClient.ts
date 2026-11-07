import { FileItem, StatsResponse, HealthResponse, FileUpdatePayload } from "../types/archive";

// Seed fallback data used if backend is not yet active or in offline simulation
export const INITIAL_FALLBACK_FILES: FileItem[] = [
  {
    id: "seed-1",
    archive_id: "default",
    title: "یادداشت‌های طراحی و معماری.txt",
    kind: "سند",
    topic: "طراحی",
    status: "آماده",
    mime_type: "text/plain",
    file_size: 1420,
    sha256: "8f4e2c3b1a",
    text: "طراحی خوب از شناخت مسئله آغاز می‌شود. در این یادداشت، اصول طراحی یک محصول ساده، خوانا و قابل استفاده را مرور می‌کنیم.",
    color: "paper",
    tags: ["طراحی محصول", "یادداشت"],
    page_count: 1,
    created_at: new Date().toISOString(),
  },
  {
    id: "seed-2",
    archive_id: "default",
    title: "رنگ، فضا و زندگی روزمره.png",
    kind: "تصویر",
    topic: "معماری",
    status: "آماده",
    mime_type: "image/png",
    file_size: 423000,
    sha256: "3d2b1a9c8e",
    text: "تصویری از یک فضای آرام با نور طبیعی، دیوارهای روشن و جزئیات سبز. این توصیف، برداشت نمایشی مدل است.",
    color: "room",
    tags: ["فضای داخلی", "الهام"],
    page_count: 1,
    created_at: new Date().toISOString(),
  },
  {
    id: "seed-3",
    archive_id: "default",
    title: "چطور بهتر یاد بگیریم؟.png",
    kind: "اسکرین‌شات",
    topic: "آموزش",
    status: "نیازمند بازبینی",
    mime_type: "image/png",
    file_size: 212000,
    sha256: "7a6b5c4d3e",
    text: "یادگیری عمیق با تمرین‌های کوتاه و پیوسته شکل می‌گیرد. بین مطالعه‌ها فاصله بگذارید و آنچه آموخته‌اید را با زبان خودتان بازگو کنید.",
    color: "social",
    tags: ["یادگیری", "مطالعه"],
    page_count: 1,
    created_at: new Date().toISOString(),
  },
  {
    id: "seed-4",
    archive_id: "default",
    title: "گزارش پژوهش‌های هوش مصنوعی.txt",
    kind: "سند",
    topic: "فناوری",
    status: "آماده",
    mime_type: "text/plain",
    file_size: 5120,
    sha256: "1f2e3d4c5b",
    text: "این گزارش به بررسی کاربرد مدل‌های زبانی در دسته‌بندی و بازیابی اسناد می‌پردازد.",
    color: "report",
    tags: ["پژوهش", "هوش مصنوعی"],
    page_count: 1,
    created_at: new Date().toISOString(),
  },
  {
    id: "seed-5",
    archive_id: "default",
    title: "سفر به جنگل‌های شمال.png",
    kind: "تصویر",
    topic: "زندگی",
    status: "آماده",
    mime_type: "image/png",
    file_size: 890000,
    sha256: "9e8d7c6b5a",
    text: "جنگلی مه‌آلود با درختان بلند و مسیر باریک میان پوشش سبز.",
    color: "forest",
    tags: ["طبیعت", "سفر"],
    page_count: 1,
    created_at: new Date().toISOString(),
  },
  {
    id: "seed-6",
    archive_id: "default",
    title: "دست‌نوشته‌های جلسهٔ محصول.txt",
    kind: "سند",
    topic: "کار",
    status: "تحلیل ناقص",
    mime_type: "text/plain",
    file_size: 2400,
    sha256: "4b5c6d7e8f",
    text: "موضوع جلسه، ساده‌سازی ورود فایل و نمایش روشن وضعیت پردازش بود. بخشی از نوشته در نمونه خوانا نیست.",
    color: "notes",
    tags: ["جلسه", "محصول"],
    page_count: 1,
    created_at: new Date().toISOString(),
  },
];

const LOCAL_STORAGE_KEY = "saher_offline_archive_files_v1";

class LocalStorageArchive {
  private static getStored(): FileItem[] {
    try {
      const data = localStorage.getItem(LOCAL_STORAGE_KEY);
      if (data) {
        return JSON.parse(data);
      }
    } catch (e) {
      console.warn("Could not read localStorage archive", e);
    }
    return INITIAL_FALLBACK_FILES;
  }

  private static setStored(files: FileItem[]): void {
    try {
      localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(files));
    } catch (e) {
      console.warn("Could not write to localStorage archive", e);
    }
  }

  static listFiles(kind?: string, query?: string, status?: string): FileItem[] {
    let list = this.getStored();
    if (kind && kind !== "همهٔ فایل‌ها") {
      list = list.filter((f) => f.kind === kind);
    }
    if (status) {
      list = list.filter((f) => f.status === status);
    }
    if (query && query.trim()) {
      const q = query.trim().toLowerCase();
      list = list.filter(
        (f) =>
          f.title.toLowerCase().includes(q) ||
          f.text.toLowerCase().includes(q) ||
          f.tags.some((t) => t.toLowerCase().includes(q))
      );
    }
    return list;
  }

  static getFile(fileId: string): FileItem | undefined {
    return this.getStored().find((f) => f.id === fileId);
  }

  static async importFile(file: File, topic?: string): Promise<FileItem> {
    const list = this.getStored();
    let text = "";
    if (file.type.startsWith("text/") || file.name.endsWith(".txt") || file.name.endsWith(".md")) {
      try {
        text = await file.text();
      } catch (e) {
        text = "خطا در استخراج متن فایل";
      }
    } else {
      text = file.type.startsWith("image/")
        ? "تصویر بارگذاری شد. آمادهٔ پردازش هوشمند دیداری و OCR."
        : "سند بارگذاری شد. استخراج متن ساختاریافته.";
    }

    const isImage = file.type.startsWith("image/");
    const kind = isImage ? (file.name.includes("screen") ? "اسکرین‌شات" : "تصویر") : "سند";
    const color = isImage ? (kind === "اسکرین‌شات" ? "social" : "room") : "paper";

    const newItem: FileItem = {
      id: "local-" + Date.now(),
      archive_id: "default",
      title: file.name,
      kind,
      topic: topic || "کار",
      status: "آماده",
      mime_type: file.type || "application/octet-stream",
      file_size: file.size,
      sha256: "sha-" + Math.random().toString(36).substring(2, 10),
      text: text || "محتوای استخراج‌شده از فایل ورودی کاربر",
      color,
      tags: ["افزودهٔ اخیر"],
      page_count: 1,
      created_at: new Date().toISOString(),
    };

    const updated = [newItem, ...list];
    this.setStored(updated);
    return newItem;
  }

  static updateFile(fileId: string, payload: FileUpdatePayload): FileItem | undefined {
    const list = this.getStored();
    let updatedItem: FileItem | undefined;
    const next = list.map((item) => {
      if (item.id === fileId) {
        updatedItem = {
          ...item,
          topic: payload.topic !== undefined ? payload.topic : item.topic,
          status: payload.status !== undefined ? payload.status : item.status,
          tags: payload.tags !== undefined ? payload.tags : item.tags,
        };
        return updatedItem;
      }
      return item;
    });
    this.setStored(next);
    return updatedItem;
  }

  static resetToDefault(): void {
    this.setStored(INITIAL_FALLBACK_FILES);
  }
}

export class ArchiveApiClient {
  private static baseUrl = "/api/v1";

  static async checkHealth(): Promise<HealthResponse> {
    try {
      const resp = await fetch("/health");
      if (resp.ok) {
        return await resp.json();
      }
    } catch (e) {
      // Backend not running in this environment
    }
    return {
      status: "offline_storage_fallback",
      version: "0.1.0",
      database: "browser_local_storage",
      storage_accessible: true,
    };
  }

  static async getStats(): Promise<StatsResponse> {
    try {
      const resp = await fetch(`${this.baseUrl}/stats`);
      if (resp.ok) {
        return await resp.json();
      }
    } catch (e) {
      // Fallback
    }
    const all = LocalStorageArchive.listFiles();
    return {
      total_files: all.length,
      ready_files: all.filter((i) => i.status === "آماده").length,
      attention_files: all.filter((i) => i.status !== "آماده").length,
    };
  }

  static async listFiles(kind?: string, query?: string, status?: string): Promise<FileItem[]> {
    try {
      const params = new URLSearchParams();
      if (kind && kind !== "همهٔ فایل‌ها") params.set("kind", kind);
      if (query && query.trim()) params.set("query", query.trim());
      if (status) params.set("status", status);

      const resp = await fetch(`${this.baseUrl}/files?${params.toString()}`);
      if (resp.ok) {
        return await resp.json();
      }
    } catch (e) {
      // Fallback
    }
    return LocalStorageArchive.listFiles(kind, query, status);
  }

  static async getFile(fileId: string): Promise<FileItem | undefined> {
    try {
      const resp = await fetch(`${this.baseUrl}/files/${fileId}`);
      if (resp.ok) {
        return await resp.json();
      }
    } catch (e) {
      // Fallback
    }
    return LocalStorageArchive.getFile(fileId);
  }

  static async importFile(file: File, topic?: string): Promise<FileItem> {
    try {
      const formData = new FormData();
      formData.append("file", file);
      if (topic) formData.append("topic", topic);

      const resp = await fetch(`${this.baseUrl}/files/import`, {
        method: "POST",
        body: formData,
      });
      if (resp.ok) {
        return await resp.json();
      }
    } catch (e) {
      // Fallback
    }
    return LocalStorageArchive.importFile(file, topic);
  }

  static async updateFile(fileId: string, payload: FileUpdatePayload): Promise<FileItem | undefined> {
    try {
      const resp = await fetch(`${this.baseUrl}/files/${fileId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (resp.ok) {
        return await resp.json();
      }
    } catch (e) {
      // Fallback
    }
    return LocalStorageArchive.updateFile(fileId, payload);
  }

  static async addTag(fileId: string, tag: string): Promise<FileItem | undefined> {
    try {
      const resp = await fetch(`${this.baseUrl}/files/${fileId}/tags`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tag }),
      });
      if (resp.ok) {
        return await resp.json();
      }
    } catch (e) {
      // Fallback
    }
    const current = LocalStorageArchive.getFile(fileId);
    if (!current) return undefined;
    const newTags = Array.from(new Set([...current.tags, tag]));
    return LocalStorageArchive.updateFile(fileId, { tags: newTags });
  }

  static async removeTag(fileId: string, tag: string): Promise<FileItem | undefined> {
    try {
      const resp = await fetch(`${this.baseUrl}/files/${fileId}/tags/${encodeURIComponent(tag)}`, {
        method: "DELETE",
      });
      if (resp.ok) {
        return await resp.json();
      }
    } catch (e) {
      // Fallback
    }
    const current = LocalStorageArchive.getFile(fileId);
    if (!current) return undefined;
    const newTags = current.tags.filter((t) => t !== tag);
    return LocalStorageArchive.updateFile(fileId, { tags: newTags });
  }

  static resetFallbackStorage(): void {
    LocalStorageArchive.resetToDefault();
  }
}
