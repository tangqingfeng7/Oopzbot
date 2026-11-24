import React, { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Clock, Disc3, Languages } from "lucide-react";
import type { LyricLine } from "../lib/playerApi";

export function LyricsPanel({
  playing,
  lyrics,
  progress,
  offsetSec,
  showTrans,
  onToggleTrans,
  onAdjustOffset,
  onResetOffset,
  onSeekLine,
}: {
  playing: boolean;
  lyrics: LyricLine[];
  progress: number;
  offsetSec: number;
  showTrans: boolean;
  onToggleTrans: () => void;
  onAdjustOffset: (delta: number) => void;
  onResetOffset: () => void;
  onSeekLine: (timeSec: number) => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const lineRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const userScrollUntilRef = useRef(0);
  const [syncOpen, setSyncOpen] = useState(false);

  const hasTrans = useMemo(() => lyrics.some((l) => Boolean(l.ttext)), [lyrics]);

  const activeIdx = useMemo(() => {
    if (!lyrics.length) return -1;
    const t = progress + offsetSec;
    for (let i = lyrics.length - 1; i >= 0; i--) {
      if (t >= lyrics[i].time) return i;
    }
    return -1;
  }, [lyrics, progress, offsetSec]);

  useEffect(() => {
    if (!syncOpen) return;
    const close = () => setSyncOpen(false);
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, [syncOpen]);

  useEffect(() => {
    if (activeIdx < 0) return;
    if (Date.now() < userScrollUntilRef.current) return;
    const container = scrollRef.current;
    const el = lineRefs.current[activeIdx];
    if (!container || !el) return;
    const top = el.offsetTop - container.clientHeight * 0.42 + el.clientHeight / 2;
    container.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
  }, [activeIdx, showTrans]);

  const offsetText = `${offsetSec >= 0 ? "+" : ""}${offsetSec}s`;

  return (
    <section className="pl-lyrics-stage">
      {playing && (
        <div className={`pl-lyrics__tools${syncOpen ? " is-open" : ""}`}>
          <div style={{ position: "relative" }} onClick={(e) => e.stopPropagation()}>
            <button
              type="button"
              className={`pl-pill-btn${offsetSec !== 0 ? " is-active" : ""}`}
              style={{ height: 30, padding: "0 11px", fontSize: 11.5 }}
              onClick={() => setSyncOpen((o) => !o)}
              title="歌词时间偏移调节"
            >
              <Clock size={12} />
              <span>{offsetSec === 0 ? "同步" : offsetText}</span>
            </button>

            <AnimatePresence>
              {syncOpen && (
                <motion.div
                  className="pl-sync-popover"
                  initial={{ opacity: 0, y: -6, scale: 0.96 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: -4, scale: 0.96 }}
                  transition={{ duration: 0.16, ease: [0.22, 1, 0.36, 1] }}
                >
                  <button type="button" onClick={() => onAdjustOffset(-1)}>-1s</button>
                  <button type="button" onClick={() => onAdjustOffset(-0.5)}>-0.5s</button>
                  <button type="button" onClick={() => onAdjustOffset(0.5)}>+0.5s</button>
                  <button type="button" onClick={() => onAdjustOffset(1)}>+1s</button>
                  <button type="button" onClick={onResetOffset}>重置</button>
                  <span style={{ fontFamily: "var(--pl-mono)", fontSize: 11, color: "var(--pl-ink-faint)", paddingLeft: 2 }}>
                    {offsetText}
                  </span>
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          {hasTrans && (
            <button
              type="button"
              className={`pl-pill-btn${showTrans ? " is-active" : ""}`}
              style={{ height: 30, padding: "0 11px", fontSize: 11.5 }}
              onClick={onToggleTrans}
              title="切换翻译歌词"
            >
              <Languages size={12} />
              <span>译</span>
            </button>
          )}
        </div>
      )}

      {!lyrics.length ? (
        <div className="pl-empty">
          <Disc3 size={36} style={{ opacity: 0.28 }} />
          <span>{playing ? "纯音乐或暂无歌词" : "音乐响起后歌词将在此浮现"}</span>
        </div>
      ) : (
        <div
          ref={scrollRef}
          className="pl-lyrics__scroll"
          onWheel={() => {
            userScrollUntilRef.current = Date.now() + 3600;
          }}
          onTouchStart={() => {
            userScrollUntilRef.current = Date.now() + 3600;
          }}
        >
          {lyrics.map((line, i) => {
            const dist = activeIdx >= 0 ? Math.abs(i - activeIdx) : 99;
            const cls =
              i === activeIdx
                ? "pl-lyric-line is-active"
                : dist <= 2
                ? "pl-lyric-line is-near"
                : "pl-lyric-line";
            return (
              <button
                key={`${i}-${line.time}`}
                ref={(el) => {
                  lineRefs.current[i] = el;
                }}
                type="button"
                className={cls}
                title="点击跳转到此处"
                onClick={() => {
                  userScrollUntilRef.current = 0;
                  onSeekLine(Math.max(0, line.time - offsetSec));
                }}
              >
                <p className="pl-lyric-line__main">{line.text}</p>
                {showTrans && line.ttext && <p className="pl-lyric-line__trans">{line.ttext}</p>}
              </button>
            );
          })}
        </div>
      )}
    </section>
  );
}
