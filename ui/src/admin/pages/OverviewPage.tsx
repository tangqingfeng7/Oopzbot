import React, { useCallback, useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { ChevronRight } from "lucide-react";
import { AnimatedNumber, EdButton } from "../components/EditorialPrimitives";
import { adminUrl, apiReq, formatDuration } from "../lib/api";
import { useApp } from "../lib/context";

interface OverviewData {
  redis?: string;
  uptime_seconds?: number;
  queue_length?: number;
  today_messages?: number;
  active_users_today?: number;
  statistics_summary?: { total_plays?: number };
}

function AmbientWave({ active, pulseSeq }: { active: boolean; pulseSeq: number }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const pulseRef = useRef(0);

  useEffect(() => {
    pulseRef.current = 1;
  }, [pulseSeq]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    let raf = 0;
    let t = 0;

    const draw = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const w = canvas.clientWidth || 400;
      const h = canvas.clientHeight || 56;
      if (canvas.width !== Math.floor(w * dpr) || canvas.height !== Math.floor(h * dpr)) {
        canvas.width = Math.floor(w * dpr);
        canvas.height = Math.floor(h * dpr);
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);

      pulseRef.current = Math.max(0, pulseRef.current * 0.94);
      const amp = active ? 8 + pulseRef.current * 11 : 2.5;
      t += active ? 0.026 : 0.008;

      const grad = ctx.createLinearGradient(0, 0, w, 0);
      if (active) {
        grad.addColorStop(0, "rgba(10, 132, 255, 0.15)");
        grad.addColorStop(0.5, "rgba(64, 156, 255, 0.95)");
        grad.addColorStop(1, "rgba(90, 200, 250, 0.2)");
      } else {
        grad.addColorStop(0, "rgba(255, 255, 255, 0.06)");
        grad.addColorStop(0.5, "rgba(255, 255, 255, 0.28)");
        grad.addColorStop(1, "rgba(255, 255, 255, 0.06)");
      }

      ctx.strokeStyle = grad;
      ctx.lineWidth = 2;
      ctx.beginPath();
      for (let x = 0; x <= w; x += 3) {
        const nx = x / w;
        const env = Math.sin(nx * Math.PI);
        const y =
          h / 2 +
          Math.sin(nx * 9 + t) * amp * env +
          Math.sin(nx * 19 - t * 1.3) * (amp * 0.32) * env;
        if (x === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();

      ctx.strokeStyle = active ? "rgba(90, 200, 250, 0.35)" : "rgba(255, 255, 255, 0.1)";
      ctx.lineWidth = 1.2;
      ctx.beginPath();
      for (let x = 0; x <= w; x += 3) {
        const nx = x / w;
        const env = Math.sin(nx * Math.PI);
        const y =
          h / 2 +
          Math.sin(nx * 7 - t * 0.85) * (amp * 0.72) * env;
        if (x === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();

      raf = requestAnimationFrame(draw);
    };

    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [active]);

  return <canvas ref={canvasRef} className="ed-wave-canvas" />;
}

const cardMotion = (i: number) => ({
  initial: { opacity: 0, y: 12 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.32, delay: i * 0.035, ease: [0.22, 1, 0.36, 1] as const },
});

export function OverviewPage() {
  const { setStatus, navigate, navItems } = useApp();
  const [data, setData] = useState<OverviewData>({});
  const [streaming, setStreaming] = useState(true);
  const [pulseSeq, setPulseSeq] = useState(0);
  const esRef = useRef<EventSource | null>(null);
  const reconnectRef = useRef<number | null>(null);

  const loadOnce = useCallback(async () => {
    const res = await apiReq<OverviewData>("/admin/api/overview");
    setData(res);
    setPulseSeq((s) => s + 1);
    setStatus("已同步", "success");
  }, [setStatus]);

  const stopStream = useCallback(() => {
    if (reconnectRef.current) {
      window.clearTimeout(reconnectRef.current);
      reconnectRef.current = null;
    }
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }
  }, []);

  const startStream = useCallback(() => {
    stopStream();
    setStatus("连接中", "warning");
    const connect = () => {
      const es = new EventSource(adminUrl("/admin/api/overview/stream"), { withCredentials: true });
      esRef.current = es;
      es.addEventListener("overview", (ev) => {
        try {
          const parsed = JSON.parse((ev as MessageEvent).data || "{}");
          setData(parsed);
          setPulseSeq((s) => s + 1);
          setStatus("实时连接", "success");
        } catch {
          setStatus("解析失败", "error");
        }
      });
      es.onerror = () => {
        es.close();
        esRef.current = null;
        setStatus("重连中", "warning");
        reconnectRef.current = window.setTimeout(connect, 1400);
      };
    };
    connect();
  }, [setStatus, stopStream]);

  useEffect(() => {
    loadOnce().catch(() => {});
    if (streaming) startStream();
    else {
      stopStream();
      setStatus("已暂停", "warning");
    }
    const onVis = () => {
      if (document.hidden) stopStream();
      else if (streaming) startStream();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      document.removeEventListener("visibilitychange", onVis);
      stopStream();
    };
  }, [loadOnce, startStream, stopStream, streaming, setStatus]);

  const uptime = Number(data.uptime_seconds ?? 0);
  const totalPlays = Number(data.statistics_summary?.total_plays ?? 0);
  const quickTargets = ["music", "config", "members", "plugins", "system"]
    .map((k) => navItems.find((n) => n.key === k))
    .filter((x): x is NonNullable<typeof x> => Boolean(x));

  return (
    <div className="ed-chapter">
      <div className="ed-chapter-bar">
        <div className="ed-chapter-bar__left">
          <h2 className="ed-chapter-bar__title">总览</h2>
        </div>
        <div className="ed-chapter-bar__actions">
          <EdButton size="sm" variant="ghost" onClick={loadOnce}>立即同步</EdButton>
          <EdButton
            size="sm"
            variant={streaming ? "default" : "primary"}
            onClick={() => setStreaming((v) => !v)}
          >
            {streaming ? "暂停实时流" : "恢复实时流"}
          </EdButton>
        </div>
      </div>

      <div className="ed-grid ed-grid--overview-top">
        <motion.section {...cardMotion(0)} className="ed-cell ed-cell--airy ed-hero-cell">
          <div>
            <div className="ed-label">
              <span>累计播放</span>
            </div>
            <div className="ed-num-hero">
              <AnimatedNumber value={totalPlays} />
            </div>
          </div>
          <AmbientWave active={streaming} pulseSeq={pulseSeq} />
        </motion.section>

        <section className="ed-telemetry-col">
          <motion.div {...cardMotion(1)} className="ed-cell ed-cell--hover">
            <div className="ed-label">
              <span>Redis</span>
              <span className={`ed-live-dot ${data.redis === "connected" ? "ed-live-dot--success" : "ed-live-dot--warning"}`} />
            </div>
            <div
              className="ed-num-md"
              style={{
                color: data.redis === "connected" ? "var(--ok)" : "var(--ink)",
              }}
            >
              {data.redis === "connected" ? "已连接" : data.redis || "—"}
            </div>
          </motion.div>

          <motion.div {...cardMotion(2)} className="ed-cell ed-cell--hover">
            <div className="ed-label">
              <span>运行时长</span>
            </div>
            <div className="ed-num-md">
              {formatDuration(uptime)}
            </div>
            <div className="ed-mono-sub">
              <AnimatedNumber value={uptime} /> s
            </div>
          </motion.div>

          <motion.div {...cardMotion(3)} className="ed-cell ed-cell--hover">
            <div className="ed-label">
              <span>待播队列</span>
            </div>
            <div className="ed-num-lg">
              <AnimatedNumber value={Number(data.queue_length ?? 0)} />
            </div>
          </motion.div>
        </section>
      </div>

      <div className="ed-grid ed-grid--overview-bottom">
        <motion.section {...cardMotion(4)} className="ed-cell ed-cell--hover">
          <div className="ed-label">
            <span>今日消息</span>
          </div>
          <div className="ed-num-lg">
            <AnimatedNumber value={Number(data.today_messages ?? 0)} />
          </div>
        </motion.section>

        <motion.section {...cardMotion(5)} className="ed-cell ed-cell--hover">
          <div className="ed-label">
            <span>今日活跃</span>
          </div>
          <div className="ed-num-lg">
            <AnimatedNumber value={Number(data.active_users_today ?? 0)} />
          </div>
        </motion.section>

        <motion.section {...cardMotion(6)} className="ed-cell">
          <div className="ed-label">
            <span>快捷入口</span>
          </div>
          <div className="ed-quick-links">
            {quickTargets.map((item) => (
              <button
                key={item.key}
                type="button"
                className="ed-quick-link"
                onClick={() => navigate(item.key)}
              >
                <span>{item.label}</span>
                <ChevronRight size={15} className="ed-quick-link__arrow" />
              </button>
            ))}
          </div>
        </motion.section>
      </div>
    </div>
  );
}
