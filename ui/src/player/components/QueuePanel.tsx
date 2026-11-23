import React from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowUpToLine, ListMusic, Trash2, X } from "lucide-react";
import { safeUrl, type QueueSong } from "../lib/playerApi";

export function QueueDrawer({
  open,
  items,
  onClose,
  onClear,
  onAction,
}: {
  open: boolean;
  items: QueueSong[];
  onClose: () => void;
  onClear: () => void;
  onAction: (action: "top" | "remove", redisIdx: number) => void;
}) {
  const hasCurrent = items.length > 0 && Boolean(items[0]._current);

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            className="pl-drawer-backdrop"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={onClose}
          />
          <motion.aside
            className="pl-drawer"
            initial={{ x: 42, opacity: 0, scale: 0.98 }}
            animate={{ x: 0, opacity: 1, scale: 1 }}
            exit={{ x: 36, opacity: 0, scale: 0.98 }}
            transition={{ type: "spring", stiffness: 420, damping: 34 }}
          >
            <header className="pl-drawer__head">
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <ListMusic size={16} />
                <strong style={{ fontSize: 15 }}>播放队列</strong>
                <span className="pl-badge">{items.length} 首</span>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                {items.length > (hasCurrent ? 1 : 0) && (
                  <button
                    type="button"
                    className="pl-tool-btn"
                    style={{ height: 28, fontSize: 11.5 }}
                    onClick={onClear}
                    title="清空待播队列"
                  >
                    <Trash2 size={12} />
                    <span>清空</span>
                  </button>
                )}
                <button type="button" className="pl-tool-btn pl-tool-btn--icon" onClick={onClose} aria-label="关闭">
                  <X size={15} />
                </button>
              </div>
            </header>

            <div className="pl-drawer__list">
              {items.length === 0 ? (
                <div className="pl-empty">
                  <ListMusic size={30} style={{ opacity: 0.26 }} />
                  <span>队列为空</span>
                </div>
              ) : (
                <AnimatePresence initial={false}>
                  {items.map((song, i) => {
                    const isNow = Boolean(song._current);
                    const redisIdx = hasCurrent ? i - 1 : i;
                    const cover = safeUrl(song.cover);
                    const key = `${isNow ? "now" : "q"}-${song.platform || "netease"}-${song.id}-${i}`;

                    return (
                      <motion.div
                        key={key}
                        layout
                        initial={{ opacity: 0, y: 6 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, scale: 0.96 }}
                        transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
                        className={`pl-q-item${isNow ? " is-now" : ""}`}
                      >
                        <span className="pl-q-idx">{isNow ? "▶" : i + 1}</span>
                        {cover ? (
                          <img className="pl-q-cover" src={cover} alt="" loading="lazy" />
                        ) : (
                          <div className="pl-q-cover" />
                        )}
                        <div className="pl-q-info">
                          <div className="pl-q-name" title={song.name || ""}>
                            {song.name || "未知歌曲"}
                          </div>
                          <div className="pl-q-artist">{song.artists || "未知歌手"}</div>
                        </div>
                        <span className="pl-q-dur">{song.durationText || ""}</span>

                        {!isNow && (
                          <div className="pl-q-actions">
                            <button
                              type="button"
                              className="pl-q-act-btn"
                              title="置顶"
                              onClick={() => onAction("top", redisIdx)}
                            >
                              <ArrowUpToLine size={13} />
                            </button>
                            <button
                              type="button"
                              className="pl-q-act-btn pl-q-act-btn--del"
                              title="移除"
                              onClick={() => onAction("remove", redisIdx)}
                            >
                              <X size={13} />
                            </button>
                          </div>
                        )}
                      </motion.div>
                    );
                  })}
                </AnimatePresence>
              )}
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
