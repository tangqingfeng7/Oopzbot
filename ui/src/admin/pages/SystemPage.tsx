import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { EdButton } from "../components/EditorialPrimitives";
import { apiReq, copyText } from "../lib/api";
import { useApp } from "../lib/context";

type LogLevelFilter = "important" | "warn" | "all";

const LOG_LINE_RE = /^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+\[([^\]]+)\]\s+(DEBUG|INFO|WARNING|ERROR|CRITICAL):\s?(.*)$/;

function renderLogLine(line: string, idx: number) {
  const m = line.match(LOG_LINE_RE);
  if (!m) {
    return (
      <div key={idx} className="ed-log-line ed-log-line--cont">
        {line || "\u00a0"}
      </div>
    );
  }
  const [, ts, src, lvl, msg] = m;
  const lvlClass =
    lvl === "ERROR" || lvl === "CRITICAL"
      ? "ed-log-line--err"
      : lvl === "WARNING"
      ? "ed-log-line--warn"
      : lvl === "DEBUG"
      ? "ed-log-line--debug"
      : "";
  return (
    <div key={idx} className={`ed-log-line ${lvlClass}`}>
      <span className="ed-log-ts">{ts}</span>
      <span className="ed-log-src">[{src}]</span>
      <span className="ed-log-lvl">{lvl}</span>
      <span className="ed-log-msg">{msg}</span>
    </div>
  );
}

export function SystemPage() {
  const { setStatus, toast, confirm } = useApp();
  const [playerLink, setPlayerLink] = useState("");
  const [sysText, setSysText] = useState("-");
  const [logLines, setLogLines] = useState<string[]>([]);
  const [tailSize, setTailSize] = useState(200);
  const [logLevel, setLogLevel] = useState<LogLevelFilter>("important");
  const [polling, setPolling] = useState(true);
  const logsRef = useRef<HTMLDivElement>(null);
  const busyRef = useRef(false);

  const loadLink = useCallback(async () => {
    const data = await apiReq<any>("/admin/api/player/link");
    setPlayerLink(data.url || "");
  }, []);

  const loadSys = useCallback(async () => {
    const data = await apiReq<any>("/admin/api/system");
    setSysText(JSON.stringify(data, null, 2));
  }, []);

  const loadLogs = useCallback(
    async (lines = tailSize, level: LogLevelFilter = logLevel) => {
      if (busyRef.current) return;
      busyRef.current = true;
      try {
        const el = logsRef.current;
        const stickBottom = !el || el.scrollTop + el.clientHeight >= el.scrollHeight - 24;
        const data = await apiReq<any>(`/admin/api/logs?tail=${lines}&level=${encodeURIComponent(level)}`);
        const nextLines: string[] = Array.isArray(data.lines)
          ? data.lines
          : Array.isArray(data.logs)
          ? data.logs
          : [];
        setLogLines(nextLines);
        if (stickBottom) {
          requestAnimationFrame(() => {
            if (logsRef.current) logsRef.current.scrollTop = logsRef.current.scrollHeight;
          });
        }
      } finally {
        busyRef.current = false;
      }
    },
    [tailSize, logLevel]
  );

  useEffect(() => {
    Promise.all([loadLink(), loadSys(), loadLogs(tailSize, logLevel)])
      .then(() => setStatus("日志轮询中", "success"))
      .catch((e) => toast(e.message, "error"));
  }, []);

  useEffect(() => {
    if (!polling) {
      setStatus("轮询已暂停", "warning");
      return;
    }
    setStatus("日志轮询中", "success");
    const id = window.setInterval(() => {
      if (!document.hidden) loadLogs(tailSize, logLevel).catch(() => {});
    }, 2000);
    return () => window.clearInterval(id);
  }, [polling, tailSize, logLevel, loadLogs, setStatus]);

  const logPlainText = useMemo(() => logLines.join("\n"), [logLines]);

  const rotateLink = async () => {
    const ok = await confirm("重置播放器链接", "重置后旧的 Web 播放器访问链接将立即失效，确认继续？", { okText: "确认重置" });
    if (!ok) return;
    try {
      const data = await apiReq<any>("/admin/api/player/link/rotate", { method: "POST", body: "{}" });
      setPlayerLink(data.url || "");
      toast("播放器链接已重置", "success");
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  const switchLevel = (next: LogLevelFilter) => {
    setLogLevel(next);
    loadLogs(tailSize, next).catch(() => {});
  };

  const switchTail = (next: number) => {
    setTailSize(next);
    loadLogs(next, logLevel).catch(() => {});
  };

  return (
    <div className="ed-chapter">
      <div className="ed-chapter-bar">
        <div className="ed-chapter-bar__left">
          <h2 className="ed-chapter-bar__title">系统</h2>
        </div>
        <div className="ed-chapter-bar__actions">
          <EdButton size="sm" variant="ghost" onClick={loadSys}>刷新状态</EdButton>
          <EdButton size="sm" variant="ghost" onClick={() => loadLogs(tailSize, logLevel)}>刷新日志</EdButton>
          <EdButton size="sm" variant={polling ? "default" : "primary"} onClick={() => setPolling((p) => !p)}>
            {polling ? "暂停轮询" : "恢复轮询"}
          </EdButton>
        </div>
      </div>

      <div className="ed-grid ed-grid--system-top">
        <section className="ed-cell" style={{ display: "flex", flexDirection: "column", justifyContent: "space-between", gap: 18 }}>
          <div className="ed-label">
            <span>播放器链接</span>
          </div>
          <input className="ed-input ed-input--mono" readOnly value={playerLink} placeholder="—" />
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            <EdButton
              size="sm"
              variant="primary"
              onClick={async () => {
                if (!playerLink) return;
                await copyText(playerLink);
                toast("链接已复制", "success");
              }}
            >
              复制链接
            </EdButton>
            <EdButton size="sm" variant="ghost" onClick={loadLink}>刷新</EdButton>
            <EdButton size="sm" variant="danger" onClick={rotateLink}>重置链接</EdButton>
          </div>
        </section>

        <section className="ed-cell ed-cell--flush" style={{ display: "flex", flexDirection: "column" }}>
          <div className="ed-cell-head">
            <div className="ed-label"><span>系统快照</span></div>
          </div>
          <pre className="ed-console" style={{ height: 220, minHeight: 0, maxHeight: "none" }}>{sysText}</pre>
        </section>
      </div>

      <section className="ed-cell ed-cell--flush" style={{ display: "flex", flexDirection: "column" }}>
        <div className="ed-cell-head" style={{ flexWrap: "wrap", gap: 10 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <div className="ed-label">
              <span>实时日志</span>
            </div>
            <div style={{ display: "flex", gap: 4 }}>
              <EdButton size="sm" variant={logLevel === "important" ? "primary" : "ghost"} onClick={() => switchLevel("important")}>
                重要
              </EdButton>
              <EdButton size="sm" variant={logLevel === "warn" ? "primary" : "ghost"} onClick={() => switchLevel("warn")}>
                警告/错误
              </EdButton>
              <EdButton size="sm" variant={logLevel === "all" ? "primary" : "ghost"} onClick={() => switchLevel("all")}>
                全部
              </EdButton>
            </div>
          </div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            <EdButton size="sm" variant={tailSize === 200 ? "default" : "ghost"} onClick={() => switchTail(200)}>
              200 行
            </EdButton>
            <EdButton size="sm" variant={tailSize === 800 ? "default" : "ghost"} onClick={() => switchTail(800)}>
              800 行
            </EdButton>
            <EdButton
              size="sm"
              variant="ghost"
              onClick={async () => {
                if (!logPlainText) return;
                await copyText(logPlainText);
                toast("日志已复制", "success");
              }}
            >
              复制
            </EdButton>
            <EdButton
              size="sm"
              variant="ghost"
              onClick={() => logsRef.current?.scrollTo({ top: logsRef.current.scrollHeight, behavior: "smooth" })}
            >
              回到底部
            </EdButton>
          </div>
        </div>
        <div ref={logsRef} className="ed-console ed-console--logs">
          {logLines.length === 0 ? (
            <div className="ed-empty" style={{ padding: "56px 20px" }}>暂无符合条件的日志</div>
          ) : (
            logLines.map(renderLogLine)
          )}
        </div>
      </section>
    </div>
  );
}
