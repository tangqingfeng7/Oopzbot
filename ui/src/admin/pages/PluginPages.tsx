import React, { useCallback, useEffect, useState } from "react";
import { motion } from "framer-motion";
import { AnimatedNumber, EdButton } from "../components/EditorialPrimitives";
import { apiReq, copyText } from "../lib/api";
import { useApp } from "../lib/context";

/* ============================================================================
   Plugin Page: Keyword Reply (/admin/keyword-reply)
   ============================================================================ */

export function KeywordReplyPage() {
  const { setStatus, toast } = useApp();
  const [rows, setRows] = useState<{ id: number; key: string; val: string }[]>([]);

  const load = useCallback(async () => {
    try {
      const data = await apiReq<any>("/admin/api/keyword-replies");
      const entries = Object.entries(data.keyword_replies || {});
      setRows(entries.map(([k, v], i) => ({ id: Date.now() + i, key: k, val: String(v ?? "") })));
      setStatus("已同步", "success");
    } catch (e: any) {
      toast(e.message, "error");
    }
  }, [setStatus, toast]);

  useEffect(() => { load(); }, [load]);

  const save = async () => {
    const obj: Record<string, string> = {};
    for (const r of rows) {
      const k = r.key.trim();
      if (k) obj[k] = r.val;
    }
    try {
      const res = await apiReq<any>("/admin/api/plugins/keyword_reply/config", {
        method: "POST",
        body: JSON.stringify({ config: { keyword_replies: obj } }),
      });
      toast(res.reload || "已保存", "success");
      await load();
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  return (
    <div className="ed-chapter">
      <div className="ed-chapter-bar">
        <div className="ed-chapter-bar__left">
          <h2 className="ed-chapter-bar__title">关键词回复</h2>
        </div>
        <div className="ed-chapter-bar__actions">
          <EdButton size="sm" variant="ghost" onClick={load}>刷新</EdButton>
          <EdButton size="sm" variant="primary" onClick={save}>保存并生效</EdButton>
        </div>
      </div>

      <section className="ed-cell" style={{ flex: 1 }}>
        <div style={{ display: "grid", gap: 10, maxWidth: 920 }}>
          {rows.map((r) => (
            <div key={r.id} style={{ display: "flex", gap: 10, alignItems: "center" }}>
              <input
                className="ed-input"
                style={{ flex: 0.36 }}
                placeholder="关键词"
                value={r.key}
                onChange={(e) => setRows((prev) => prev.map((x) => (x.id === r.id ? { ...x, key: e.target.value } : x)))}
              />
              <input
                className="ed-input"
                style={{ flex: 0.64 }}
                placeholder="回复内容"
                value={r.val}
                onChange={(e) => setRows((prev) => prev.map((x) => (x.id === r.id ? { ...x, val: e.target.value } : x)))}
              />
              <EdButton size="sm" variant="danger" onClick={() => setRows((prev) => prev.filter((x) => x.id !== r.id))}>
                删除
              </EdButton>
            </div>
          ))}
          <div>
            <EdButton size="sm" variant="ghost" onClick={() => setRows((prev) => [...prev, { id: Date.now(), key: "", val: "" }])}>
              + 添加关键词
            </EdButton>
          </div>
        </div>
      </section>
    </div>
  );
}

/* ============================================================================
   Plugin Page: Scheduler (/admin/scheduler)
   ============================================================================ */

const WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"];
function fmtWeekdays(wd: string) {
  if (!wd) return "-";
  const nums = String(wd).split(",").map(Number);
  if (nums.length === 7) return "每天";
  return nums.map((n) => "周" + (WEEKDAYS[n] || n)).join(" · ");
}

export function SchedulerPage() {
  const { setStatus, toast } = useApp();
  const [scheduled, setScheduled] = useState<any[]>([]);
  const [templates, setTemplates] = useState<any[]>([]);
  const [reminders, setReminders] = useState<any[]>([]);
  const [form, setForm] = useState({ name: "", hour: "8", minute: "0", weekdays: "0,1,2,3,4,5,6", channel: "", area: "", text: "" });

  const load = useCallback(async () => {
    try {
      const [s, t, r] = await Promise.all([
        apiReq<any>("/admin/api/scheduled-messages"),
        apiReq<any>("/admin/api/scheduled-message-templates"),
        apiReq<any>("/admin/api/reminders"),
      ]);
      setScheduled(s.items || []);
      setTemplates(t.items || []);
      setReminders(r.items || []);
      setStatus("列表已同步", "success");
    } catch (e: any) {
      toast(e.message, "error");
    }
  }, [setStatus, toast]);

  useEffect(() => { load(); }, [load]);

  const create = async () => {
    if (!form.name.trim() || !form.channel.trim() || !form.area.trim() || !form.text.trim()) {
      toast("请填写必填项", "warning");
      return;
    }
    try {
      await apiReq("/admin/api/scheduled-messages", {
        method: "POST",
        body: JSON.stringify({
          name: form.name.trim(),
          cron_hour: parseInt(form.hour || "0", 10),
          cron_minute: parseInt(form.minute || "0", 10),
          weekdays: form.weekdays.trim() || "0,1,2,3,4,5,6",
          channel_id: form.channel.trim(),
          area_id: form.area.trim(),
          message_text: form.text.trim(),
        }),
      });
      setForm((f) => ({ ...f, name: "", text: "" }));
      toast("定时任务已创建", "success");
      await load();
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  const applyTemplate = async (key: string) => {
    if (!form.channel.trim() || !form.area.trim()) {
      toast("请先填写频道 ID 和域 ID", "warning");
      return;
    }
    try {
      await apiReq(`/admin/api/scheduled-message-templates/${encodeURIComponent(key)}/apply`, {
        method: "POST",
        body: JSON.stringify({ channel_id: form.channel.trim(), area_id: form.area.trim() }),
      });
      toast("已从模板创建", "success");
      await load();
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  return (
    <div className="ed-chapter">
      <div className="ed-chapter-bar">
        <div className="ed-chapter-bar__left">
          <h2 className="ed-chapter-bar__title">定时任务</h2>
        </div>
        <div className="ed-chapter-bar__actions">
          <EdButton size="sm" variant="ghost" onClick={load}>刷新</EdButton>
        </div>
      </div>

      <div className="ed-grid ed-grid--2">
        <section className="ed-cell">
          <div className="ed-label" style={{ marginBottom: 16 }}>
            <span>新建定时消息</span>
          </div>
          <div className="ed-form-grid">
            <div className="ed-field">
              <label className="ed-field__label">任务名称</label>
              <input className="ed-input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="早安消息" />
            </div>
            <div className="ed-field">
              <label className="ed-field__label">触发时间</label>
              <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                <input className="ed-input" type="number" min={0} max={23} value={form.hour} onChange={(e) => setForm({ ...form, hour: e.target.value })} />
                <span>:</span>
                <input className="ed-input" type="number" min={0} max={59} value={form.minute} onChange={(e) => setForm({ ...form, minute: e.target.value })} />
              </div>
            </div>
            <div className="ed-field ed-field--wide">
              <label className="ed-field__label">星期（0-6，0=周一）</label>
              <input className="ed-input" value={form.weekdays} onChange={(e) => setForm({ ...form, weekdays: e.target.value })} />
            </div>
            <div className="ed-field">
              <label className="ed-field__label">频道 ID</label>
              <input className="ed-input" value={form.channel} onChange={(e) => setForm({ ...form, channel: e.target.value })} />
            </div>
            <div className="ed-field">
              <label className="ed-field__label">域 ID</label>
              <input className="ed-input" value={form.area} onChange={(e) => setForm({ ...form, area: e.target.value })} />
            </div>
            <div className="ed-field ed-field--wide">
              <label className="ed-field__label">消息内容</label>
              <textarea className="ed-textarea" rows={3} value={form.text} onChange={(e) => setForm({ ...form, text: e.target.value })} />
            </div>
          </div>
          <div style={{ marginTop: 14 }}>
            <EdButton variant="primary" size="sm" onClick={create}>创建任务</EdButton>
          </div>
        </section>

        <section className="ed-cell ed-cell--flush">
          <div className="ed-cell-head">
            <div className="ed-label"><span>预设模板</span></div>
          </div>
          {templates.length === 0 ? (
            <div className="ed-empty">暂无模板</div>
          ) : (
            templates.map((t) => (
              <div key={t.key} style={{ padding: "16px 24px", borderBottom: "1px solid var(--rule)", display: "grid", gap: 8 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <strong style={{ fontSize: 14 }}>{t.name}</strong>
                  <span className="ed-tag">{String(t.cron_hour).padStart(2, "0")}:{String(t.cron_minute).padStart(2, "0")} · {fmtWeekdays(t.weekdays)}</span>
                </div>
                <div style={{ fontSize: 12.5, color: "var(--ink-faint)" }}>{t.message_text}</div>
                <div style={{ display: "flex", gap: 8 }}>
                  <EdButton
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      setForm((f) => ({
                        ...f,
                        name: t.name || "",
                        hour: String(t.cron_hour ?? 8),
                        minute: String(t.cron_minute ?? 0),
                        weekdays: t.weekdays || "0,1,2,3,4,5,6",
                        text: t.message_text || "",
                      }));
                      toast("已套用到表单", "info");
                    }}
                  >
                    套用
                  </EdButton>
                  <EdButton size="sm" variant="primary" onClick={() => applyTemplate(t.key)}>一键创建</EdButton>
                </div>
              </div>
            ))
          )}
        </section>
      </div>

      <section className="ed-cell ed-cell--flush">
        <div className="ed-cell-head">
          <div className="ed-label"><span>定时消息</span></div>
        </div>
        <div className="ed-table-wrap">
          <table className="ed-table">
            <thead>
              <tr>
                <th style={{ width: "7%" }}>ID</th>
                <th style={{ width: "16%" }}>名称</th>
                <th style={{ width: "9%" }}>时间</th>
                <th style={{ width: "16%" }}>星期</th>
                <th style={{ width: "26%" }}>内容</th>
                <th style={{ width: "10%" }}>状态</th>
                <th style={{ width: "16%" }}>操作</th>
              </tr>
            </thead>
            <tbody>
              {scheduled.length === 0 ? (
                <tr><td colSpan={7} className="ed-empty">暂无定时消息</td></tr>
              ) : (
                scheduled.map((t) => (
                  <tr key={t.id}>
                    <td style={{ fontFamily: "var(--font-mono)" }}>{t.id}</td>
                    <td style={{ color: "var(--ink)", fontWeight: 500 }}>{t.name}</td>
                    <td style={{ fontFamily: "var(--font-mono)" }}>{String(t.cron_hour).padStart(2, "0")}:{String(t.cron_minute).padStart(2, "0")}</td>
                    <td>{fmtWeekdays(t.weekdays)}</td>
                    <td>{(t.message_text || "").slice(0, 48)}</td>
                    <td><span className={`ed-tag ${t.enabled ? "ed-tag--ok" : "ed-tag--muted"}`}>{t.enabled ? "启用" : "停用"}</span></td>
                    <td>
                      <div style={{ display: "flex", gap: 6 }}>
                        <EdButton size="sm" variant="ghost" onClick={async () => { await apiReq(`/admin/api/scheduled-messages/${t.id}/toggle`, { method: "POST", body: "{}" }); await load(); }}>
                          {t.enabled ? "停用" : "启用"}
                        </EdButton>
                        <EdButton size="sm" variant="danger" onClick={async () => { await apiReq(`/admin/api/scheduled-messages/${t.id}`, { method: "DELETE" }); await load(); }}>
                          删除
                        </EdButton>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="ed-cell ed-cell--flush">
        <div className="ed-cell-head">
          <div className="ed-label"><span>待执行提醒</span></div>
        </div>
        <div className="ed-table-wrap">
          <table className="ed-table">
            <thead>
              <tr>
                <th style={{ width: "10%" }}>ID</th>
                <th style={{ width: "20%" }}>用户</th>
                <th style={{ width: "22%" }}>触发时间</th>
                <th style={{ width: "48%" }}>内容</th>
              </tr>
            </thead>
            <tbody>
              {reminders.length === 0 ? (
                <tr><td colSpan={4} className="ed-empty">暂无待执行提醒</td></tr>
              ) : (
                reminders.map((r) => (
                  <tr key={r.id}>
                    <td style={{ fontFamily: "var(--font-mono)" }}>{r.id}</td>
                    <td style={{ fontFamily: "var(--font-mono)" }}>{(r.user_id || "-").slice(0, 12)}</td>
                    <td style={{ fontFamily: "var(--font-mono)" }}>{r.fire_at}</td>
                    <td>{(r.message_text || "").slice(0, 60)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

/* ============================================================================
   Plugin Page: Screen Share (/admin/screen-share)
   ============================================================================ */

export function ScreenSharePage() {
  const { setStatus, toast, confirm } = useApp();
  const [shares, setShares] = useState<any[]>([]);

  const load = useCallback(async () => {
    try {
      const data = await apiReq<any>("/admin/api/screen-shares");
      const list = Array.isArray(data.shares) ? data.shares : [];
      setShares(list);
      setStatus(list.length ? `活动共享 ${list.length}` : "暂无共享", "success");
    } catch (e: any) {
      toast(e.message, "error");
    }
  }, [setStatus, toast]);

  useEffect(() => { load(); }, [load]);

  const stopOne = async (s: any) => {
    const ok = await confirm(
      "结束屏幕共享",
      `确认结束 ${s.presenter_name || s.presenter_uid} 在「${s.channel_name || s.channel}」的屏幕共享？`,
      { okText: "结束共享" }
    );
    if (!ok) return;
    try {
      await apiReq(`/admin/api/screen-shares/${encodeURIComponent(s.id)}/stop`, { method: "POST", body: "{}" });
      toast("屏幕共享已结束", "warning");
      await load();
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  return (
    <div className="ed-chapter">
      <div className="ed-chapter-bar">
        <div className="ed-chapter-bar__left">
          <h2 className="ed-chapter-bar__title">屏幕共享</h2>
        </div>
        <div className="ed-chapter-bar__actions">
          <EdButton size="sm" variant="ghost" onClick={load}>刷新</EdButton>
        </div>
      </div>

      <div className="ed-grid ed-grid--2">
        <div className="ed-cell">
          <div className="ed-label"><span>正在共享</span></div>
          <div className="ed-num-lg"><AnimatedNumber value={shares.length} /></div>
        </div>
        <div className="ed-cell">
          <div className="ed-label"><span>链接权限</span></div>
          <div className="ed-num-md">会话有效</div>
        </div>
      </div>

      <section className="ed-cell ed-cell--flush" style={{ flex: 1 }}>
        {shares.length === 0 ? (
          <div className="ed-empty">当前没有正在进行的屏幕共享</div>
        ) : (
          shares.map((s) => (
            <div key={s.id} style={{ padding: "20px 28px", borderBottom: "1px solid var(--rule)", display: "grid", gap: 12 }}>
              <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 10 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  <span className="ed-live-dot ed-live-dot--success" />
                  <strong style={{ fontSize: 15 }}>{s.channel_name || s.channel}</strong>
                  <span className="ed-tag">{s.area_name || s.area}</span>
                  <span className="ed-tag">{s.presenter_name || s.presenter_uid}</span>
                </div>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: 11.5, color: "var(--ink-faint)" }}>
                  {s.ready_at ? new Date(Number(s.ready_at) * 1000).toLocaleString("zh-CN", { hour12: false }) : "-"}
                </span>
              </div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <input className="ed-input ed-input--mono" style={{ flex: 1, minWidth: 220 }} readOnly value={s.viewer_url || ""} />
                <EdButton size="sm" variant="ghost" onClick={async () => { await copyText(s.viewer_url || ""); toast("观看链接已复制", "success"); }}>复制</EdButton>
                <a className="ed-btn ed-btn--primary ed-btn--sm" href={s.viewer_url} target="_blank" rel="noreferrer"><span>打开</span></a>
                <EdButton size="sm" variant="danger" onClick={() => stopOne(s)}>结束共享</EdButton>
              </div>
            </div>
          ))
        )}
      </section>
    </div>
  );
}

/* ============================================================================
   Plugin Page: Activity Stats (/admin/activity) — Custom SVG Editorial Charts
   ============================================================================ */

const RANK_TITLES = [
  { min: 1000, label: "宇宙级话痨", color: "#e6c27a" },
  { min: 200, label: "群聊永动机", color: "#c084fc" },
  { min: 100, label: "话痨之王", color: "#818cf8" },
  { min: 50, label: "社交牛逼症", color: "#fb923c" },
  { min: 20, label: "活跃分子", color: "#fbbf24" },
  { min: 5, label: "冒泡选手", color: "#6ee7b7" },
  { min: 1, label: "潜水偷看", color: "#38bdf8" },
  { min: 0, label: "查无此人", color: "#94a3b8" },
];

export function ActivityPage() {
  const { setStatus, toast } = useApp();
  const [overview, setOverview] = useState({ today_messages: 0, week_messages: 0, active_users_today: 0 });
  const [daily, setDaily] = useState<{ date: string; total: number }[]>([]);
  const [ranking, setRanking] = useState<any[]>([]);

  const load = useCallback(async () => {
    try {
      const [ov, d, r] = await Promise.all([
        apiReq<any>("/admin/api/message-stats/overview"),
        apiReq<any>("/admin/api/message-stats/daily?days=14"),
        apiReq<any>("/admin/api/message-stats/ranking?days=7&limit=10"),
      ]);
      setOverview({
        today_messages: ov.today_messages || 0,
        week_messages: ov.week_messages || 0,
        active_users_today: ov.active_users_today || 0,
      });
      setDaily(d.daily || []);
      setRanking(r.ranking || []);
      setStatus("活跃统计已同步", "success");
    } catch (e: any) {
      toast(e.message, "error");
    }
  }, [setStatus, toast]);

  useEffect(() => { load(); }, [load]);

  const maxDaily = Math.max(1, ...daily.map((x) => x.total));
  const maxRank = Math.max(1, ...ranking.map((x) => x.total));

  const svgW = 560;
  const svgH = 210;
  const padX = 16;
  const padY = 18;
  const pts = daily.map((d, i) => {
    const x = daily.length > 1 ? padX + (i / (daily.length - 1)) * (svgW - padX * 2) : svgW / 2;
    const y = svgH - padY - (d.total / maxDaily) * (svgH - padY * 2);
    return { x, y, ...d };
  });
  const linePath = pts.map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ");
  const areaPath = pts.length
    ? `${linePath} L ${pts[pts.length - 1].x.toFixed(1)} ${svgH - padY} L ${pts[0].x.toFixed(1)} ${svgH - padY} Z`
    : "";

  return (
    <div className="ed-chapter">
      <div className="ed-chapter-bar">
        <div className="ed-chapter-bar__left">
          <h2 className="ed-chapter-bar__title">活跃统计</h2>
        </div>
        <div className="ed-chapter-bar__actions">
          <EdButton size="sm" variant="ghost" onClick={load}>刷新</EdButton>
        </div>
      </div>

      <div className="ed-grid ed-grid--3">
        <div className="ed-cell">
          <div className="ed-label"><span>今日消息</span></div>
          <div className="ed-num-lg"><AnimatedNumber value={overview.today_messages} /></div>
        </div>
        <div className="ed-cell">
          <div className="ed-label"><span>本周消息</span></div>
          <div className="ed-num-lg"><AnimatedNumber value={overview.week_messages} /></div>
        </div>
        <div className="ed-cell">
          <div className="ed-label"><span>今日活跃</span></div>
          <div className="ed-num-lg"><AnimatedNumber value={overview.active_users_today} /></div>
        </div>
      </div>

      <div className="ed-grid ed-grid--2">
        <section className="ed-cell">
          <div className="ed-label" style={{ marginBottom: 14 }}>
            <span>14 天消息趋势</span>
          </div>
          {pts.length === 0 ? (
            <div className="ed-empty">暂无趋势数据</div>
          ) : (
            <svg viewBox={`0 0 ${svgW} ${svgH}`} style={{ width: "100%", height: 220, display: "block" }}>
              <defs>
                <linearGradient id="edAreaGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#0a84ff" stopOpacity="0.32" />
                  <stop offset="100%" stopColor="#0a84ff" stopOpacity="0" />
                </linearGradient>
              </defs>
              {[0.25, 0.5, 0.75, 1].map((r) => (
                <line
                  key={r}
                  x1={padX}
                  x2={svgW - padX}
                  y1={svgH - padY - r * (svgH - padY * 2)}
                  y2={svgH - padY - r * (svgH - padY * 2)}
                  stroke="rgba(255,255,255,0.08)"
                />
              ))}
              <path d={areaPath} fill="url(#edAreaGrad)" />
              <motion.path
                d={linePath}
                fill="none"
                stroke="#409cff"
                strokeWidth={2.2}
                strokeLinecap="round"
                strokeLinejoin="round"
                initial={{ pathLength: 0 }}
                animate={{ pathLength: 1 }}
                transition={{ duration: 0.65, ease: [0.22, 1, 0.36, 1] }}
              />
              {pts.map((p) => (
                <g key={p.date}>
                  <circle cx={p.x} cy={p.y} r={3.5} fill="#ffffff" stroke="#0a84ff" strokeWidth={1.5} />
                  <title>{`${p.date}: ${p.total}`}</title>
                </g>
              ))}
            </svg>
          )}
        </section>

        <section className="ed-cell">
          <div className="ed-label" style={{ marginBottom: 14 }}>
            <span>活跃排行</span>
          </div>
          {ranking.length === 0 ? (
            <div className="ed-empty">暂无排行数据</div>
          ) : (
            <div style={{ display: "grid", gap: 12 }}>
              {ranking.map((r, i) => (
                <div key={r.user_id || i} style={{ display: "grid", gridTemplateColumns: "110px 1fr 48px", gap: 12, alignItems: "center" }}>
                  <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontSize: 13 }}>
                    {r.display_name || (r.user_id || "").slice(0, 8)}
                  </span>
                  <div style={{ height: 7, borderRadius: 999, background: "rgba(255,255,255,0.08)", overflow: "hidden", position: "relative" }}>
                    <motion.div
                      initial={{ width: 0 }}
                      animate={{ width: `${Math.max(4, (r.total / maxRank) * 100)}%` }}
                      transition={{ duration: 0.55, delay: i * 0.03, ease: [0.22, 1, 0.36, 1] }}
                      style={{ height: "100%", borderRadius: 999, background: i === 0 ? "var(--accent)" : "rgba(245, 245, 247, 0.72)" }}
                    />
                  </div>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, textAlign: "right", color: "var(--ink-faint)" }}>{r.total}</span>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>

      <section className="ed-cell ed-cell--flush" style={{ flex: 1 }}>
        <div className="ed-table-wrap">
          <table className="ed-table">
            <thead>
              <tr>
                <th style={{ width: "10%" }}>NO.</th>
                <th style={{ width: "36%" }}>用户</th>
                <th style={{ width: "20%" }}>消息数</th>
                <th style={{ width: "34%" }}>称号</th>
              </tr>
            </thead>
            <tbody>
              {ranking.length === 0 ? (
                <tr><td colSpan={4} className="ed-empty">暂无数据</td></tr>
              ) : (
                ranking.map((r, i) => {
                  const title = RANK_TITLES.find((t) => (r.total || 0) >= t.min) || RANK_TITLES[RANK_TITLES.length - 1];
                  return (
                    <tr key={r.user_id || i}>
                      <td><span className={`ed-rank-num${i < 3 ? " ed-rank-num--top" : ""}`}>{String(i + 1).padStart(2, "0")}</span></td>
                      <td style={{ color: "var(--ink)", fontWeight: 500 }}>{r.display_name || (r.user_id || "").slice(0, 12)}</td>
                      <td style={{ fontFamily: "var(--font-mono)" }}>{r.total}</td>
                      <td>
                        <span className="ed-tag" style={{ borderColor: title.color, color: title.color }}>
                          {title.label}
                        </span>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
