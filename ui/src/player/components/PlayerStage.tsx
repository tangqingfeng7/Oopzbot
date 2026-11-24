import React, { useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Disc3,
  ListMusic,
  Pause,
  Play,
  Repeat1,
  Shuffle,
  SkipForward,
  Square,
  Volume2,
  VolumeX,
} from "lucide-react";
import {
  fmtTime,
  platformLabel,
  PLAY_MODES,
  safeUrl,
  type PlayModeId,
  type PlayerStatus,
} from "../lib/playerApi";

function ModeIcon({ mode }: { mode: PlayModeId }) {
  switch (mode) {
    case "single":
      return <Repeat1 size={17} />;
    case "shuffle":
      return <Shuffle size={17} />;
    case "stop":
      return <Square size={15} />;
    default:
      return <ListMusic size={17} />;
  }
}

export function PlayerStage({
  status,
  progress,
  volume,
  playMode,
  onTogglePause,
  onNext,
  onCycleMode,
  onSeekCommit,
  onSeekPreview,
  onVolumeChange,
  onVolumeCommit,
  onOpenSearch,
}: {
  status: PlayerStatus | null;
  progress: number;
  volume: number;
  playMode: PlayModeId;
  onTogglePause: () => void;
  onNext: () => void;
  onCycleMode: () => void;
  onSeekPreview: (sec: number | null) => void;
  onSeekCommit: (sec: number) => void;
  onVolumeChange: (val: number) => void;
  onVolumeCommit: (val: number) => void;
  onOpenSearch: () => void;
}) {
  const playing = Boolean(status?.playing);
  const paused = Boolean(status?.paused);
  const loading = Boolean(status?.loading);
  const spinning = playing && !paused && !loading;
  const duration = Number(status?.duration || 0);
  const coverUrl = safeUrl(status?.cover);
  const modeMeta = PLAY_MODES.find((m) => m.id === playMode) || PLAY_MODES[0];

  const seekTrackRef = useRef<HTMLDivElement>(null);
  const volTrackRef = useRef<HTMLDivElement>(null);
  const [draggingSeek, setDraggingSeek] = useState(false);
  const [draggingVol, setDraggingVol] = useState(false);
  const [dragSec, setDragSec] = useState(0);
  const [tilt, setTilt] = useState({ rx: 0, ry: 0 });

  const calcRatio = (el: HTMLDivElement | null, clientX: number) => {
    if (!el) return 0;
    const rect = el.getBoundingClientRect();
    if (!rect.width) return 0;
    return Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
  };

  const displaySec = draggingSeek ? dragSec : progress;
  const pct = duration > 0 ? Math.min(100, Math.max(0, (displaySec / duration) * 100)) : 0;

  return (
    <section className="pl-deck">
      {/* Floating Album Sleeve + Sliding Vinyl Record */}
      <div
        className="pl-turntable"
        onMouseMove={(e) => {
          const rect = e.currentTarget.getBoundingClientRect();
          const nx = (e.clientX - rect.left) / rect.width - 0.5;
          const ny = (e.clientY - rect.top) / rect.height - 0.5;
          setTilt({ rx: -ny * 8, ry: nx * 8 });
        }}
        onMouseLeave={() => setTilt({ rx: 0, ry: 0 })}
      >
        <motion.div
          className="pl-vinyl"
          animate={{
            x: spinning ? "24%" : playing ? "10%" : "0%",
            opacity: playing ? 1 : 0.35,
          }}
          transition={{ type: "spring", stiffness: 180, damping: 24 }}
        >
          <div className={`pl-vinyl__rotor${spinning ? "" : " is-paused"}`}>
            <div className="pl-vinyl__sheen" />
            <div className="pl-vinyl__label">
              {coverUrl && <img src={coverUrl} alt="" />}
            </div>
            <div className="pl-vinyl__spindle" />
          </div>
        </motion.div>

        <div
          className="pl-sleeve"
          style={{ transform: `rotateX(${tilt.rx}deg) rotateY(${tilt.ry}deg)` }}
        >
          <AnimatePresence mode="wait">
            {coverUrl ? (
              <motion.img
                key={coverUrl}
                src={coverUrl}
                alt=""
                className="pl-sleeve__img"
                initial={{ opacity: 0, scale: 1.08 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.96 }}
                transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
              />
            ) : (
              <div key="idle-sleeve" className="pl-sleeve__placeholder">
                <Disc3 size={64} strokeWidth={1.3} />
              </div>
            )}
          </AnimatePresence>
          <div className="pl-sleeve__shine" />
        </div>
      </div>

      {/* Song Meta */}
      <div className="pl-info">
        {playing && status ? (
          <AnimatePresence mode="wait">
            <motion.div
              key={`${status.platform || "netease"}:${status.id}`}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
              style={{ display: "grid", gap: 5 }}
            >
              <div className="pl-info__top">
                <h2 className="pl-info__title" title={status.name || ""}>
                  {status.name || "未知歌曲"}
                </h2>
                <span className="pl-tag">{platformLabel(status.platform)}</span>
              </div>
              <div className="pl-info__sub">
                {(status.artists || "未知歌手") + (status.album ? ` · ${status.album}` : "")}
              </div>
            </motion.div>
          </AnimatePresence>
        ) : (
          <div style={{ display: "grid", gap: 8 }}>
            <h2 className="pl-info__title" style={{ color: "rgba(255,255,255,0.75)" }}>等待播放</h2>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span className="pl-info__sub">当前没有正在播放的曲目</span>
              <button type="button" className="pl-pill-btn" style={{ height: 28, fontSize: 12 }} onClick={onOpenSearch}>
                去点歌
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Progress Scrubber */}
      <div className="pl-progress">
        <div
          ref={seekTrackRef}
          className={`pl-slider${draggingSeek ? " is-dragging" : ""}`}
          onPointerDown={(e) => {
            if (!duration) return;
            e.currentTarget.setPointerCapture(e.pointerId);
            const sec = calcRatio(seekTrackRef.current, e.clientX) * duration;
            setDraggingSeek(true);
            setDragSec(sec);
            onSeekPreview(sec);
          }}
          onPointerMove={(e) => {
            if (!draggingSeek || !duration) return;
            const sec = calcRatio(seekTrackRef.current, e.clientX) * duration;
            setDragSec(sec);
            onSeekPreview(sec);
          }}
          onPointerUp={(e) => {
            if (!draggingSeek) return;
            setDraggingSeek(false);
            const sec = duration ? calcRatio(seekTrackRef.current, e.clientX) * duration : 0;
            onSeekPreview(null);
            onSeekCommit(sec);
          }}
          onPointerCancel={() => {
            setDraggingSeek(false);
            onSeekPreview(null);
          }}
        >
          <div className="pl-slider__rail">
            <div className="pl-slider__fill" style={{ width: `${pct}%` }} />
          </div>
          <div className="pl-slider__thumb" style={{ left: `${pct}%` }} />
        </div>
        <div className="pl-times">
          <span>{fmtTime(displaySec)}</span>
          <span>{status?.durationText || fmtTime(duration)}</span>
        </div>
      </div>

      {/* Sculpted Transport + Volume */}
      <div className="pl-transport">
        <div className="pl-transport__main">
          <button
            type="button"
            className="pl-round-btn"
            onClick={onCycleMode}
            title={`播放模式：${modeMeta.label}（点击切换）`}
          >
            <ModeIcon mode={playMode} />
          </button>

          <button
            type="button"
            className="pl-play-fab"
            disabled={!playing}
            onClick={onTogglePause}
            title={paused ? "继续播放 (Space)" : "暂停 (Space)"}
            aria-label={paused ? "继续播放" : "暂停"}
          >
            {paused ? <Play size={24} fill="currentColor" style={{ marginLeft: 2 }} /> : <Pause size={24} fill="currentColor" />}
          </button>

          <button
            type="button"
            className="pl-round-btn"
            onClick={onNext}
            title="下一首 (→)"
            aria-label="下一首"
          >
            <SkipForward size={18} />
          </button>
        </div>

        <div className="pl-vol">
          {volume === 0 ? <VolumeX size={15} /> : <Volume2 size={15} />}
          <div
            ref={volTrackRef}
            className={`pl-slider${draggingVol ? " is-dragging" : ""}`}
            style={{ flex: 1 }}
            onPointerDown={(e) => {
              e.currentTarget.setPointerCapture(e.pointerId);
              const val = Math.round(calcRatio(volTrackRef.current, e.clientX) * 100);
              setDraggingVol(true);
              onVolumeChange(val);
            }}
            onPointerMove={(e) => {
              if (!draggingVol) return;
              const val = Math.round(calcRatio(volTrackRef.current, e.clientX) * 100);
              onVolumeChange(val);
            }}
            onPointerUp={(e) => {
              if (!draggingVol) return;
              setDraggingVol(false);
              const val = Math.round(calcRatio(volTrackRef.current, e.clientX) * 100);
              onVolumeChange(val);
              onVolumeCommit(val);
            }}
            onPointerCancel={() => setDraggingVol(false)}
          >
            <div className="pl-slider__rail">
              <div className="pl-slider__fill" style={{ width: `${volume}%` }} />
            </div>
            <div className="pl-slider__thumb" style={{ left: `${volume}%` }} />
          </div>
          <span className="pl-vol__pct">{volume}</span>
        </div>
      </div>
    </section>
  );
}
