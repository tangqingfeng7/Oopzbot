import React, { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { EdButton, EditorialSelect, ToggleSwitch } from "../components/EditorialPrimitives";
import { apiReq, getAdminBase } from "../lib/api";
import { useApp } from "../lib/context";

type TabKey = "basic" | "bot" | "music" | "schedule";

const TABS: { key: TabKey; num: string; label: string }[] = [
  { key: "basic", num: "01", label: "基础设置" },
  { key: "bot", num: "02", label: "机器人" },
  { key: "music", num: "03", label: "音乐与平台" },
  { key: "schedule", num: "04", label: "通知" },
];

const PROXY_ALIASES: Record<string, string> = {
  clash: "http://127.0.0.1:7890",
  "clash-http": "http://127.0.0.1:7890",
  "clash-mixed": "http://127.0.0.1:7890",
  "clash-socks": "socks5://127.0.0.1:7891",
  mihomo: "http://127.0.0.1:7890",
  "mihomo-socks": "socks5://127.0.0.1:7891",
};

function parseProxy(raw: unknown) {
  const out = { mode: "direct", scheme: "http", host: "127.0.0.1", port: "7890" };
  if (raw === false) return out;
  const val = raw == null ? "" : String(raw).trim();
  if (val === "") { out.mode = "system"; return out; }
  if (val.toLowerCase() === "direct") return out;
  let urlStr = PROXY_ALIASES[val.toLowerCase()] || val;
  if (!urlStr.includes("://")) urlStr = "http://" + urlStr;
  const m = urlStr.match(/^([a-zA-Z0-9]+):\/\/(?:[^@/]*@)?([^:/\s]+)(?::(\d+))?/);
  if (!m) return out;
  out.mode = "manual";
  out.scheme = m[1].toLowerCase().startsWith("socks") ? "socks5" : "http";
  out.host = m[2] || "127.0.0.1";
  out.port = m[3] || (out.scheme === "socks5" ? "7891" : "7890");
  return out;
}

function SecretInput({
  value,
  onChange,
  placeholder,
  maxLength,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  maxLength?: number;
}) {
  const [show, setShow] = useState(false);
  return (
    <div className="ed-secret-row">
      <input
        className="ed-input"
        type={show ? "text" : "password"}
        value={value}
        maxLength={maxLength}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
      />
      <EdButton size="sm" variant="ghost" onClick={() => setShow((s) => !s)}>
        {show ? "隐藏" : "显示"}
      </EdButton>
    </div>
  );
}

interface QrState {
  img: string;
  link: string;
  status: string;
  account: string;
  accountOk: boolean;
  canSave: boolean;
  busy: boolean;
}

export function ConfigPage() {
  const { setStatus, toast, confirm, hasPlugin } = useApp();
  const showScreenShare = hasPlugin("screen-share");

  const [tab, setTab] = useState<TabKey>("basic");
  const [schema, setSchema] = useState<Record<string, any>>({});
  const [vals, setVals] = useState<Record<string, any>>({});
  const [configured, setConfigured] = useState<Record<string, boolean>>({});
  const [proxy, setProxy] = useState({ mode: "direct", scheme: "http", host: "127.0.0.1", port: "7890" });
  const [areaHint, setAreaHint] = useState("");
  const [oopzPwd, setOopzPwd] = useState("");
  const [oopzStatus, setOopzStatus] = useState("");

  const [neteaseQr, setNeteaseQr] = useState<QrState>({
    img: "", link: "", status: "未开始", account: "未检测", accountOk: false, canSave: false, busy: false,
  });
  const [biliQr, setBiliQr] = useState<QrState>({
    img: "", link: "", status: "未开始", account: "未检测", accountOk: false, canSave: false, busy: false,
  });

  const neteaseTimer = useRef<number | null>(null);
  const biliTimer = useRef<number | null>(null);

  const stopQrTimers = useCallback(() => {
    if (neteaseTimer.current) { window.clearInterval(neteaseTimer.current); neteaseTimer.current = null; }
    if (biliTimer.current) { window.clearInterval(biliTimer.current); biliTimer.current = null; }
  }, []);

  useEffect(() => stopQrTimers, [stopQrTimers]);

  const setField = (path: string, value: any) => {
    setVals((prev) => ({ ...prev, [path]: value }));
  };

  const checkAccount = useCallback(async (platform: "netease" | "bilibili", isConfigured: boolean) => {
    const setter = platform === "netease" ? setNeteaseQr : setBiliQr;
    if (!isConfigured) {
      setter((s) => ({ ...s, account: "未登录", accountOk: false }));
      return;
    }
    setter((s) => ({ ...s, account: "检测中...", accountOk: false }));
    try {
      const data = await apiReq<any>(`/admin/api/${platform}/account`);
      if (data.logged_in && data.profile?.user_id) {
        setter((s) => ({
          ...s,
          account: `${data.profile.nickname || "未命名账号"} (ID: ${data.profile.user_id})`,
          accountOk: true,
        }));
      } else {
        setter((s) => ({ ...s, account: data.message || "未登录或已过期", accountOk: false }));
      }
    } catch (e: any) {
      setter((s) => ({ ...s, account: e.message || "检测失败", accountOk: false }));
    }
  }, []);

  const loadConfig = useCallback(async () => {
    try {
      const data = await apiReq<any>("/admin/api/config");
      const cfg = data.config || {};
      const sc = data.schema || {};
      setSchema(sc);

      const get = (path: string, nullish = false) => {
        const [g, k] = path.split(".");
        const raw = cfg[g]?.[k];
        const def = sc[g]?.[k]?.default ?? "";
        if (sc[g]?.[k]?.type === "bool") return !!raw;
        return nullish ? (raw ?? def) : (raw || def);
      };

      const next: Record<string, any> = {
        "web_player.url": get("web_player.url"),
        "web_player.host": get("web_player.host"),
        "web_player.port": get("web_player.port"),
        "web_player.token_ttl_seconds": get("web_player.token_ttl_seconds", true),
        "web_player.cookie_max_age_seconds": get("web_player.cookie_max_age_seconds", true),
        "web_player.link_idle_release_seconds": get("web_player.link_idle_release_seconds", true),
        "web_player.send_link_enabled": get("web_player.send_link_enabled"),
        "web_player.cookie_secure": get("web_player.cookie_secure"),
        "web_player.admin_path": get("web_player.admin_path"),
        "web_player.admin_session_ttl_seconds": get("web_player.admin_session_ttl_seconds", true),
        "web_player.admin_cookie_secure": get("web_player.admin_cookie_secure"),
        "web_player.admin_password": "",

        "redis.host": get("redis.host"),
        "redis.port": get("redis.port"),
        "redis.db": get("redis.db"),
        "redis.decode_responses": get("redis.decode_responses"),
        "redis.password": "",

        "auto_recall.enabled": get("auto_recall.enabled"),
        "auto_recall.delay": get("auto_recall.delay"),
        "area_join_notify.enabled": get("area_join_notify.enabled"),
        "area_join_notify.poll_interval_seconds": get("area_join_notify.poll_interval_seconds"),
        "area_join_notify.auto_assign_role_id": get("area_join_notify.auto_assign_role_id"),
        "area_join_notify.auto_assign_role_name": get("area_join_notify.auto_assign_role_name"),
        "area_join_notify.message_template": get("area_join_notify.message_template"),
        "area_join_notify.message_template_leave": get("area_join_notify.message_template_leave"),
        "message_stats.enabled": get("message_stats.enabled"),
        "command_cooldown.enabled": get("command_cooldown.enabled"),
        "command_cooldown.default_seconds": get("command_cooldown.default_seconds", true),
        "command_cooldown.exempt_admins": get("command_cooldown.exempt_admins"),

        "oopz.default_area": get("oopz.default_area"),
        "oopz.default_channel": get("oopz.default_channel"),
        "oopz.login_phone": get("oopz.login_phone"),
        "oopz.agora_app_id": get("oopz.agora_app_id"),
        "oopz.agora_init_timeout": get("oopz.agora_init_timeout"),

        "netease.base_url": get("netease.base_url"),
        "netease.audio_download_timeout": get("netease.audio_download_timeout"),
        "netease.audio_download_retries": get("netease.audio_download_retries"),
        "netease.audio_quality": get("netease.audio_quality"),
        "netease.cookie": cfg.netease?.cookie || "",

        "music.auto_play_enabled": get("music.auto_play_enabled"),
        "music.default_volume": get("music.default_volume", true),

        "qq_music.enabled": get("qq_music.enabled"),
        "qq_music.base_url": get("qq_music.base_url"),
        "qq_music.cookie": cfg.qq_music?.cookie || "",

        "bilibili_music.enabled": get("bilibili_music.enabled"),
        "bilibili_music.cookie": cfg.bilibili_music?.cookie || "",

        "screen_share.enabled": get("screen_share.enabled"),
        "screen_share.agora_app_id": get("screen_share.agora_app_id"),
        "screen_share.agora_app_certificate": "",
        "screen_share.presenter_link_ttl_seconds": get("screen_share.presenter_link_ttl_seconds"),
        "screen_share.session_max_seconds": get("screen_share.session_max_seconds"),
        "screen_share.rtc_token_ttl_seconds": get("screen_share.rtc_token_ttl_seconds"),
        "screen_share.default_quality": get("screen_share.default_quality") || "1080p",
      };

      setVals(next);
      setProxy(parseProxy(cfg.oopz?.proxy));
      setConfigured({
        admin_password: !!cfg.web_player?.admin_password_configured,
        oopz_password: !!cfg.oopz?.login_password_configured,
        redis_password: !!cfg.redis?.password_configured,
        screen_share_cert: !!cfg.screen_share?.agora_app_certificate_configured,
        netease_cookie: !!cfg.netease?.cookie_configured,
        qq_cookie: !!cfg.qq_music?.cookie_configured,
        bili_cookie: !!cfg.bilibili_music?.cookie_configured,
      });

      const ma = data.runtime?.music_area || {};
      setAreaHint(`音乐域：${ma.area || "-"} · 来源：${ma.source_text || "未解析"} · 活跃域：${ma.active_area || "-"} · 默认域：${ma.default_area || "-"}`);
      setStatus("配置已同步", "success");

      checkAccount("netease", !!cfg.netease?.cookie_configured);
      checkAccount("bilibili", !!cfg.bilibili_music?.cookie_configured);
    } catch (e: any) {
      setStatus("加载失败", "error");
      toast(e.message, "error");
    }
  }, [checkAccount, setStatus, toast]);

  useEffect(() => {
    loadConfig();
  }, [loadConfig]);

  const buildUpdates = () => {
    const num = (k: string, def = 0) => {
      const n = Number(vals[k]);
      return Number.isFinite(n) ? Math.trunc(n) : def;
    };
    const str = (k: string) => String(vals[k] ?? "").trim();

    let proxyValue = "direct";
    if (proxy.mode === "system") proxyValue = "";
    else if (proxy.mode === "manual") {
      const p = Number(proxy.port) || (proxy.scheme === "socks5" ? 7891 : 7890);
      proxyValue = `${proxy.scheme}://${proxy.host.trim() || "127.0.0.1"}:${p}`;
    }

    const updates: Record<string, Record<string, any>> = {
      web_player: {
        url: str("web_player.url"),
        host: str("web_player.host") || schema.web_player?.host?.default || "0.0.0.0",
        port: num("web_player.port") || Number(schema.web_player?.port?.default || 8080),
        token_ttl_seconds: num("web_player.token_ttl_seconds"),
        cookie_max_age_seconds: num("web_player.cookie_max_age_seconds"),
        link_idle_release_seconds: num("web_player.link_idle_release_seconds"),
        send_link_enabled: !!vals["web_player.send_link_enabled"],
        cookie_secure: !!vals["web_player.cookie_secure"],
        admin_path: str("web_player.admin_path") || "/admin",
        admin_session_ttl_seconds: num("web_player.admin_session_ttl_seconds"),
        admin_cookie_secure: !!vals["web_player.admin_cookie_secure"],
      },
      redis: {
        host: str("redis.host"),
        port: num("redis.port", 6379),
        db: num("redis.db", 0),
        decode_responses: !!vals["redis.decode_responses"],
      },
      auto_recall: {
        enabled: !!vals["auto_recall.enabled"],
        delay: num("auto_recall.delay", 30),
      },
      area_join_notify: {
        enabled: !!vals["area_join_notify.enabled"],
        poll_interval_seconds: num("area_join_notify.poll_interval_seconds", 2),
        auto_assign_role_id: str("area_join_notify.auto_assign_role_id"),
        auto_assign_role_name: str("area_join_notify.auto_assign_role_name"),
        message_template: str("area_join_notify.message_template"),
        message_template_leave: str("area_join_notify.message_template_leave"),
      },
      message_stats: { enabled: !!vals["message_stats.enabled"] },
      command_cooldown: {
        enabled: !!vals["command_cooldown.enabled"],
        default_seconds: num("command_cooldown.default_seconds"),
        exempt_admins: !!vals["command_cooldown.exempt_admins"],
      },
      oopz: {
        default_area: str("oopz.default_area"),
        default_channel: str("oopz.default_channel"),
        login_phone: str("oopz.login_phone"),
        login_password: oopzPwd,
        agora_app_id: str("oopz.agora_app_id"),
        agora_init_timeout: num("oopz.agora_init_timeout") || Number(schema.oopz?.agora_init_timeout?.default || 60),
        proxy: proxyValue,
      },
      netease: {
        base_url: str("netease.base_url"),
        audio_download_timeout: num("netease.audio_download_timeout", 30),
        audio_download_retries: num("netease.audio_download_retries", 2),
        audio_quality: str("netease.audio_quality") || schema.netease?.audio_quality?.default || "standard",
      },
      music: {
        auto_play_enabled: !!vals["music.auto_play_enabled"],
        default_volume: num("music.default_volume", 100),
      },
      qq_music: {
        enabled: !!vals["qq_music.enabled"],
        base_url: str("qq_music.base_url"),
      },
      bilibili_music: {
        enabled: !!vals["bilibili_music.enabled"],
      },
    };

    if (str("web_player.admin_password")) updates.web_player.admin_password = str("web_player.admin_password");
    if (str("redis.password")) updates.redis.password = str("redis.password");
    if (str("netease.cookie")) updates.netease.cookie = str("netease.cookie");
    if (str("qq_music.cookie")) updates.qq_music.cookie = str("qq_music.cookie");
    if (str("bilibili_music.cookie")) updates.bilibili_music.cookie = str("bilibili_music.cookie");

    if (showScreenShare) {
      updates.screen_share = {
        enabled: !!vals["screen_share.enabled"],
        agora_app_id: str("screen_share.agora_app_id"),
        presenter_link_ttl_seconds: num("screen_share.presenter_link_ttl_seconds", 600),
        session_max_seconds: num("screen_share.session_max_seconds", 14400),
        rtc_token_ttl_seconds: num("screen_share.rtc_token_ttl_seconds", 3600),
        default_quality: str("screen_share.default_quality") || "1080p",
      };
      if (str("screen_share.agora_app_certificate")) {
        updates.screen_share.agora_app_certificate = str("screen_share.agora_app_certificate");
      }
    }
    return updates;
  };

  const saveConfig = async () => {
    try {
      const data = await apiReq<any>("/admin/api/config", {
        method: "POST",
        body: JSON.stringify({ updates: buildUpdates(), persist: true }),
      });
      if (Array.isArray(data.errors) && data.errors.length > 0) {
        toast(`部分失败：${data.errors.join(" | ")}`, "error");
      } else {
        toast(data.message || "配置已保存并生效", "success");
      }
      const savedAdminPath = String(data.config?.web_player?.admin_path || "").trim();
      const currentBase = getAdminBase();
      if (savedAdminPath && savedAdminPath !== currentBase) {
        toast(`后台路径已切换为 ${savedAdminPath}，正在跳转...`, "success");
        window.setTimeout(() => {
          window.location.assign(`${savedAdminPath}/config`);
        }, 450);
        return;
      }
      await loadConfig();
    } catch (e: any) {
      toast(e.message || "保存失败", "error");
    }
  };

  const resetConfig = async () => {
    const ok = await confirm("恢复运行配置", "确认丢弃当前修改并从 config.py 重新加载？", { okText: "确认恢复" });
    if (!ok) return;
    try {
      const data = await apiReq<any>("/admin/api/config/reset", { method: "POST", body: "{}" });
      toast(data.message || "已恢复 config.py", "success");
      const savedAdminPath = String(data.config?.web_player?.admin_path || "").trim();
      const currentBase = getAdminBase();
      if (savedAdminPath && savedAdminPath !== currentBase) {
        toast(`后台路径已切换为 ${savedAdminPath}，正在跳转...`, "success");
        window.setTimeout(() => {
          window.location.assign(`${savedAdminPath}/config`);
        }, 450);
        return;
      }
      await loadConfig();
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  const loginOopz = async () => {
    setOopzStatus("登录中...");
    try {
      const data = await apiReq<any>("/admin/api/oopz/login", {
        method: "POST",
        body: JSON.stringify({ phone: String(vals["oopz.login_phone"] || "").trim(), password: oopzPwd }),
      });
      setOopzPwd("");
      const c = data.credentials || {};
      setOopzStatus(`UID ${c.person_uid || "-"} · 设备 ${c.device_id || "-"}`);
      toast("OOPZ 凭据已更新", "success");
      await loadConfig();
    } catch (e: any) {
      setOopzStatus(e.message || "登录失败");
      toast(e.message || "OOPZ 登录失败", "error");
    }
  };

  const startQr = async (platform: "netease" | "bilibili") => {
    const isNetease = platform === "netease";
    const setter = isNetease ? setNeteaseQr : setBiliQr;
    const timerRef = isNetease ? neteaseTimer : biliTimer;
    if (timerRef.current) { window.clearInterval(timerRef.current); timerRef.current = null; }
    setter((s) => ({ ...s, busy: true, img: "", link: "", status: "获取二维码...", canSave: false }));
    try {
      const body = isNetease ? JSON.stringify({ base_url: String(vals["netease.base_url"] || "").trim() }) : "{}";
      const data = await apiReq<any>(`/admin/api/${platform}/login/qr`, { method: "POST", body });
      const key = data.key || "";
      const baseUrl = data.base_url || String(vals["netease.base_url"] || "").trim();
      setter((s) => ({
        ...s,
        busy: false,
        img: data.qrimg || "",
        link: data.qrurl || "",
        status: data.message || "等待扫码",
      }));
      const poll = async () => {
        try {
          const chkBody = isNetease ? JSON.stringify({ base_url: baseUrl, key }) : JSON.stringify({ key });
          const res = await apiReq<any>(`/admin/api/${platform}/login/qr/check`, { method: "POST", body: chkBody });
          if (res.status === "waiting" || res.status === "scanned") {
            setter((s) => ({ ...s, status: res.message || (res.status === "scanned" ? "已扫码，请确认" : "等待扫码") }));
          } else if (res.status === "expired") {
            if (timerRef.current) { window.clearInterval(timerRef.current); timerRef.current = null; }
            setter((s) => ({ ...s, img: "", status: "二维码已过期" }));
          } else if (res.status === "success") {
            if (timerRef.current) { window.clearInterval(timerRef.current); timerRef.current = null; }
            setField(isNetease ? "netease.cookie" : "bilibili_music.cookie", res.cookie || "");
            const prof = res.profile;
            setter((s) => ({
              ...s,
              status: "登录成功，Cookie 已填入",
              canSave: true,
              account: prof?.user_id ? `${prof.nickname || "账号"} (ID: ${prof.user_id})` : s.account,
              accountOk: true,
            }));
            toast(`${isNetease ? "网易云" : "B 站"}扫码成功，点击保存生效`, "success");
          }
        } catch (err: any) {
          if (timerRef.current) { window.clearInterval(timerRef.current); timerRef.current = null; }
          setter((s) => ({ ...s, status: err.message || "检查失败" }));
        }
      };
      timerRef.current = window.setInterval(poll, 2500);
      window.setTimeout(poll, 900);
    } catch (e: any) {
      setter((s) => ({ ...s, busy: false, status: e.message || "获取失败" }));
      toast(e.message, "error");
    }
  };

  return (
    <div className="ed-chapter">
      <div className="ed-chapter-bar">
        <div className="ed-chapter-bar__left">
          <h2 className="ed-chapter-bar__title">配置</h2>
        </div>
        <div className="ed-chapter-bar__actions">
          <EdButton size="sm" variant="ghost" onClick={loadConfig}>刷新</EdButton>
          <EdButton size="sm" variant="ghost" onClick={resetConfig}>恢复配置</EdButton>
          <EdButton size="sm" variant="primary" onClick={saveConfig}>保存并生效</EdButton>
        </div>
      </div>

      <div className="ed-grid ed-grid--split-aside">
        <aside className="ed-chapter-rail">
          {TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              className={`ed-chapter-tab${tab === t.key ? " is-active" : ""}`}
              onClick={() => setTab(t.key)}
            >
              {tab === t.key && (
                <motion.span
                  layoutId="cfg-rail-bar"
                  className="ed-chapter-tab__bar"
                  transition={{ type: "spring", stiffness: 460, damping: 34 }}
                />
              )}
              <span>{t.label}</span>
            </button>
          ))}
        </aside>

        <div style={{ minWidth: 0 }}>
          <AnimatePresence mode="wait">
            <motion.div
              key={tab}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
              style={{ display: "grid", gap: 16 }}
            >
              {tab === "basic" && (
                <>
                  <section className="ed-cell">
                    <div className="ed-label" style={{ marginBottom: 18 }}>
                      <span>访问与安全</span>
                    </div>
                    <div className="ed-form-grid">
                      <div className="ed-field ed-field--wide">
                        <label className="ed-field__label">播放器 URL</label>
                        <input className="ed-input" value={vals["web_player.url"] ?? ""} placeholder="http://127.0.0.1:8080" onChange={(e) => setField("web_player.url", e.target.value)} />
                      </div>
                      <div className="ed-field">
                        <label className="ed-field__label">监听地址</label>
                        <input className="ed-input" value={vals["web_player.host"] ?? ""} onChange={(e) => setField("web_player.host", e.target.value)} />
                      </div>
                      <div className="ed-field">
                        <label className="ed-field__label">监听端口</label>
                        <input className="ed-input" type="number" value={vals["web_player.port"] ?? ""} onChange={(e) => setField("web_player.port", e.target.value)} />
                      </div>
                      <div className="ed-field">
                        <label className="ed-field__label">播放器 Token TTL（秒）</label>
                        <input className="ed-input" type="number" value={vals["web_player.token_ttl_seconds"] ?? ""} onChange={(e) => setField("web_player.token_ttl_seconds", e.target.value)} />
                      </div>
                      <div className="ed-field">
                        <label className="ed-field__label">播放器 Cookie MaxAge（秒）</label>
                        <input className="ed-input" type="number" value={vals["web_player.cookie_max_age_seconds"] ?? ""} onChange={(e) => setField("web_player.cookie_max_age_seconds", e.target.value)} />
                      </div>
                      <div className="ed-field">
                        <label className="ed-field__label">后台路径前缀</label>
                        <input
                          className="ed-input"
                          value={vals["web_player.admin_path"] ?? ""}
                          placeholder="/admin（改为随机路径如 /ops-9f3k 可隐藏默认入口）"
                          onChange={(e) => setField("web_player.admin_path", e.target.value)}
                        />
                      </div>
                      <div className="ed-field">
                        <label className="ed-field__label">后台会话 TTL（秒）</label>
                        <input className="ed-input" type="number" value={vals["web_player.admin_session_ttl_seconds"] ?? ""} onChange={(e) => setField("web_player.admin_session_ttl_seconds", e.target.value)} />
                      </div>
                      <div className="ed-field">
                        <label className="ed-field__label">空闲释放链接（秒）</label>
                        <input className="ed-input" type="number" value={vals["web_player.link_idle_release_seconds"] ?? ""} onChange={(e) => setField("web_player.link_idle_release_seconds", e.target.value)} />
                      </div>
                      <div className="ed-field ed-field--wide">
                        <label className="ed-field__label">后台新密码</label>
                        <SecretInput
                          value={vals["web_player.admin_password"] ?? ""}
                          placeholder={configured.admin_password ? "已配置，留空表示不修改" : "未配置"}
                          onChange={(v) => setField("web_player.admin_password", v)}
                        />
                      </div>
                    </div>
                    <div style={{ marginTop: 14 }}>
                      <div className="ed-switch-row">
                        <span className="ed-field__label">点歌时发送 Web 播放器链接</span>
                        <ToggleSwitch checked={!!vals["web_player.send_link_enabled"]} onChange={(v) => setField("web_player.send_link_enabled", v)} />
                      </div>
                      <div className="ed-switch-row">
                        <span className="ed-field__label">播放器 Cookie Secure</span>
                        <ToggleSwitch checked={!!vals["web_player.cookie_secure"]} onChange={(v) => setField("web_player.cookie_secure", v)} />
                      </div>
                      <div className="ed-switch-row" style={{ borderBottom: "none" }}>
                        <span className="ed-field__label">后台 Cookie Secure</span>
                        <ToggleSwitch checked={!!vals["web_player.admin_cookie_secure"]} onChange={(v) => setField("web_player.admin_cookie_secure", v)} />
                      </div>
                    </div>
                  </section>

                  <section className="ed-cell">
                    <div className="ed-label" style={{ marginBottom: 18 }}>
                      <span>Redis</span>
                    </div>
                    <div className="ed-form-grid">
                      <div className="ed-field">
                        <label className="ed-field__label">Redis Host</label>
                        <input className="ed-input" value={vals["redis.host"] ?? ""} onChange={(e) => setField("redis.host", e.target.value)} />
                      </div>
                      <div className="ed-field">
                        <label className="ed-field__label">Redis Port</label>
                        <input className="ed-input" type="number" value={vals["redis.port"] ?? ""} onChange={(e) => setField("redis.port", e.target.value)} />
                      </div>
                      <div className="ed-field">
                        <label className="ed-field__label">Redis DB</label>
                        <input className="ed-input" type="number" value={vals["redis.db"] ?? ""} onChange={(e) => setField("redis.db", e.target.value)} />
                      </div>
                      <div className="ed-field" style={{ alignSelf: "end" }}>
                        <div className="ed-switch-row" style={{ borderBottom: "none", padding: "7px 0" }}>
                          <span className="ed-field__label">decode_responses</span>
                          <ToggleSwitch checked={!!vals["redis.decode_responses"]} onChange={(v) => setField("redis.decode_responses", v)} />
                        </div>
                      </div>
                      <div className="ed-field ed-field--wide">
                        <label className="ed-field__label">Redis 密码</label>
                        <SecretInput
                          value={vals["redis.password"] ?? ""}
                          placeholder={configured.redis_password ? "已配置，留空表示不修改" : "未配置"}
                          onChange={(v) => setField("redis.password", v)}
                        />
                      </div>
                    </div>
                  </section>
                </>
              )}

              {tab === "bot" && (
                <>
                  <section className="ed-cell">
                    <div className="ed-label" style={{ marginBottom: 18 }}>
                      <span>机器人行为</span>
                    </div>
                    <div className="ed-form-grid">
                      <div className="ed-field" style={{ alignSelf: "end" }}>
                        <div className="ed-switch-row" style={{ borderBottom: "none", padding: "7px 0" }}>
                          <span className="ed-field__label">启用自动撤回</span>
                          <ToggleSwitch checked={!!vals["auto_recall.enabled"]} onChange={(v) => setField("auto_recall.enabled", v)} />
                        </div>
                      </div>
                      <div className="ed-field">
                        <label className="ed-field__label">自动撤回延迟（秒）</label>
                        <input className="ed-input" type="number" value={vals["auto_recall.delay"] ?? ""} onChange={(e) => setField("auto_recall.delay", e.target.value)} />
                      </div>
                      <div className="ed-field" style={{ alignSelf: "end" }}>
                        <div className="ed-switch-row" style={{ borderBottom: "none", padding: "7px 0" }}>
                          <span className="ed-field__label">启用区域加入通知</span>
                          <ToggleSwitch checked={!!vals["area_join_notify.enabled"]} onChange={(v) => setField("area_join_notify.enabled", v)} />
                        </div>
                      </div>
                      <div className="ed-field">
                        <label className="ed-field__label">成员轮询间隔（秒）</label>
                        <input className="ed-input" type="number" value={vals["area_join_notify.poll_interval_seconds"] ?? ""} onChange={(e) => setField("area_join_notify.poll_interval_seconds", e.target.value)} />
                      </div>
                      <div className="ed-field">
                        <label className="ed-field__label">新人自动分配身份组 ID</label>
                        <input className="ed-input" value={vals["area_join_notify.auto_assign_role_id"] ?? ""} placeholder="留空不分配" onChange={(e) => setField("area_join_notify.auto_assign_role_id", e.target.value)} />
                      </div>
                      <div className="ed-field">
                        <label className="ed-field__label">按名称匹配身份组</label>
                        <input className="ed-input" value={vals["area_join_notify.auto_assign_role_name"] ?? ""} placeholder="优先使用 ID" onChange={(e) => setField("area_join_notify.auto_assign_role_name", e.target.value)} />
                      </div>
                    </div>
                  </section>

                  <section className="ed-cell">
                    <div className="ed-label" style={{ marginBottom: 14 }}>
                      <span>统计与冷却</span>
                    </div>
                    <div className="ed-switch-row">
                      <span className="ed-field__label">启用消息统计</span>
                      <ToggleSwitch checked={!!vals["message_stats.enabled"]} onChange={(v) => setField("message_stats.enabled", v)} />
                    </div>
                    <div className="ed-switch-row">
                      <span className="ed-field__label">启用命令冷却</span>
                      <ToggleSwitch checked={!!vals["command_cooldown.enabled"]} onChange={(v) => setField("command_cooldown.enabled", v)} />
                    </div>
                    <div className="ed-switch-row">
                      <span className="ed-field__label">管理员免冷却</span>
                      <ToggleSwitch checked={!!vals["command_cooldown.exempt_admins"]} onChange={(v) => setField("command_cooldown.exempt_admins", v)} />
                    </div>
                    <div className="ed-field" style={{ marginTop: 14, maxWidth: 280 }}>
                      <label className="ed-field__label">默认冷却时间（秒）</label>
                      <input className="ed-input" type="number" min={0} max={300} value={vals["command_cooldown.default_seconds"] ?? ""} onChange={(e) => setField("command_cooldown.default_seconds", e.target.value)} />
                    </div>
                  </section>
                </>
              )}

              {tab === "music" && (
                <>
                  <section className="ed-cell">
                    <div className="ed-label" style={{ marginBottom: 18 }}>
                      <span>OOPZ 与代理</span>
                    </div>
                    <div className="ed-form-grid">
                      <div className="ed-field ed-field--wide">
                        <label className="ed-field__label">OOPZ 账号密码登录</label>
                        <div className="ed-secret-row" style={{ flexWrap: "wrap" }}>
                          <input className="ed-input" style={{ flex: "1 1 180px" }} value={vals["oopz.login_phone"] ?? ""} placeholder="手机号；留空用配置" onChange={(e) => setField("oopz.login_phone", e.target.value)} />
                          <input className="ed-input" style={{ flex: "1 1 180px" }} type="password" value={oopzPwd} placeholder={configured.oopz_password ? "已配置，留空用配置" : "密码"} onChange={(e) => setOopzPwd(e.target.value)} />
                          <EdButton size="sm" variant="primary" onClick={loginOopz}>登录并获取</EdButton>
                        </div>
                        {oopzStatus && <div className="ed-mono-sub" style={{ marginTop: 4 }}>{oopzStatus}</div>}
                      </div>
                      <div className="ed-field">
                        <label className="ed-field__label">默认区域 ID</label>
                        <input className="ed-input" value={vals["oopz.default_area"] ?? ""} onChange={(e) => setField("oopz.default_area", e.target.value)} />
                      </div>
                      <div className="ed-field">
                        <label className="ed-field__label">默认频道 ID</label>
                        <input className="ed-input" value={vals["oopz.default_channel"] ?? ""} onChange={(e) => setField("oopz.default_channel", e.target.value)} />
                      </div>
                      {areaHint && (
                        <div className="ed-field ed-field--wide" style={{ fontFamily: "var(--font-mono)", fontSize: 11.5, color: "var(--ink-faint)" }}>
                          {areaHint}
                        </div>
                      )}
                      <div className="ed-field">
                        <label className="ed-field__label">代理模式</label>
                        <EditorialSelect
                          value={proxy.mode}
                          onChange={(m) => setProxy((p) => ({ ...p, mode: m }))}
                          options={[
                            { value: "direct", label: "关闭（直连）" },
                            { value: "system", label: "系统代理" },
                            { value: "manual", label: "手动指定" },
                          ]}
                        />
                      </div>
                      {proxy.mode === "manual" && (
                        <>
                          <div className="ed-field">
                            <label className="ed-field__label">代理协议</label>
                            <EditorialSelect
                              value={proxy.scheme}
                              onChange={(s) => setProxy((p) => ({ ...p, scheme: s }))}
                              options={[
                                { value: "http", label: "HTTP" },
                                { value: "socks5", label: "SOCKS5" },
                              ]}
                            />
                          </div>
                          <div className="ed-field">
                            <label className="ed-field__label">代理地址</label>
                            <input className="ed-input" value={proxy.host} onChange={(e) => setProxy((p) => ({ ...p, host: e.target.value }))} />
                          </div>
                          <div className="ed-field">
                            <label className="ed-field__label">代理端口</label>
                            <input className="ed-input" type="number" value={proxy.port} onChange={(e) => setProxy((p) => ({ ...p, port: e.target.value }))} />
                          </div>
                        </>
                      )}
                    </div>
                  </section>

                  <section className="ed-cell">
                    <div className="ed-label" style={{ marginBottom: 18 }}>
                      <span>网易云音乐</span>
                    </div>
                    <div className="ed-form-grid">
                      <div className="ed-field ed-field--wide">
                        <label className="ed-field__label">API 地址</label>
                        <input className="ed-input" value={vals["netease.base_url"] ?? ""} onChange={(e) => setField("netease.base_url", e.target.value)} />
                      </div>
                      <div className="ed-field ed-field--wide">
                        <div style={{ display: "flex", gap: 18, alignItems: "center", flexWrap: "wrap", padding: 14, borderRadius: 14, border: "1px solid var(--rule)", background: "rgba(0,0,0,0.2)" }}>
                          <div style={{ width: 148, height: 148, borderRadius: 12, border: "1px solid var(--rule)", display: "grid", placeItems: "center", background: "rgba(0,0,0,0.35)", flexShrink: 0, overflow: "hidden" }}>
                            {neteaseQr.img ? <img src={neteaseQr.img} alt="QR" style={{ width: 136, height: 136, borderRadius: 8, background: "#fff", padding: 4 }} /> : <span className="ed-mono-sub" style={{ margin: 0 }}>QR</span>}
                          </div>
                          <div style={{ display: "grid", gap: 8 }}>
                            <div style={{ display: "flex", gap: 8 }}>
                              <EdButton size="sm" variant="primary" disabled={neteaseQr.busy} onClick={() => startQr("netease")}>刷新二维码</EdButton>
                              <EdButton size="sm" variant="ghost" disabled={!neteaseQr.canSave} onClick={saveConfig}>保存生效</EdButton>
                            </div>
                            <div style={{ fontSize: 12, color: "var(--ink-faint)" }}>{neteaseQr.status}</div>
                            <div style={{ fontSize: 12, color: neteaseQr.accountOk ? "var(--ok)" : "var(--ink-soft)" }}>
                              账号：{neteaseQr.account}
                            </div>
                            {neteaseQr.link && <a href={neteaseQr.link} target="_blank" rel="noreferrer" style={{ color: "var(--gold)", fontSize: 12 }}>打开二维码链接</a>}
                          </div>
                        </div>
                      </div>
                      <div className="ed-field">
                        <label className="ed-field__label">音频超时（秒）</label>
                        <input className="ed-input" type="number" value={vals["netease.audio_download_timeout"] ?? ""} onChange={(e) => setField("netease.audio_download_timeout", e.target.value)} />
                      </div>
                      <div className="ed-field">
                        <label className="ed-field__label">重试次数</label>
                        <input className="ed-input" type="number" value={vals["netease.audio_download_retries"] ?? ""} onChange={(e) => setField("netease.audio_download_retries", e.target.value)} />
                      </div>
                      <div className="ed-field">
                        <label className="ed-field__label">音质</label>
                        <input className="ed-input" value={vals["netease.audio_quality"] ?? ""} placeholder="standard / exhigh" onChange={(e) => setField("netease.audio_quality", e.target.value)} />
                      </div>
                      <div className="ed-field ed-field--wide">
                        <label className="ed-field__label">网易云 Cookie</label>
                        <SecretInput value={vals["netease.cookie"] ?? ""} placeholder={configured.netease_cookie ? "已配置，留空表示不修改" : "未配置"} onChange={(v) => setField("netease.cookie", v)} />
                      </div>
                    </div>
                  </section>

                  <section className="ed-cell">
                    <div className="ed-label" style={{ marginBottom: 18 }}>
                      <span>播放与语音推流</span>
                    </div>
                    <div className="ed-form-grid">
                      <div className="ed-field" style={{ alignSelf: "end" }}>
                        <div className="ed-switch-row" style={{ borderBottom: "none", padding: "7px 0" }}>
                          <span className="ed-field__label">队列播完自动随机</span>
                          <ToggleSwitch checked={!!vals["music.auto_play_enabled"]} onChange={(v) => setField("music.auto_play_enabled", v)} />
                        </div>
                      </div>
                      <div className="ed-field">
                        <label className="ed-field__label">默认音量 (0-100)</label>
                        <input className="ed-input" type="number" min={0} max={100} value={vals["music.default_volume"] ?? ""} onChange={(e) => setField("music.default_volume", e.target.value)} />
                      </div>
                      <div className="ed-field">
                        <label className="ed-field__label">Agora App ID</label>
                        <input className="ed-input" value={vals["oopz.agora_app_id"] ?? ""} onChange={(e) => setField("oopz.agora_app_id", e.target.value)} />
                      </div>
                      <div className="ed-field">
                        <label className="ed-field__label">浏览器启动超时（秒）</label>
                        <input className="ed-input" type="number" value={vals["oopz.agora_init_timeout"] ?? ""} onChange={(e) => setField("oopz.agora_init_timeout", e.target.value)} />
                      </div>
                    </div>
                  </section>

                  {showScreenShare && (
                    <section className="ed-cell">
                      <div className="ed-label" style={{ marginBottom: 18 }}>
                        <span>网页屏幕共享</span>
                      </div>
                      <div className="ed-form-grid">
                        <div className="ed-field ed-field--wide">
                          <div className="ed-switch-row" style={{ borderBottom: "none", padding: "4px 0" }}>
                            <span className="ed-field__label">启用网页屏幕共享</span>
                            <ToggleSwitch checked={!!vals["screen_share.enabled"]} onChange={(v) => setField("screen_share.enabled", v)} />
                          </div>
                        </div>
                        <div className="ed-field ed-field--wide">
                          <label className="ed-field__label">声网 App ID</label>
                          <input className="ed-input" maxLength={32} value={vals["screen_share.agora_app_id"] ?? ""} onChange={(e) => setField("screen_share.agora_app_id", e.target.value)} />
                        </div>
                        <div className="ed-field ed-field--wide">
                          <label className="ed-field__label">声网 App Certificate</label>
                          <SecretInput maxLength={32} value={vals["screen_share.agora_app_certificate"] ?? ""} placeholder={configured.screen_share_cert ? "已配置，留空表示不修改" : "未配置"} onChange={(v) => setField("screen_share.agora_app_certificate", v)} />
                        </div>
                        <div className="ed-field">
                          <label className="ed-field__label">发起链接有效期（秒）</label>
                          <input className="ed-input" type="number" value={vals["screen_share.presenter_link_ttl_seconds"] ?? ""} onChange={(e) => setField("screen_share.presenter_link_ttl_seconds", e.target.value)} />
                        </div>
                        <div className="ed-field">
                          <label className="ed-field__label">最长共享时长（秒）</label>
                          <input className="ed-input" type="number" value={vals["screen_share.session_max_seconds"] ?? ""} onChange={(e) => setField("screen_share.session_max_seconds", e.target.value)} />
                        </div>
                        <div className="ed-field">
                          <label className="ed-field__label">RTC Token 有效期（秒）</label>
                          <input className="ed-input" type="number" value={vals["screen_share.rtc_token_ttl_seconds"] ?? ""} onChange={(e) => setField("screen_share.rtc_token_ttl_seconds", e.target.value)} />
                        </div>
                        <div className="ed-field">
                          <label className="ed-field__label">默认画质</label>
                          <EditorialSelect
                            value={vals["screen_share.default_quality"] || "1080p"}
                            onChange={(v) => setField("screen_share.default_quality", v)}
                            options={[
                              { value: "2k", label: "2K" },
                              { value: "1080p", label: "1080p" },
                              { value: "720p", label: "720p" },
                            ]}
                          />
                        </div>
                      </div>
                    </section>
                  )}

                  <section className="ed-cell">
                    <div className="ed-label" style={{ marginBottom: 18 }}>
                      <span>QQ 音乐</span>
                    </div>
                    <div className="ed-form-grid">
                      <div className="ed-field ed-field--wide">
                        <div className="ed-switch-row" style={{ borderBottom: "none", padding: "4px 0" }}>
                          <span className="ed-field__label">启用 QQ 音乐</span>
                          <ToggleSwitch checked={!!vals["qq_music.enabled"]} onChange={(v) => setField("qq_music.enabled", v)} />
                        </div>
                      </div>
                      <div className="ed-field ed-field--wide">
                        <label className="ed-field__label">API 地址</label>
                        <input className="ed-input" value={vals["qq_music.base_url"] ?? ""} onChange={(e) => setField("qq_music.base_url", e.target.value)} />
                      </div>
                      <div className="ed-field ed-field--wide">
                        <label className="ed-field__label">Cookie</label>
                        <SecretInput value={vals["qq_music.cookie"] ?? ""} placeholder={configured.qq_cookie ? "已配置，留空表示不修改" : "未配置"} onChange={(v) => setField("qq_music.cookie", v)} />
                      </div>
                    </div>
                  </section>

                  <section className="ed-cell">
                    <div className="ed-label" style={{ marginBottom: 18 }}>
                      <span>B 站音乐</span>
                    </div>
                    <div className="ed-form-grid">
                      <div className="ed-field ed-field--wide">
                        <div className="ed-switch-row" style={{ borderBottom: "none", padding: "4px 0" }}>
                          <span className="ed-field__label">启用 B 站音乐</span>
                          <ToggleSwitch checked={!!vals["bilibili_music.enabled"]} onChange={(v) => setField("bilibili_music.enabled", v)} />
                        </div>
                      </div>
                      <div className="ed-field ed-field--wide">
                        <div style={{ display: "flex", gap: 18, alignItems: "center", flexWrap: "wrap", padding: 14, borderRadius: 14, border: "1px solid var(--rule)", background: "rgba(0,0,0,0.2)" }}>
                          <div style={{ width: 148, height: 148, borderRadius: 12, border: "1px solid var(--rule)", display: "grid", placeItems: "center", background: "rgba(0,0,0,0.35)", flexShrink: 0, overflow: "hidden" }}>
                            {biliQr.img ? <img src={biliQr.img} alt="QR" style={{ width: 136, height: 136, borderRadius: 8, background: "#fff", padding: 4 }} /> : <span className="ed-mono-sub" style={{ margin: 0 }}>QR</span>}
                          </div>
                          <div style={{ display: "grid", gap: 8 }}>
                            <div style={{ display: "flex", gap: 8 }}>
                              <EdButton size="sm" variant="primary" disabled={biliQr.busy} onClick={() => startQr("bilibili")}>刷新二维码</EdButton>
                              <EdButton size="sm" variant="ghost" disabled={!biliQr.canSave} onClick={saveConfig}>保存生效</EdButton>
                            </div>
                            <div style={{ fontSize: 12, color: "var(--ink-faint)" }}>{biliQr.status}</div>
                            <div style={{ fontSize: 12, color: biliQr.accountOk ? "var(--ok)" : "var(--ink-soft)" }}>
                              账号：{biliQr.account}
                            </div>
                            {biliQr.link && <a href={biliQr.link} target="_blank" rel="noreferrer" style={{ color: "var(--gold)", fontSize: 12 }}>打开二维码链接</a>}
                          </div>
                        </div>
                      </div>
                      <div className="ed-field ed-field--wide">
                        <label className="ed-field__label">Cookie</label>
                        <SecretInput value={vals["bilibili_music.cookie"] ?? ""} placeholder={configured.bili_cookie ? "已配置，留空表示不修改" : "未配置"} onChange={(v) => setField("bilibili_music.cookie", v)} />
                      </div>
                    </div>
                  </section>
                </>
              )}

              {tab === "schedule" && (
                <section className="ed-cell">
                  <div className="ed-label" style={{ marginBottom: 18 }}>
                    <span>进退域通知模板</span>
                  </div>
                  <div className="ed-form-grid">
                    <div className="ed-field ed-field--wide">
                      <label className="ed-field__label">入域消息模板</label>
                      <input className="ed-input" value={vals["area_join_notify.message_template"] ?? ""} placeholder="欢迎 {name} 加入" onChange={(e) => setField("area_join_notify.message_template", e.target.value)} />
                    </div>
                    <div className="ed-field ed-field--wide">
                      <label className="ed-field__label">退域消息模板</label>
                      <input className="ed-input" value={vals["area_join_notify.message_template_leave"] ?? ""} placeholder="{name} 已退出域" onChange={(e) => setField("area_join_notify.message_template_leave", e.target.value)} />
                    </div>
                  </div>
                </section>
              )}
            </motion.div>
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}
