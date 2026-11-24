import React, { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ChevronLeft, ChevronRight, Heart, RefreshCw, Search, X } from "lucide-react";
import {
  fetchLikedTracks,
  refreshLikedCache,
  safeUrl,
  searchTracks,
  type QueueSong,
} from "../lib/playerApi";

function TrackSkeletons({ count = 5 }: { count?: number }) {
  return (
    <div style={{ display: "grid", gap: 6, padding: "4px 2px" }}>
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="pl-track-row">
          <span className="pl-skel" style={{ width: 42, height: 42, borderRadius: 9 }} />
          <div style={{ flex: 1, display: "grid", gap: 6 }}>
            <span className="pl-skel" style={{ width: `${45 + (i % 3) * 16}%`, height: 13 }} />
            <span className="pl-skel" style={{ width: `${30 + (i % 2) * 18}%`, height: 10, opacity: 0.65 }} />
          </div>
          <span className="pl-skel" style={{ width: 62, height: 26, borderRadius: 999 }} />
        </div>
      ))}
    </div>
  );
}

function TrackListRow({
  song,
  added,
  adding,
  onAdd,
}: {
  song: QueueSong;
  added: boolean;
  adding: boolean;
  onAdd: () => void;
}) {
  const cover = safeUrl(song.cover);
  return (
    <div className="pl-track-row">
      {cover ? (
        <img src={cover} alt="" loading="lazy" />
      ) : (
        <div style={{ width: 42, height: 42, borderRadius: 9, background: "rgba(255,255,255,0.06)", flexShrink: 0 }} />
      )}
      <div className="pl-q-info">
        <div className="pl-q-name" title={song.name || ""}>
          {song.name || "未知歌曲"}
        </div>
        <div className="pl-q-artist">
          {(song.artists || "未知") + (song.album ? ` · ${song.album}` : "")}
        </div>
      </div>
      {song.durationText && <span className="pl-q-dur">{song.durationText}</span>}
      <button
        type="button"
        className={`pl-add-btn${added ? " is-added" : ""}`}
        disabled={adding}
        onClick={onAdd}
      >
        {adding ? "添加中" : added ? "已添加" : "加入队列"}
      </button>
    </div>
  );
}

/* ---------- Search Modal ---------- */

export function SearchModal({
  open,
  addedIds,
  onClose,
  onAddSong,
}: {
  open: boolean;
  addedIds: Set<string>;
  onClose: () => void;
  onAddSong: (song: QueueSong) => Promise<void>;
}) {
  const [kw, setKw] = useState("");
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<QueueSong[]>([]);
  const [error, setError] = useState("");
  const [addingId, setAddingId] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      setKw("");
      setResults([]);
      setError("");
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const clean = kw.trim();
    if (!clean) {
      setResults([]);
      setError("");
      setLoading(false);
      return;
    }
    const ctrl = new AbortController();
    setLoading(true);
    setError("");
    const timer = window.setTimeout(async () => {
      try {
        const list = await searchTracks(clean, ctrl.signal);
        setResults(list);
      } catch (e: any) {
        if (e?.name !== "AbortError") setError("搜索失败，请重试");
      } finally {
        if (!ctrl.signal.aborted) setLoading(false);
      }
    }, 320);
    return () => {
      window.clearTimeout(timer);
      ctrl.abort();
    };
  }, [open, kw]);

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="pl-overlay"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.18 }}
          onClick={onClose}
        >
          <motion.div
            className="pl-modal"
            initial={{ opacity: 0, y: -16, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -10, scale: 0.97 }}
            transition={{ type: "spring", stiffness: 460, damping: 34 }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="pl-modal__search">
              <Search size={17} style={{ color: "var(--pl-ink-faint)", flexShrink: 0 }} />
              <input
                ref={inputRef}
                value={kw}
                onChange={(e) => setKw(e.target.value)}
                placeholder="搜索歌曲、歌手..."
                onKeyDown={(e) => {
                  if (e.key === "Escape") onClose();
                }}
              />
              <button type="button" className="pl-tool-btn pl-tool-btn--icon" onClick={onClose} aria-label="关闭">
                <X size={15} />
              </button>
            </div>

            <div className="pl-modal__body">
              {loading ? (
                <TrackSkeletons count={5} />
              ) : error ? (
                <div className="pl-empty">{error}</div>
              ) : !kw.trim() ? (
                <div className="pl-empty">输入关键词搜索音乐</div>
              ) : results.length === 0 ? (
                <div className="pl-empty">未找到相关歌曲</div>
              ) : (
                results.map((song) => {
                  const sid = String(song.id);
                  return (
                    <TrackListRow
                      key={sid}
                      song={song}
                      added={addedIds.has(sid)}
                      adding={addingId === sid}
                      onAdd={async () => {
                        setAddingId(sid);
                        try {
                          await onAddSong(song);
                        } finally {
                          setAddingId(null);
                        }
                      }}
                    />
                  );
                })
              )}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

/* ---------- Liked Songs Modal ---------- */

export function LikedModal({
  open,
  addedIds,
  onClose,
  onAddSong,
}: {
  open: boolean;
  addedIds: Set<string>;
  onClose: () => void;
  onAddSong: (song: QueueSong) => Promise<void>;
}) {
  const [kw, setKw] = useState("");
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);
  const [total, setTotal] = useState(0);
  const [songs, setSongs] = useState<QueueSong[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [addingId, setAddingId] = useState<string | null>(null);
  const ctrlRef = useRef<AbortController | null>(null);

  const loadPage = useCallback(async (targetPage: number, keyword: string) => {
    ctrlRef.current?.abort();
    const ctrl = new AbortController();
    ctrlRef.current = ctrl;
    setLoading(true);
    setError("");
    try {
      const res = await fetchLikedTracks(targetPage, keyword, ctrl.signal);
      if (ctrl.signal.aborted) return;
      if (res.error) {
        setError(res.error);
        setSongs([]);
        return;
      }
      setSongs(res.songs);
      setPage(res.page);
      setPages(res.pages);
      setTotal(res.total);
    } catch (e: any) {
      if (e?.name !== "AbortError") setError("加载失败，请重试");
    } finally {
      if (!ctrl.signal.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!open) {
      ctrlRef.current?.abort();
      return;
    }
    setKw("");
    loadPage(1, "");
  }, [open, loadPage]);

  useEffect(() => {
    if (!open) return;
    const timer = window.setTimeout(() => loadPage(1, kw), 280);
    return () => window.clearTimeout(timer);
  }, [kw, open, loadPage]);

  const handleRefresh = async () => {
    setLoading(true);
    try {
      await refreshLikedCache();
    } catch {
      // ignore
    }
    setKw("");
    await loadPage(1, "");
  };

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="pl-overlay"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.18 }}
          onClick={onClose}
        >
          <motion.div
            className="pl-modal"
            initial={{ opacity: 0, y: -16, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -10, scale: 0.97 }}
            transition={{ type: "spring", stiffness: 460, damping: 34 }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="pl-modal__head">
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <Heart size={16} style={{ color: "var(--pl-accent-hover)" }} />
                <strong style={{ fontSize: 15 }}>喜欢的音乐</strong>
                {total > 0 && <span className="pl-badge">{total} 首</span>}
              </div>
              <div style={{ display: "flex", gap: 6 }}>
                <button type="button" className="pl-tool-btn pl-tool-btn--icon" onClick={handleRefresh} title="刷新列表">
                  <RefreshCw size={14} />
                </button>
                <button type="button" className="pl-tool-btn pl-tool-btn--icon" onClick={onClose} aria-label="关闭">
                  <X size={15} />
                </button>
              </div>
            </div>

            <div className="pl-modal__search">
              <Search size={16} style={{ color: "var(--pl-ink-faint)", flexShrink: 0 }} />
              <input
                value={kw}
                onChange={(e) => setKw(e.target.value)}
                placeholder="在喜欢列表中搜索歌曲、歌手、专辑..."
              />
            </div>

            <div className="pl-modal__body">
              {loading ? (
                <TrackSkeletons count={6} />
              ) : error ? (
                <div className="pl-empty">{error}</div>
              ) : songs.length === 0 ? (
                <div className="pl-empty">{kw.trim() ? "未找到匹配的歌曲" : "喜欢列表为空"}</div>
              ) : (
                songs.map((song) => {
                  const sid = String(song.id);
                  return (
                    <TrackListRow
                      key={sid}
                      song={song}
                      added={addedIds.has(sid)}
                      adding={addingId === sid}
                      onAdd={async () => {
                        setAddingId(sid);
                        try {
                          await onAddSong(song);
                        } finally {
                          setAddingId(null);
                        }
                      }}
                    />
                  );
                })
              )}
            </div>

            {pages > 1 && (
              <footer className="pl-pager">
                <button
                  type="button"
                  className="pl-tool-btn"
                  disabled={page <= 1 || loading}
                  onClick={() => loadPage(page - 1, kw)}
                >
                  <ChevronLeft size={14} />
                  <span>上一页</span>
                </button>
                <span style={{ fontFamily: "var(--pl-mono)", fontSize: 12, color: "var(--pl-ink-faint)" }}>
                  {page} / {pages}
                </span>
                <button
                  type="button"
                  className="pl-tool-btn"
                  disabled={page >= pages || loading}
                  onClick={() => loadPage(page + 1, kw)}
                >
                  <span>下一页</span>
                  <ChevronRight size={14} />
                </button>
              </footer>
            )}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
