export type PlayModeId = "list" | "single" | "shuffle" | "stop";

export interface PlayModeMeta {
  id: PlayModeId;
  label: string;
}

export const PLAY_MODES: readonly PlayModeMeta[] = [
  { id: "list", label: "顺序播放" },
  { id: "single", label: "单曲循环" },
  { id: "shuffle", label: "随机播放" },
  { id: "stop", label: "停止播放" },
];

export interface PlayerStatus {
  playing?: boolean;
  id?: string | number;
  name?: string;
  artists?: string;
  album?: string;
  cover?: string;
  duration?: number;
  durationText?: string;
  progress?: number;
  server_time?: number;
  paused?: boolean;
  loading?: boolean;
  volume?: number;
  mode?: PlayModeId;
  platform?: string;
}

export interface QueueSong {
  id: string | number;
  name?: string;
  artists?: string;
  album?: string;
  cover?: string;
  duration?: number;
  durationText?: string;
  platform?: string;
  _current?: boolean;
  [k: string]: unknown;
}

export interface LyricLine {
  time: number;
  text: string;
  ttext?: string;
}

declare global {
  interface Window {
    __OOPZ_AREA__?: string;
  }
}

export function getPinnedArea(): string {
  return typeof window !== "undefined" && typeof window.__OOPZ_AREA__ === "string"
    ? window.__OOPZ_AREA__
    : "";
}

export function apiUrl(path: string): string {
  const area = getPinnedArea();
  if (!area) return path;
  return `${path}${path.includes("?") ? "&" : "?"}area=${encodeURIComponent(area)}`;
}

export function normalizePlatform(value?: string | null): string {
  return String(value || "netease").trim().toLowerCase() || "netease";
}

const PLATFORM_LABELS: Record<string, string> = {
  netease: "NETEASE",
  qq: "QQ MUSIC",
  bilibili: "BILIBILI",
};

export function platformLabel(platform?: string | null): string {
  const norm = normalizePlatform(platform);
  return PLATFORM_LABELS[norm] || norm.toUpperCase();
}

export function clampVolume(value: unknown, fallback = 50): number {
  const parsed = Number.parseInt(String(value ?? ""), 10);
  if (Number.isNaN(parsed)) return fallback;
  return Math.min(100, Math.max(0, parsed));
}

export function fmtTime(sec: number): string {
  const safe = !sec || sec < 0 || !Number.isFinite(sec) ? 0 : sec;
  const m = Math.floor(safe / 60);
  const s = Math.floor(safe % 60);
  return `${m}:${s < 10 ? "0" : ""}${s}`;
}

export function safeUrl(u: unknown): string {
  const s = String(u ?? "").trim();
  return /^https?:\/\//i.test(s) ? s : "";
}

export function parseLRC(lrc?: string | null): { time: number; text: string }[] {
  if (!lrc) return [];
  const lines: { time: number; text: string }[] = [];
  const re = /\[(\d{1,3}):(\d{2})(?:\.(\d{1,3}))?\]/g;
  for (const raw of lrc.split("\n")) {
    re.lastIndex = 0;
    const times: number[] = [];
    let match: RegExpExecArray | null;
    while ((match = re.exec(raw)) !== null) {
      const min = Number.parseInt(match[1], 10);
      const sec = Number.parseInt(match[2], 10);
      const ms = match[3] ? Number.parseInt(match[3].padEnd(3, "0"), 10) : 0;
      times.push(min * 60 + sec + ms / 1000);
    }
    const text = raw.replace(/\[.*?\]/g, "").trim();
    if (text) {
      for (const time of times) lines.push({ time, text });
    }
  }
  lines.sort((a, b) => a.time - b.time);
  return lines;
}

export function mergeLyrics(rawLrc?: string | null, rawTlyric?: string | null): LyricLine[] {
  const base = parseLRC(rawLrc);
  const trans = parseLRC(rawTlyric);
  if (!trans.length) return base;
  return base.map((line) => {
    const hit = trans.find((t) => Math.abs(t.time - line.time) < 0.55);
    return hit ? { ...line, ttext: hit.text } : line;
  });
}

export async function fetchPlayerStatus(signal?: AbortSignal): Promise<PlayerStatus> {
  const r = await fetch(apiUrl("/api/status"), { signal, cache: "no-store" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function fetchPlayerQueue(signal?: AbortSignal): Promise<QueueSong[]> {
  const r = await fetch(apiUrl("/api/queue"), { signal, cache: "no-store" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  const d = await r.json();
  return Array.isArray(d.queue) ? d.queue : [];
}

export async function fetchPlayerLyric(
  id: string | number,
  platform: string,
  signal?: AbortSignal
): Promise<{ lyric: string; tlyric: string }> {
  const query = new URLSearchParams({
    id: String(id),
    platform: normalizePlatform(platform),
  });
  const r = await fetch(apiUrl(`/api/lyric?${query.toString()}`), { signal });
  if (!r.ok) return { lyric: "", tlyric: "" };
  const d = await r.json();
  return { lyric: String(d.lyric || ""), tlyric: String(d.tlyric || "") };
}

export async function sendControl(payload: Record<string, unknown>): Promise<{ ok: boolean; error?: string }> {
  const r = await fetch(apiUrl("/api/control"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return r.json();
}

export async function sendQueueAction(
  action: "top" | "remove",
  index: number
): Promise<{ ok: boolean; error?: string }> {
  const r = await fetch(apiUrl("/api/queue/action"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, index }),
  });
  return r.json();
}

export async function searchTracks(keyword: string, signal?: AbortSignal): Promise<QueueSong[]> {
  const r = await fetch(apiUrl(`/api/search?keyword=${encodeURIComponent(keyword)}`), { signal });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  const d = await r.json();
  return (Array.isArray(d.results) ? d.results : []).filter((s: QueueSong) => s && s.id);
}

export async function addTrackToQueue(song: QueueSong): Promise<{ ok: boolean; error?: string }> {
  const r = await fetch(apiUrl("/api/add"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(song),
  });
  return r.json();
}

export async function fetchLikedTracks(
  page: number,
  keyword: string,
  signal?: AbortSignal
): Promise<{ songs: QueueSong[]; page: number; pages: number; total: number; error?: string }> {
  const kw = keyword.trim();
  const path = `/api/liked?page=${Math.max(1, page)}&limit=30${kw ? `&keyword=${encodeURIComponent(kw)}` : ""}`;
  const r = await fetch(apiUrl(path), { signal });
  const d = await r.json();
  return {
    songs: (Array.isArray(d.songs) ? d.songs : []).filter((s: QueueSong) => s && s.id),
    page: Number(d.page || 1),
    pages: Number(d.pages || 1),
    total: Number(d.total || 0),
    error: d.error ? String(d.error) : undefined,
  };
}

export async function refreshLikedCache(): Promise<void> {
  await fetch(apiUrl("/api/liked/refresh"), { method: "POST" });
}
