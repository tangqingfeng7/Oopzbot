export interface NavItem {
  key: string;
  href: string;
  label: string;
  code: string;
  isPlugin?: boolean;
}

export interface PluginNavSeed {
  key: string;
  href: string;
  label: string;
}

export const CORE_NAV_ITEMS: NavItem[] = [
  { key: "dashboard", href: "/admin", label: "总览", code: "OVERVIEW" },
  { key: "music", href: "/admin/music", label: "音乐", code: "AUDIO" },
  { key: "config", href: "/admin/config", label: "配置", code: "SETTINGS" },
  { key: "stats", href: "/admin/stats", label: "统计", code: "ARCHIVE" },
  { key: "members", href: "/admin/members", label: "成员", code: "ROSTER" },
  { key: "areas", href: "/admin/areas", label: "域管理", code: "SPACES" },
  { key: "plugins", href: "/admin/plugins", label: "插件", code: "MODULES" },
  { key: "system", href: "/admin/system", label: "系统", code: "RUNTIME" },
];

export function readInitialPluginNav(): PluginNavSeed[] {
  try {
    const raw = document.getElementById("pluginNavigation")?.textContent || "[]";
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function buildNavItems(plugins: PluginNavSeed[]): NavItem[] {
  const mapped: NavItem[] = plugins.map((p) => ({
    key: p.key,
    href: p.href,
    label: p.label,
    code: p.key.toUpperCase().replace(/[^A-Z0-9]+/g, " "),
    isPlugin: true,
  }));
  return [...CORE_NAV_ITEMS, ...mapped];
}

export function pageKeyFromPath(pathname: string, nav: NavItem[]): string {
  const clean = pathname.replace(/\/+$/, "") || "/admin";
  const matched = nav.find((item) => item.href.replace(/\/+$/, "") === clean);
  if (matched) return matched.key;
  const fromBody = document.body.dataset.adminPage;
  if (fromBody && nav.some((item) => item.key === fromBody)) return fromBody;
  return "dashboard";
}

export async function apiReq<T = Record<string, any>>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    credentials: "include",
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      ...(options?.headers || {}),
    },
    ...(options || {}),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.ok === false) {
    const detail = Array.isArray(data.errors) && data.errors.length > 0
      ? data.errors.join(" | ")
      : "";
    throw new Error(data.error || detail || `HTTP ${response.status}`);
  }
  return data as T;
}

export async function copyText(value: string): Promise<void> {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    await navigator.clipboard.writeText(value);
    return;
  }
  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "readonly");
  textarea.style.position = "absolute";
  textarea.style.left = "-9999px";
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand("copy");
  document.body.removeChild(textarea);
}

export function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const mins = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  if (days > 0) return `${days}d ${pad(hours)}h ${pad(mins)}m ${pad(secs)}s`;
  return `${pad(hours)}h ${pad(mins)}m ${pad(secs)}s`;
}

const AREA_ORDER_KEY = "adminAreaOrder";

export interface AreaItem {
  id: string;
  name?: string;
  code?: string;
}

export function applyAreaOrder<T extends AreaItem>(areas: T[]): T[] {
  try {
    const raw = window.localStorage.getItem(AREA_ORDER_KEY);
    const saved: string[] = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(saved) || !saved.length) return areas;
    const byId = new Map(areas.map((a) => [a.id, a]));
    const ordered: T[] = [];
    for (const id of saved) {
      const hit = byId.get(id);
      if (hit) {
        ordered.push(hit);
        byId.delete(id);
      }
    }
    for (const a of areas) {
      if (byId.has(a.id)) ordered.push(a);
    }
    return ordered;
  } catch {
    return areas;
  }
}

export function saveAreaOrder(ids: string[]): void {
  try {
    window.localStorage.setItem(AREA_ORDER_KEY, JSON.stringify(ids));
  } catch {
    // ignore
  }
}
