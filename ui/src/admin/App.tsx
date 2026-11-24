import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Command, LogOut } from "lucide-react";
import {
  CommandPalette,
  ConfirmDialog,
  EdButton,
  ToastStack,
  type ConfirmState,
  type ToastItem,
} from "./components/EditorialPrimitives";
import {
  adminUrl,
  apiReq,
  buildNavItems,
  pageKeyFromPath,
  readInitialPluginNav,
  type PluginNavSeed,
} from "./lib/api";
import { AppContext, type StatusKind } from "./lib/context";
import { OverviewPage } from "./pages/OverviewPage";
import { MusicPage } from "./pages/MusicPage";
import { ConfigPage } from "./pages/ConfigPage";
import { StatsPage } from "./pages/StatsPage";
import { MembersPage } from "./pages/MembersPage";
import { AreasPage } from "./pages/AreasPage";
import { PluginsPage } from "./pages/PluginsPage";
import { SystemPage } from "./pages/SystemPage";
import {
  ActivityPage,
  KeywordReplyPage,
  SchedulerPage,
  ScreenSharePage,
} from "./pages/PluginPages";

const pageVariants = {
  enter: (dir: number) => ({
    opacity: 0,
    x: dir >= 0 ? 22 : -22,
    scale: 0.988,
    filter: "blur(6px)",
  }),
  center: {
    opacity: 1,
    x: 0,
    scale: 1,
    filter: "blur(0px)",
  },
  exit: (dir: number) => ({
    opacity: 0,
    x: dir >= 0 ? -18 : 18,
    scale: 0.992,
    filter: "blur(4px)",
  }),
};

export function App() {
  const [pluginNav, setPluginNav] = useState<PluginNavSeed[]>(() => readInitialPluginNav());
  const navItems = useMemo(() => buildNavItems(pluginNav), [pluginNav]);

  const [activeKey, setActiveKey] = useState<string>(() =>
    pageKeyFromPath(window.location.pathname, buildNavItems(readInitialPluginNav()))
  );
  const [direction, setDirection] = useState<number>(1);
  const [authed, setAuthed] = useState<boolean | null>(null);

  const [pwd, setPwd] = useState("");
  const [showPwd, setShowPwd] = useState(false);
  const [loginErr, setLoginErr] = useState("");
  const [shakeSeq, setShakeSeq] = useState(0);

  const [statusText, setStatusText] = useState("检查会话");
  const [statusKind, setStatusKind] = useState<StatusKind>("warning");
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const [confirmState, setConfirmState] = useState<ConfirmState | null>(null);
  const [cmdkOpen, setCmdkOpen] = useState(false);

  const toastIdRef = useRef(1);

  const toast = useCallback((text: string, kind: ToastItem["kind"] = "info") => {
    const clean = text.trim();
    if (!clean) return;
    const id = toastIdRef.current++;
    setToasts((prev) => [...prev.slice(-3), { id, text: clean, kind }]);
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, kind === "error" ? 4200 : 2800);
  }, []);

  const confirm = useCallback(
    (title: string, message: string, opts?: { okText?: string; danger?: boolean }) =>
      new Promise<boolean>((resolve) => {
        setConfirmState({
          title,
          message,
          okText: opts?.okText,
          danger: opts?.danger,
          resolve: (ok) => {
            setConfirmState(null);
            resolve(ok);
          },
        });
      }),
    []
  );

  const setStatus = useCallback((text: string, kind: StatusKind = "neutral") => {
    setStatusText(text);
    setStatusKind(kind);
  }, []);

  const hasPlugin = useCallback(
    (key: string) => pluginNav.some((p) => p.key === key),
    [pluginNav]
  );

  const refreshPluginNav = useCallback(async () => {
    try {
      const resp = await fetch(adminUrl("/admin"), { credentials: "include", cache: "no-store" });
      if (!resp.ok) return;
      const html = await resp.text();
      const match = html.match(/<script[^>]*id="pluginNavigation"[^>]*>([\s\S]*?)<\/script>/i);
      if (match && match[1]) {
        const parsed = JSON.parse(match[1]);
        if (Array.isArray(parsed)) setPluginNav(parsed);
      }
    } catch {
      // ignore
    }
  }, []);

  const navigate = useCallback(
    (nextKey: string, push = true) => {
      const target = navItems.find((n) => n.key === nextKey);
      if (!target) return;
      const oldIdx = navItems.findIndex((n) => n.key === activeKey);
      const newIdx = navItems.findIndex((n) => n.key === nextKey);
      setDirection(newIdx >= oldIdx ? 1 : -1);
      setActiveKey(nextKey);
      document.title = `${target.label} · Oopz`;
      if (push && window.location.pathname !== target.href) {
        window.history.pushState({ key: nextKey }, "", target.href);
      }
      window.scrollTo({ top: 0, behavior: "smooth" });
    },
    [activeKey, navItems]
  );

  useEffect(() => {
    const onPop = () => {
      const next = pageKeyFromPath(window.location.pathname, navItems);
      navigate(next, false);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, [navItems, navigate]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setCmdkOpen((o) => !o);
      } else if (authed && e.altKey && (e.key === "ArrowRight" || e.key === "ArrowLeft")) {
        e.preventDefault();
        const idx = navItems.findIndex((n) => n.key === activeKey);
        if (idx < 0) return;
        const nextIdx = (idx + (e.key === "ArrowRight" ? 1 : -1) + navItems.length) % navItems.length;
        navigate(navItems[nextIdx].key);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [authed, activeKey, navItems, navigate]);

  const checkAuth = useCallback(async () => {
    try {
      await apiReq("/admin/api/me");
      setAuthed(true);
      setStatus("在线", "success");
    } catch {
      setAuthed(false);
      setStatus("未登录", "warning");
    }
  }, [setStatus]);

  useEffect(() => { checkAuth(); }, [checkAuth]);

  const handleLogin = async () => {
    setLoginErr("");
    try {
      await apiReq("/admin/api/login", { method: "POST", body: JSON.stringify({ password: pwd }) });
      setPwd("");
      toast("验证通过", "success");
      await checkAuth();
    } catch (e: any) {
      setLoginErr(e.message || "密码错误");
      setShakeSeq((s) => s + 1);
    }
  };

  const handleLogout = async () => {
    try {
      await apiReq("/admin/api/logout", { method: "POST", body: "{}" });
    } catch {
      // ignore
    }
    setAuthed(false);
    setStatus("未登录", "warning");
    toast("已退出登录", "info");
  };

  const renderPage = () => {
    switch (activeKey) {
      case "dashboard": return <OverviewPage />;
      case "music": return <MusicPage />;
      case "config": return <ConfigPage />;
      case "stats": return <StatsPage />;
      case "members": return <MembersPage />;
      case "areas": return <AreasPage />;
      case "plugins": return <PluginsPage />;
      case "system": return <SystemPage />;
      case "keyword-reply": return <KeywordReplyPage />;
      case "scheduler": return <SchedulerPage />;
      case "screen-share": return <ScreenSharePage />;
      case "activity": return <ActivityPage />;
      default: return <OverviewPage />;
    }
  };

  return (
    <AppContext.Provider
      value={{ navItems, hasPlugin, navigate, setStatus, toast, confirm, refreshPluginNav }}
    >
      <div className="ed-backdrop" aria-hidden="true" />

      <div className="ed-frame">
        {authed !== false && (
          <header className="ed-masthead">
            <div className="ed-brand">
              <button type="button" className="ed-brand__logo" onClick={() => navigate("dashboard")}>
                <span className="ed-brand__word">Oopz</span>
              </button>
              <span className="ed-live-pill">
                <span className={`ed-live-dot ed-live-dot--${statusKind}`} />
                <span>{statusText}</span>
              </span>
            </div>

            <nav className="ed-nav" aria-label="后台导航">
              {navItems.map((item) => {
                const active = item.key === activeKey;
                return (
                  <button
                    key={item.key}
                    type="button"
                    className={`ed-nav__item${active ? " is-active" : ""}`}
                    onClick={() => navigate(item.key)}
                  >
                    {active && (
                      <motion.span
                        layoutId="nav-active-pill"
                        className="ed-nav__pill"
                        transition={{ type: "spring", stiffness: 460, damping: 34 }}
                      />
                    )}
                    <span>{item.label}</span>
                  </button>
                );
              })}
            </nav>

            <div className="ed-mast-tools">
              <button type="button" className="ed-mast-btn" onClick={() => setCmdkOpen(true)} title="快捷跳转 (Ctrl+K)">
                <Command size={13} />
                <span className="ed-kbd">K</span>
              </button>
              {authed && (
                <button type="button" className="ed-mast-btn ed-mast-btn--danger" onClick={handleLogout} title="退出登录">
                  <LogOut size={13} />
                  <span>退出</span>
                </button>
              )}
            </div>
          </header>
        )}

        <main className="ed-stage-outer">
          {authed === false ? (
            <div className="ed-auth-wrap">
              <motion.div
                key={shakeSeq}
                className="ed-auth-card"
                initial={shakeSeq === 0 ? { opacity: 0, y: 18, scale: 0.96 } : undefined}
                animate={
                  shakeSeq > 0
                    ? { x: [0, -8, 8, -5, 5, 0], opacity: 1, scale: 1 }
                    : { opacity: 1, y: 0, scale: 1 }
                }
                transition={{ duration: shakeSeq > 0 ? 0.34 : 0.36, ease: [0.22, 1, 0.36, 1] }}
              >
                <h1 className="ed-auth-card__title">Oopz</h1>
                <div style={{ display: "grid", gap: 14 }}>
                  <div className="ed-secret-row">
                    <input
                      className="ed-input"
                      type={showPwd ? "text" : "password"}
                      value={pwd}
                      autoFocus
                      placeholder="输入管理密码"
                      onChange={(e) => setPwd(e.target.value)}
                      onKeyDown={(e) => { if (e.key === "Enter") handleLogin(); }}
                    />
                    <EdButton size="sm" variant="ghost" onClick={() => setShowPwd((s) => !s)}>
                      {showPwd ? "隐藏" : "显示"}
                    </EdButton>
                  </div>
                  <EdButton variant="primary" style={{ width: "100%", height: 40 }} onClick={handleLogin}>
                    继续
                  </EdButton>
                  {loginErr && (
                    <div style={{ fontSize: 12.5, color: "#ff6961", textAlign: "center" }}>
                      {loginErr}
                    </div>
                  )}
                </div>
              </motion.div>
            </div>
          ) : authed === true ? (
            <AnimatePresence mode="wait" custom={direction}>
              <motion.div
                key={activeKey}
                custom={direction}
                variants={pageVariants}
                initial="enter"
                animate="center"
                exit="exit"
                transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
                style={{ flex: 1, display: "flex", flexDirection: "column" }}
              >
                {renderPage()}
              </motion.div>
            </AnimatePresence>
          ) : (
            <div className="ed-empty" style={{ margin: "auto" }}>加载中...</div>
          )}
        </main>
      </div>

      <CommandPalette
        open={cmdkOpen}
        navItems={navItems}
        onNavigate={(k) => navigate(k)}
        onLogout={handleLogout}
        onClose={() => setCmdkOpen(false)}
      />
      <ConfirmDialog state={confirmState} />
      <ToastStack items={toasts} onDismiss={(id) => setToasts((p) => p.filter((t) => t.id !== id))} />
    </AppContext.Provider>
  );
}
