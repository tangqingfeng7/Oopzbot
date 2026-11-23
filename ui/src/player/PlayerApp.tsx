import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Heart, ListMusic, Radio, RefreshCw, Search } from "lucide-react";
import {
  addTrackToQueue,
  clampVolume,
  fetchPlayerLyric,
  fetchPlayerQueue,
  fetchPlayerStatus,
  mergeLyrics,
  normalizePlatform,
  PLAY_MODES,
  safeUrl,
  sendControl,
  sendQueueAction,
  type LyricLine,
  type PlayModeId,
  type PlayerStatus,
  type QueueSong,
} from "./lib/playerApi";
import { PlayerStage } from "./components/PlayerStage";
import { LyricsPanel } from "./components/LyricsPanel";
import { QueueDrawer } from "./components/QueuePanel";
import { LikedModal, SearchModal } from "./components/TrackModals";

export function PlayerApp() {
  const [status, setStatus] = useState<PlayerStatus | null>(null);
  const [waitQueue, setWaitQueue] = useState<QueueSong[]>([]);
  const [lyrics, setLyrics] = useState<LyricLine[]>([]);
  const [connected, setConnected] = useState(true);

  const [playMode, setPlayMode] = useState<PlayModeId>("list");
  const [volume, setVolume] = useState<number>(() =>
    clampVolume(localStorage.getItem("webVolume"), 50)
  );
  const [progress, setProgress] = useState(0);
  const [seekPreview, setSeekPreview] = useState<number | null>(null);

  const [showTrans, setShowTrans] = useState(false);
  const [offsetSec, setOffsetSec] = useState<number>(
    () => parseFloat(localStorage.getItem("lyricOffset") || "0") || 0
  );

  const [queueOpen, setQueueOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [likedOpen, setLikedOpen] = useState(false);
  const [addedIds, setAddedIds] = useState<Set<string>>(() => new Set());
  const [toastMsg, setToastMsg] = useState<{ id: number; text: string } | null>(null);

  const progressBaseRef = useRef({ sec: 0, ts: Date.now() });
  const volumeLockRef = useRef(false);
  const volumeTimerRef = useRef<number | null>(null);
  const lastTrackKeyRef = useRef("");
  const lastErrTsRef = useRef(0);
  const toastTimerRef = useRef<number | null>(null);
  const lyricAbortRef = useRef<AbortController | null>(null);

  const toast = useCallback((text: string) => {
    setToastMsg({ id: Date.now(), text });
    if (toastTimerRef.current) window.clearTimeout(toastTimerRef.current);
    toastTimerRef.current = window.setTimeout(() => setToastMsg(null), 2400);
  }, []);

  const syncQueue = useCallback(async () => {
    try {
      const list = await fetchPlayerQueue();
      setWaitQueue(list);
    } catch {
      // ignore transient network errors
    }
  }, []);

  const syncStatus = useCallback(async () => {
    try {
      const d = await fetchPlayerStatus();
      setConnected(true);
      setStatus(d);

      if (d.volume !== undefined && !volumeLockRef.current) {
        const clamped = clampVolume(d.volume, 50);
        setVolume(clamped);
        localStorage.setItem("webVolume", String(clamped));
      }
      if (d.mode && PLAY_MODES.some((m) => m.id === d.mode)) {
        setPlayMode(d.mode);
      }

      if (!d.playing) {
        if (lastTrackKeyRef.current !== "") {
          lastTrackKeyRef.current = "";
          lyricAbortRef.current?.abort();
          setLyrics([]);
          setProgress(0);
        }
        return;
      }

      const platform = normalizePlatform(d.platform);
      const trackKey = `${platform}:${d.id}`;
      if (trackKey !== lastTrackKeyRef.current) {
        lastTrackKeyRef.current = trackKey;
        lyricAbortRef.current?.abort();
        const ctrl = new AbortController();
        lyricAbortRef.current = ctrl;
        fetchPlayerLyric(d.id ?? "", platform, ctrl.signal)
          .then(({ lyric, tlyric }) => {
            if (!ctrl.signal.aborted) {
              setLyrics(mergeLyrics(lyric, tlyric));
            }
          })
          .catch(() => {
            if (!ctrl.signal.aborted) setLyrics([]);
          });
        syncQueue();
      }

      let baseSec = Number(d.progress || 0);
      if (d.loading) {
        baseSec = 0;
      } else if (d.server_time) {
        const delay = Date.now() / 1000 - Number(d.server_time);
        baseSec += Math.max(0, delay);
      }
      progressBaseRef.current = { sec: baseSec, ts: Date.now() };
      setProgress(Math.min(baseSec, Number(d.duration || 0) || baseSec));
    } catch {
      const now = Date.now();
      if (now - lastErrTsRef.current > 4000) {
        lastErrTsRef.current = now;
        setConnected(false);
      }
    }
  }, [syncQueue]);

  useEffect(() => {
    syncStatus();
    syncQueue();
    const sId = window.setInterval(() => {
      if (!document.hidden) syncStatus();
    }, 1000);
    const qId = window.setInterval(() => {
      if (!document.hidden) syncQueue();
    }, 5000);
    const onVis = () => {
      if (!document.hidden) {
        syncStatus();
        syncQueue();
      }
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      window.clearInterval(sId);
      window.clearInterval(qId);
      document.removeEventListener("visibilitychange", onVis);
      lyricAbortRef.current?.abort();
    };
  }, [syncStatus, syncQueue]);

  useEffect(() => {
    if (!status?.playing || status.paused || status.loading || !status.duration) return;
    const duration = Number(status.duration);
    const id = window.setInterval(() => {
      if (seekPreview !== null) return;
      const { sec, ts } = progressBaseRef.current;
      const next = Math.min(duration, sec + (Date.now() - ts) / 1000);
      setProgress(next);
    }, 120);
    return () => window.clearInterval(id);
  }, [status?.playing, status?.paused, status?.loading, status?.duration, seekPreview]);

  const handleTogglePause = useCallback(async () => {
    if (!status?.playing) return;
    const nextPaused = !status.paused;
    const action = nextPaused ? "pause" : "resume";
    setStatus((prev) => (prev ? { ...prev, paused: nextPaused } : prev));
    try {
      const res = await sendControl({ action });
      if (res.ok) toast(nextPaused ? "已暂停" : "继续播放");
      else toast(res.error || "操作失败");
    } catch {
      toast("操作失败：网络错误");
    }
  }, [status?.playing, status?.paused, toast]);

  const handleControl = useCallback(
    async (action: "next" | "clear") => {
      try {
        const res = await sendControl({ action });
        if (res.ok) {
          toast(action === "next" ? "已切换下一首" : "队列已清空");
          window.setTimeout(() => {
            syncStatus();
            syncQueue();
          }, 350);
        } else {
          toast(res.error || "操作失败");
        }
      } catch {
        toast("操作失败：网络错误");
      }
    },
    [syncQueue, syncStatus, toast]
  );

  const handleCycleMode = useCallback(async () => {
    const idx = PLAY_MODES.findIndex((m) => m.id === playMode);
    const next = PLAY_MODES[(idx + 1) % PLAY_MODES.length];
    const prev = playMode;
    setPlayMode(next.id);
    try {
      const res = await sendControl({ action: "mode", value: next.id });
      if (res.ok) toast(`已切换到：${next.label}`);
      else {
        setPlayMode(prev);
        toast(res.error || "切换失败");
      }
    } catch {
      setPlayMode(prev);
      toast("切换失败：网络错误");
    }
  }, [playMode, toast]);

  const handleSeek = useCallback(async (sec: number) => {
    progressBaseRef.current = { sec, ts: Date.now() };
    setProgress(sec);
    try {
      await sendControl({ action: "seek", time: Math.round(sec) });
    } catch {
      // ignore
    }
  }, []);

  const handleVolumeChange = useCallback((val: number) => {
    const clamped = clampVolume(val, 50);
    volumeLockRef.current = true;
    setVolume(clamped);
    localStorage.setItem("webVolume", String(clamped));
  }, []);

  const handleVolumeCommit = useCallback((val: number) => {
    const clamped = clampVolume(val, 50);
    if (volumeTimerRef.current) window.clearTimeout(volumeTimerRef.current);
    volumeTimerRef.current = window.setTimeout(() => {
      sendControl({ action: "volume", value: clamped }).catch(() => {});
      window.setTimeout(() => {
        volumeLockRef.current = false;
      }, 900);
    }, 160);
  }, []);

  const handleQueueAction = useCallback(
    async (action: "top" | "remove", redisIdx: number) => {
      try {
        const res = await sendQueueAction(action, redisIdx);
        if (res.ok) {
          toast(action === "top" ? "已置顶" : "已移除");
          syncQueue();
        } else {
          toast(res.error || "操作失败");
        }
      } catch {
        toast("操作失败");
      }
    },
    [syncQueue, toast]
  );

  const handleAddSong = useCallback(
    async (song: QueueSong) => {
      try {
        const res = await addTrackToQueue(song);
        if (res.ok) {
          setAddedIds((prev) => new Set(prev).add(String(song.id)));
          toast(`已加入队列：${song.name || "未知歌曲"}`);
          syncQueue();
        } else {
          toast(res.error || "添加失败");
        }
      } catch {
        toast("添加失败：网络错误");
      }
    },
    [syncQueue, toast]
  );

  const adjustOffset = (delta: number) => {
    setOffsetSec((prev) => {
      const next = Math.round((prev + delta) * 10) / 10;
      localStorage.setItem("lyricOffset", String(next));
      toast(`歌词已${delta > 0 ? "延后" : "提前"} ${Math.abs(delta)} 秒`);
      return next;
    });
  };

  const resetOffset = () => {
    setOffsetSec(0);
    localStorage.setItem("lyricOffset", "0");
    toast("歌词偏移已重置");
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName;
      const inInput = tag === "INPUT" || tag === "TEXTAREA";
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setLikedOpen(false);
        setQueueOpen(false);
        setSearchOpen((o) => !o);
        return;
      }
      if (e.key === "Escape") {
        setSearchOpen(false);
        setLikedOpen(false);
        setQueueOpen(false);
        return;
      }
      if (inInput || searchOpen || likedOpen) return;
      if (e.key === "/") {
        e.preventDefault();
        setQueueOpen(false);
        setSearchOpen(true);
      } else if (e.key.toLowerCase() === "l") {
        e.preventDefault();
        setQueueOpen(false);
        setLikedOpen(true);
      } else if (e.key.toLowerCase() === "q") {
        e.preventDefault();
        setQueueOpen((o) => !o);
      } else if (e.code === "Space") {
        e.preventDefault();
        handleTogglePause();
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        handleControl("next");
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [searchOpen, likedOpen, handleTogglePause, handleControl]);

  const fullQueue = useMemo<QueueSong[]>(() => {
    const out: QueueSong[] = [];
    if (status?.playing && status.id != null) {
      out.push({
        id: status.id,
        name: status.name,
        artists: status.artists,
        cover: status.cover,
        durationText: status.durationText,
        platform: status.platform,
        _current: true,
      });
    }
    return out.concat(waitQueue);
  }, [status, waitQueue]);

  const upNext = waitQueue[0] || null;
  const ambientCover = status?.playing ? safeUrl(status.cover) : "";
  const effectiveProgress = seekPreview !== null ? seekPreview : progress;

  return (
    <>
      <div className="pl-ambient" aria-hidden="true">
        <AnimatePresence>
          {ambientCover && (
            <motion.div
              key={ambientCover}
              style={{ position: "absolute", inset: 0 }}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 1.2, ease: "easeInOut" }}
            >
              <img src={ambientCover} alt="" className="pl-ambient__layer pl-ambient__layer--a" />
              <img src={ambientCover} alt="" className="pl-ambient__layer pl-ambient__layer--b" />
            </motion.div>
          )}
        </AnimatePresence>
        <div className="pl-ambient__veil" />
        <div className="pl-ambient__grain" />
      </div>

      <div className="pl-shell">
        <header className="pl-topbar">
          <div className="pl-brand">
            <Radio size={17} style={{ opacity: 0.9 }} />
            <h1 className="pl-brand__title">Oopz Music</h1>
            <span className={`pl-conn${connected ? "" : " is-err"}`}>
              <span className="pl-conn__dot" />
              <span>{connected ? "已连接" : "连接断开"}</span>
            </span>
          </div>

          <div className="pl-tools">
            <button
              type="button"
              className={`pl-pill-btn${queueOpen ? " is-active" : ""}`}
              onClick={() => setQueueOpen((o) => !o)}
              title="播放队列 (Q)"
            >
              <ListMusic size={14} />
              <span>队列</span>
              <span className="pl-count-dot">{fullQueue.length}</span>
            </button>

            <button
              type="button"
              className="pl-pill-btn"
              onClick={() => setLikedOpen(true)}
              title="喜欢的音乐 (L)"
            >
              <Heart size={14} />
              <span>喜欢</span>
            </button>

            <button
              type="button"
              className="pl-pill-btn"
              onClick={() => setSearchOpen(true)}
              title="搜索点歌 (/)"
            >
              <Search size={14} />
              <span>点歌</span>
              <span className="pl-kbd">/</span>
            </button>

            <button
              type="button"
              className="pl-pill-btn pl-pill-btn--icon"
              onClick={() => {
                syncStatus();
                syncQueue();
                toast("已同步");
              }}
              title="刷新状态"
            >
              <RefreshCw size={14} />
            </button>
          </div>
        </header>

        <main className="pl-canvas">
          <PlayerStage
            status={status}
            progress={effectiveProgress}
            volume={volume}
            playMode={playMode}
            onTogglePause={handleTogglePause}
            onNext={() => handleControl("next")}
            onCycleMode={handleCycleMode}
            onSeekPreview={setSeekPreview}
            onSeekCommit={handleSeek}
            onVolumeChange={handleVolumeChange}
            onVolumeCommit={handleVolumeCommit}
            onOpenSearch={() => setSearchOpen(true)}
          />

          <LyricsPanel
            playing={Boolean(status?.playing)}
            lyrics={lyrics}
            progress={effectiveProgress}
            offsetSec={offsetSec}
            showTrans={showTrans}
            onToggleTrans={() => setShowTrans((v) => !v)}
            onAdjustOffset={adjustOffset}
            onResetOffset={resetOffset}
            onSeekLine={handleSeek}
          />
        </main>
      </div>

      {/* Subtle Floating Up-Next Chip */}
      <AnimatePresence>
        {upNext && !queueOpen && (
          <motion.button
            key={`upnext-${upNext.id}`}
            type="button"
            className="pl-upnext"
            initial={{ opacity: 0, y: 14, scale: 0.94 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 10, scale: 0.94 }}
            transition={{ type: "spring", stiffness: 380, damping: 30 }}
            onClick={() => setQueueOpen(true)}
            title="打开播放队列"
          >
            {safeUrl(upNext.cover) && <img src={safeUrl(upNext.cover)} alt="" />}
            <div className="pl-upnext__text">
              <div className="pl-upnext__kicker">即将播放</div>
              <div className="pl-upnext__name">{upNext.name || "未知歌曲"}</div>
            </div>
          </motion.button>
        )}
      </AnimatePresence>

      <QueueDrawer
        open={queueOpen}
        items={fullQueue}
        onClose={() => setQueueOpen(false)}
        onClear={() => handleControl("clear")}
        onAction={handleQueueAction}
      />

      <SearchModal
        open={searchOpen}
        addedIds={addedIds}
        onClose={() => setSearchOpen(false)}
        onAddSong={handleAddSong}
      />

      <LikedModal
        open={likedOpen}
        addedIds={addedIds}
        onClose={() => setLikedOpen(false)}
        onAddSong={handleAddSong}
      />

      <div className="pl-toast-wrap" aria-live="polite">
        <AnimatePresence>
          {toastMsg && (
            <motion.div
              key={toastMsg.id}
              className="pl-toast"
              initial={{ opacity: 0, y: 12, scale: 0.94 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 8, scale: 0.94 }}
              transition={{ type: "spring", stiffness: 440, damping: 32 }}
            >
              {toastMsg.text}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </>
  );
}
