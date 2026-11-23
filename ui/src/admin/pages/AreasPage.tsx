import React, { useCallback, useEffect, useState } from "react";
import {
  AreaStrip,
  EdButton,
  EditorialSelect,
  SlideSheet,
  ToggleSwitch,
} from "../components/EditorialPrimitives";
import { apiReq, applyAreaOrder, saveAreaOrder, type AreaItem } from "../lib/api";
import { useApp } from "../lib/context";

export function AreasPage() {
  const { setStatus, toast, confirm, hasPlugin } = useApp();
  const showScreenShare = hasPlugin("screen-share");

  const [areas, setAreas] = useState<AreaItem[]>([]);
  const [currentArea, setCurrentArea] = useState("");
  const [invites, setInvites] = useState<any[]>([]);
  const [roles, setRoles] = useState<any[]>([]);
  const [channels, setChannels] = useState<any[]>([]);
  const [voiceChannels, setVoiceChannels] = useState<any[]>([]);

  // Area config state
  const [ac, setAc] = useState({
    name: "",
    default_channel: "",
    auto_assign_role_id: "",
    auto_assign_role_name: "",
    welcome_message: "",
    leave_message: "",
    admin_uids: "",
    plugins_enabled: "",
    plugins_disabled: "",
    use_announcement_style: "",
    screen_share_role_ids: [] as number[],
  });

  // Modals / sheets
  const [createOpen, setCreateOpen] = useState(false);
  const [newCh, setNewCh] = useState({ name: "", type: "text" });

  const [editCh, setEditCh] = useState<any | null>(null);
  const [onlineMembers, setOnlineMembers] = useState<any[]>([]);
  const [selectedAccessUids, setSelectedAccessUids] = useState<Set<string>>(new Set());

  const [dispatchInfo, setDispatchInfo] = useState<{ uid: string; name: string; from: string; to: string } | null>(null);

  const loadAreaDetail = useCallback(async (areaId: string) => {
    if (!areaId) return;
    try {
      const [metaRes, chRes, vcRes, cfgRes] = await Promise.all([
        apiReq<any>(`/admin/api/areas/${encodeURIComponent(areaId)}/meta`).catch(() => ({ roles: [] })),
        apiReq<any>(`/admin/api/channels?area=${encodeURIComponent(areaId)}`).catch(() => ({ channels: [] })),
        apiReq<any>(`/admin/api/voice-channels?area=${encodeURIComponent(areaId)}`).catch(() => ({ voice_channels: [] })),
        apiReq<any>(`/admin/api/area-configs/${encodeURIComponent(areaId)}`).catch(() => ({ config: {} })),
      ]);
      setRoles(metaRes.roles || []);
      setChannels(chRes.channels || []);
      setVoiceChannels(vcRes.voice_channels || []);
      const c = cfgRes.config || {};
      const ann = c.use_announcement_style;
      setAc({
        name: c.name || "",
        default_channel: c.default_channel || "",
        auto_assign_role_id: c.auto_assign_role_id || "",
        auto_assign_role_name: c.auto_assign_role_name || "",
        welcome_message: c.welcome_message || "",
        leave_message: c.leave_message || "",
        admin_uids: (c.admin_uids || []).join(", "),
        plugins_enabled: (c.plugins_enabled || []).join(", "),
        plugins_disabled: (c.plugins_disabled || []).join(", "),
        use_announcement_style: ann === true ? "true" : ann === false ? "false" : "",
        screen_share_role_ids: Array.isArray(c.screen_share_role_ids) ? c.screen_share_role_ids : [],
      });
    } catch (e: any) {
      toast(e.message, "error");
    }
  }, [toast]);

  const loadAll = useCallback(async () => {
    try {
      const [aRes, invRes] = await Promise.all([
        apiReq<any>("/admin/api/areas"),
        apiReq<any>("/admin/api/area-invites").catch(() => ({ invites: [] })),
      ]);
      const ordered = applyAreaOrder<AreaItem>(aRes.areas || []);
      setAreas(ordered);
      setInvites(invRes.invites || []);
      const nextArea = ordered.some((a) => a.id === currentArea) ? currentArea : (ordered[0]?.id || "");
      setCurrentArea(nextArea);
      if (nextArea) await loadAreaDetail(nextArea);
      setStatus("已同步", "success");
    } catch (e: any) {
      toast(e.message, "error");
    }
  }, [currentArea, loadAreaDetail, setStatus, toast]);

  useEffect(() => { loadAll(); }, []);

  const splitList = (s: string) => s.split(/[,，\s]+/).map((x) => x.trim()).filter(Boolean);

  const saveAreaConfig = async () => {
    if (!currentArea) return;
    const annVal = ac.use_announcement_style === "true" ? true : ac.use_announcement_style === "false" ? false : null;
    try {
      await apiReq(`/admin/api/area-configs/${encodeURIComponent(currentArea)}`, {
        method: "POST",
        body: JSON.stringify({
          name: ac.name.trim(),
          default_channel: ac.default_channel.trim(),
          auto_assign_role_id: ac.auto_assign_role_id.trim(),
          auto_assign_role_name: ac.auto_assign_role_name.trim(),
          welcome_message: ac.welcome_message.trim(),
          leave_message: ac.leave_message.trim(),
          admin_uids: splitList(ac.admin_uids),
          plugins_enabled: splitList(ac.plugins_enabled),
          plugins_disabled: splitList(ac.plugins_disabled),
          screen_share_role_ids: ac.screen_share_role_ids,
          use_announcement_style: annVal,
        }),
      });
      toast("域配置已保存", "success");
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  const deleteAreaConfig = async () => {
    if (!currentArea) return;
    if (!(await confirm("删除域配置", "确认删除该域的独立配置并回退到全局默认？", { okText: "确认删除" }))) return;
    try {
      await apiReq(`/admin/api/area-configs/${encodeURIComponent(currentArea)}`, { method: "DELETE" });
      toast("域配置已删除", "warning");
      await loadAreaDetail(currentArea);
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  const leaveArea = async () => {
    if (!currentArea) return;
    const aName = areas.find((a) => a.id === currentArea)?.name || currentArea;
    if (!(await confirm("退出当前域", `确认让 Bot 退出「${aName}」？`, { okText: "确认退出" }))) return;
    try {
      await apiReq("/admin/api/areas/leave", { method: "POST", body: JSON.stringify({ area: currentArea }) });
      toast("已退出域", "warning");
      setCurrentArea("");
      await loadAll();
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  const openEditChannel = async (ch: any) => {
    try {
      const [sRes, amRes, olRes] = await Promise.all([
        apiReq<any>(`/admin/api/channels/${encodeURIComponent(ch.id)}/settings`),
        apiReq<any>(`/admin/api/channels/${encodeURIComponent(ch.id)}/accessible-members`).catch(() => ({ members: [] })),
        apiReq<any>(`/admin/api/online-members?area=${encodeURIComponent(currentArea)}`).catch(() => ({ members: [] })),
      ]);
      const s = sRes.settings || {};
      setEditCh({
        id: ch.id,
        type: String(ch.type || "TEXT").toUpperCase(),
        name: s.name || ch.name || "",
        maxMember: s.maxMember || 30000,
        textGapSecond: s.textGapSecond || 0,
        voiceQuality: s.voiceQuality || "64k",
        voiceDelay: s.voiceDelay || "LOW",
        secret: !!s.secret,
        hasPassword: !!s.hasPassword,
        password: s.password || "",
      });
      setOnlineMembers(olRes.members || []);
      setSelectedAccessUids(new Set((amRes.members || []).map((m: any) => m.uid)));
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  const saveEditChannel = async () => {
    if (!editCh || !editCh.name.trim()) { toast("频道名不能为空", "warning"); return; }
    const isVoice = editCh.type === "VOICE" || editCh.type === "AUDIO";
    const body: Record<string, any> = {
      area: currentArea,
      name: editCh.name.trim(),
      maxMember: Number(editCh.maxMember) || 30000,
      textGapSecond: Number(editCh.textGapSecond) || 0,
      secret: !!editCh.secret,
      hasPassword: !!editCh.hasPassword,
      password: editCh.hasPassword ? editCh.password : "",
    };
    if (body.secret) body.accessibleMembers = Array.from(selectedAccessUids);
    if (isVoice) {
      body.voiceQuality = editCh.voiceQuality;
      body.voiceDelay = editCh.voiceDelay;
    }
    try {
      await apiReq(`/admin/api/channels/${encodeURIComponent(editCh.id)}/settings`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      setEditCh(null);
      toast("频道设置已保存", "success");
      await loadAreaDetail(currentArea);
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  return (
    <div className="ed-chapter">
      <div className="ed-chapter-bar">
        <div className="ed-chapter-bar__left">
          <h2 className="ed-chapter-bar__title">域管理</h2>
        </div>
        <div className="ed-chapter-bar__actions">
          <EdButton size="sm" variant="ghost" onClick={loadAll}>刷新</EdButton>
          <EdButton size="sm" variant="danger" disabled={!currentArea} onClick={leaveArea}>退出当前域</EdButton>
        </div>
      </div>

      <AreaStrip
        areas={areas}
        value={currentArea}
        onChange={(id) => { setCurrentArea(id); loadAreaDetail(id); }}
        onReorder={(next) => { setAreas(next); saveAreaOrder(next.map((a) => a.id)); }}
      />

      <section className="ed-cell">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, marginBottom: invites.length > 0 ? 14 : 8 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div className="ed-label"><span>域邀请</span></div>
            <span className={`ed-tag ${invites.length > 0 ? "ed-tag--gold" : "ed-tag--muted"}`}>
              {invites.length} 条待处理
            </span>
          </div>
          <EdButton
            size="sm"
            variant="ghost"
            onClick={async () => {
              try {
                const invRes = await apiReq<any>("/admin/api/area-invites");
                setInvites(invRes.invites || []);
                toast("邀请列表已刷新", "success");
              } catch (e: any) {
                toast(e.message || "刷新邀请失败", "error");
              }
            }}
          >
            刷新邀请
          </EdButton>
        </div>

        {invites.length === 0 ? (
          <div className="ed-empty" style={{ padding: "20px 12px" }}>
            暂无待处理的私信域邀请
          </div>
        ) : (
          <div style={{ display: "grid", gap: 10 }}>
            {invites.map((inv) => (
              <div
                key={inv.code}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  gap: 16,
                  flexWrap: "wrap",
                  padding: 14,
                  borderRadius: 14,
                  border: "1px solid var(--rule)",
                  background: "rgba(255,255,255,0.03)",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 14, minWidth: 0 }}>
                  {inv.areaAvatar && (
                    <img src={inv.areaAvatar} alt="" style={{ width: 44, height: 44, borderRadius: 12, objectFit: "cover", flexShrink: 0 }} />
                  )}
                  <div style={{ minWidth: 0 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                      <span style={{ fontWeight: 600, fontSize: 15 }}>{inv.areaName || inv.area}</span>
                      {inv.channelName && <span className="ed-tag">#{inv.channelName}</span>}
                      {inv.reason && <span className="ed-tag ed-tag--err">{inv.reason}</span>}
                    </div>
                    <div style={{ fontFamily: "var(--font-mono)", fontSize: 11.5, color: "var(--ink-faint)", marginTop: 3 }}>
                      发送者：{inv.senderName || inv.senderId || "-"} · 邀请码：{inv.code}{inv.receivedAt ? ` · ${inv.receivedAt}` : ""}
                    </div>
                  </div>
                </div>
                <div style={{ display: "flex", gap: 8 }}>
                  <EdButton
                    size="sm"
                    variant="primary"
                    disabled={!inv.canAccept}
                    onClick={async () => {
                      if (!(await confirm("接受域邀请", `确认加入「${inv.areaName || inv.area}」？`, { danger: false, okText: "接受邀请" }))) return;
                      await apiReq("/admin/api/area-invites/accept", { method: "POST", body: JSON.stringify({ code: inv.code }) });
                      toast("已加入该域", "success");
                      await loadAll();
                    }}
                  >
                    {inv.joined ? "已加入" : "接受"}
                  </EdButton>
                  <EdButton
                    size="sm"
                    variant="danger"
                    onClick={async () => {
                      if (!(await confirm("拒绝域邀请", `确认拒绝「${inv.areaName || inv.area}」的邀请？`, { okText: "确认拒绝" }))) return;
                      await apiReq("/admin/api/area-invites/reject", { method: "POST", body: JSON.stringify({ code: inv.code }) });
                      toast("已拒绝该邀请", "info");
                      await loadAll();
                    }}
                  >
                    拒绝
                  </EdButton>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="ed-cell">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 18 }}>
          <div className="ed-label"><span>域配置</span></div>
          <div style={{ display: "flex", gap: 8 }}>
            <EdButton size="sm" variant="primary" onClick={saveAreaConfig}>保存配置</EdButton>
            <EdButton size="sm" variant="danger" onClick={deleteAreaConfig}>删除配置</EdButton>
          </div>
        </div>
        <div className="ed-form-grid">
          <div className="ed-field">
            <label className="ed-field__label">域名称</label>
            <input className="ed-input" value={ac.name} onChange={(e) => setAc({ ...ac, name: e.target.value })} placeholder="仅日志显示" />
          </div>
          <div className="ed-field">
            <label className="ed-field__label">公告样式</label>
            <EditorialSelect
              value={ac.use_announcement_style}
              onChange={(v) => setAc({ ...ac, use_announcement_style: v })}
              options={[
                { value: "", label: "跟随全局默认" },
                { value: "true", label: "强制开启" },
                { value: "false", label: "强制关闭" },
              ]}
            />
          </div>
          <div className="ed-field">
            <label className="ed-field__label">默认频道</label>
            <EditorialSelect
              value={ac.default_channel}
              onChange={(v) => setAc({ ...ac, default_channel: v })}
              options={[
                { value: "", label: "不设置" },
                ...channels.map((ch) => ({ value: ch.id, label: `${ch.name || ch.id}`, group: ch.group || "未分组" })),
              ]}
            />
          </div>
          <div className="ed-field">
            <label className="ed-field__label">自动分配身份组</label>
            <EditorialSelect
              value={ac.auto_assign_role_id}
              onChange={(v) => {
                const hit = roles.find((r) => String(r.id) === v);
                setAc({ ...ac, auto_assign_role_id: v, auto_assign_role_name: hit?.name || "" });
              }}
              options={[
                { value: "", label: "不自动分配" },
                ...roles.map((r) => ({ value: String(r.id), label: `${r.name || r.id} (${r.id})` })),
              ]}
            />
          </div>
          {showScreenShare && (
            <div className="ed-field ed-field--wide">
              <label className="ed-field__label">允许发起屏幕共享的身份组</label>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {roles.map((r) => {
                  const rid = Number(r.id);
                  const checked = ac.screen_share_role_ids.includes(rid);
                  return (
                    <EdButton
                      key={rid}
                      size="sm"
                      variant={checked ? "primary" : "ghost"}
                      onClick={() => {
                        const next = checked
                          ? ac.screen_share_role_ids.filter((x) => x !== rid)
                          : [...ac.screen_share_role_ids, rid];
                        setAc({ ...ac, screen_share_role_ids: next });
                      }}
                    >
                      {r.name || rid}
                    </EdButton>
                  );
                })}
              </div>
            </div>
          )}
          <div className="ed-field ed-field--wide">
            <label className="ed-field__label">入域欢迎消息</label>
            <input className="ed-input" value={ac.welcome_message} onChange={(e) => setAc({ ...ac, welcome_message: e.target.value })} placeholder="欢迎 {name} 加入" />
          </div>
          <div className="ed-field ed-field--wide">
            <label className="ed-field__label">退域消息</label>
            <input className="ed-input" value={ac.leave_message} onChange={(e) => setAc({ ...ac, leave_message: e.target.value })} placeholder="留空继承全局" />
          </div>
          <div className="ed-field ed-field--wide">
            <label className="ed-field__label">管理员 UID（逗号分隔）</label>
            <input className="ed-input" value={ac.admin_uids} onChange={(e) => setAc({ ...ac, admin_uids: e.target.value })} />
          </div>
          <div className="ed-field">
            <label className="ed-field__label">启用插件（空=全部）</label>
            <input className="ed-input" value={ac.plugins_enabled} onChange={(e) => setAc({ ...ac, plugins_enabled: e.target.value })} />
          </div>
          <div className="ed-field">
            <label className="ed-field__label">禁用插件</label>
            <input className="ed-input" value={ac.plugins_disabled} onChange={(e) => setAc({ ...ac, plugins_disabled: e.target.value })} />
          </div>
        </div>
      </section>

      <div className="ed-grid ed-grid--2" style={{ flex: 1 }}>
        <section className="ed-cell ed-cell--flush">
          <div className="ed-cell-head">
            <div className="ed-label"><span>频道列表</span></div>
            <EdButton size="sm" variant="primary" onClick={() => { setNewCh({ name: "", type: "text" }); setCreateOpen(true); }}>创建频道</EdButton>
          </div>
          <div className="ed-table-wrap">
            <table className="ed-table">
              <thead>
                <tr>
                  <th style={{ width: "42%" }}>频道</th>
                  <th style={{ width: "18%" }}>类型</th>
                  <th style={{ width: "40%" }}>操作</th>
                </tr>
              </thead>
              <tbody>
                {channels.length === 0 ? (
                  <tr><td colSpan={3} className="ed-empty">暂无频道</td></tr>
                ) : (
                  channels.map((ch) => {
                    const isVoice = ["VOICE", "AUDIO"].includes(String(ch.type || "").toUpperCase());
                    return (
                      <tr key={ch.id}>
                        <td>
                          <div style={{ color: "var(--ink)", fontWeight: 500 }}>{ch.name}</div>
                          <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--ink-faint)" }}>{ch.id}</div>
                        </td>
                        <td>
                          <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                            <span className={`ed-tag ${isVoice ? "ed-tag--gold" : "ed-tag--ok"}`}>{isVoice ? "语音" : "文字"}</span>
                            {ch.secret && <span className="ed-tag ed-tag--err">私密</span>}
                          </div>
                        </td>
                        <td>
                          <div style={{ display: "flex", gap: 6 }}>
                            <EdButton size="sm" variant="ghost" onClick={() => openEditChannel(ch)}>编辑</EdButton>
                            <EdButton
                              size="sm"
                              variant="danger"
                              onClick={async () => {
                                if (!(await confirm("删除频道", `确认删除频道「${ch.name}」？`, { okText: "确认删除" }))) return;
                                await apiReq(`/admin/api/channels/${encodeURIComponent(ch.id)}`, {
                                  method: "DELETE",
                                  body: JSON.stringify({ area: currentArea }),
                                });
                                toast("频道已删除", "warning");
                                await loadAreaDetail(currentArea);
                              }}
                            >
                              删除
                            </EdButton>
                          </div>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section className="ed-cell ed-cell--flush">
          <div className="ed-cell-head">
            <div className="ed-label"><span>语音频道监控</span></div>
          </div>
          {voiceChannels.length === 0 ? (
            <div className="ed-empty">暂无语音频道</div>
          ) : (
            voiceChannels.map((vc) => (
              <div key={vc.id} style={{ padding: "16px 22px", borderBottom: "1px solid var(--rule)" }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 10 }}>
                  <strong style={{ fontSize: 14 }}>{vc.name}</strong>
                  <span className="ed-tag">{(vc.users || []).length} 人</span>
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                  {(vc.users || []).length === 0 ? (
                    <span style={{ fontSize: 12, color: "var(--ink-faint)" }}>空闲</span>
                  ) : (
                    (vc.users || []).map((u: any) => (
                      <div key={u.uid} style={{ display: "inline-flex", alignItems: "center", gap: 8, padding: "5px 10px", borderRadius: 999, border: "1px solid var(--rule)", background: "rgba(255,255,255,0.04)" }}>
                        {u.avatar && <img src={u.avatar} alt="" style={{ width: 24, height: 24, borderRadius: "50%", objectFit: "cover" }} />}
                        <span style={{ fontSize: 12.5 }}>{u.name}</span>
                        <EdButton
                          size="sm"
                          variant="primary"
                          onClick={() => {
                            const target = voiceChannels.find((x) => x.id !== vc.id)?.id || "";
                            setDispatchInfo({ uid: u.uid, name: u.name, from: vc.id, to: target });
                          }}
                        >
                          调度
                        </EdButton>
                      </div>
                    ))
                  )}
                </div>
              </div>
            ))
          )}
        </section>
      </div>

      {/* Create Channel Sheet */}
      <SlideSheet
        open={createOpen}
        title="创建频道"
        onClose={() => setCreateOpen(false)}
        footer={
          <>
            <EdButton variant="ghost" onClick={() => setCreateOpen(false)}>取消</EdButton>
            <EdButton
              variant="primary"
              onClick={async () => {
                if (!newCh.name.trim()) { toast("请输入频道名称", "warning"); return; }
                await apiReq("/admin/api/channels/create", {
                  method: "POST",
                  body: JSON.stringify({ area: currentArea, name: newCh.name.trim(), type: newCh.type }),
                });
                setCreateOpen(false);
                toast("频道已创建", "success");
                await loadAreaDetail(currentArea);
              }}
            >
              创建
            </EdButton>
          </>
        }
      >
        <div style={{ display: "grid", gap: 16 }}>
          <div className="ed-field">
            <label className="ed-field__label">频道名称</label>
            <input className="ed-input" value={newCh.name} onChange={(e) => setNewCh({ ...newCh, name: e.target.value })} />
          </div>
          <div className="ed-field">
            <label className="ed-field__label">频道类型</label>
            <EditorialSelect
              value={newCh.type}
              onChange={(t) => setNewCh({ ...newCh, type: t })}
              options={[
                { value: "text", label: "文字频道" },
                { value: "voice", label: "语音频道" },
              ]}
            />
          </div>
        </div>
      </SlideSheet>

      {/* Edit Channel Sheet */}
      <SlideSheet
        open={!!editCh}
        title={editCh ? `编辑 · ${editCh.name}` : "编辑频道"}
        onClose={() => setEditCh(null)}
        footer={
          <>
            <EdButton variant="ghost" onClick={() => setEditCh(null)}>取消</EdButton>
            <EdButton variant="primary" onClick={saveEditChannel}>保存</EdButton>
          </>
        }
      >
        {editCh && (
          <div style={{ display: "grid", gap: 14 }}>
            <div className="ed-field">
              <label className="ed-field__label">频道名称</label>
              <input className="ed-input" value={editCh.name} onChange={(e) => setEditCh({ ...editCh, name: e.target.value })} />
            </div>
            <div className="ed-form-grid">
              <div className="ed-field">
                <label className="ed-field__label">人数上限</label>
                <input className="ed-input" type="number" value={editCh.maxMember} onChange={(e) => setEditCh({ ...editCh, maxMember: e.target.value })} />
              </div>
              <div className="ed-field">
                <label className="ed-field__label">慢速模式（秒）</label>
                <input className="ed-input" type="number" value={editCh.textGapSecond} onChange={(e) => setEditCh({ ...editCh, textGapSecond: e.target.value })} />
              </div>
            </div>
            {(editCh.type === "VOICE" || editCh.type === "AUDIO") && (
              <div className="ed-form-grid">
                <div className="ed-field">
                  <label className="ed-field__label">语音质量</label>
                  <EditorialSelect
                    value={editCh.voiceQuality}
                    onChange={(v) => setEditCh({ ...editCh, voiceQuality: v })}
                    options={[{ value: "32k", label: "32k" }, { value: "64k", label: "64k" }, { value: "128k", label: "128k" }]}
                  />
                </div>
                <div className="ed-field">
                  <label className="ed-field__label">语音延迟</label>
                  <EditorialSelect
                    value={editCh.voiceDelay}
                    onChange={(v) => setEditCh({ ...editCh, voiceDelay: v })}
                    options={[{ value: "LOW", label: "低" }, { value: "NORMAL", label: "普通" }, { value: "HIGH", label: "高" }]}
                  />
                </div>
              </div>
            )}
            <div className="ed-switch-row">
              <span className="ed-field__label">私密频道</span>
              <ToggleSwitch checked={editCh.secret} onChange={(v) => setEditCh({ ...editCh, secret: v })} />
            </div>
            <div className="ed-switch-row">
              <span className="ed-field__label">启用密码</span>
              <ToggleSwitch checked={editCh.hasPassword} onChange={(v) => setEditCh({ ...editCh, hasPassword: v })} />
            </div>
            {editCh.hasPassword && (
              <div className="ed-field">
                <label className="ed-field__label">频道密码</label>
                <input className="ed-input" value={editCh.password} onChange={(e) => setEditCh({ ...editCh, password: e.target.value })} />
              </div>
            )}
            {editCh.secret && (
              <div>
                <div className="ed-label" style={{ marginBottom: 8 }}><span>ACCESSIBLE MEMBERS</span><span className="ed-label__zh">可访问在线成员</span></div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                  {onlineMembers.map((m) => {
                    const sel = selectedAccessUids.has(m.uid);
                    return (
                      <EdButton
                        key={m.uid}
                        size="sm"
                        variant={sel ? "primary" : "ghost"}
                        onClick={() => {
                          const next = new Set(selectedAccessUids);
                          if (sel) next.delete(m.uid); else next.add(m.uid);
                          setSelectedAccessUids(next);
                        }}
                      >
                        {m.name}
                      </EdButton>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        )}
      </SlideSheet>

      {/* Voice Dispatch Sheet */}
      <SlideSheet
        open={!!dispatchInfo}
        title="调度语音频道"
        onClose={() => setDispatchInfo(null)}
        footer={
          <>
            <EdButton variant="ghost" onClick={() => setDispatchInfo(null)}>取消</EdButton>
            <EdButton
              variant="primary"
              onClick={async () => {
                if (!dispatchInfo?.to) { toast("请选择目标频道", "warning"); return; }
                await apiReq("/admin/api/voice-channels/dispatch", {
                  method: "POST",
                  body: JSON.stringify({ area: currentArea, target: dispatchInfo.uid, to_channel: dispatchInfo.to, from_channel: dispatchInfo.from }),
                });
                setDispatchInfo(null);
                toast("已调度", "success");
                await loadAreaDetail(currentArea);
              }}
            >
              确认调度
            </EdButton>
          </>
        }
      >
        {dispatchInfo && (
          <div style={{ display: "grid", gap: 14 }}>
            <div style={{ fontSize: 13.5, color: "var(--ink-soft)" }}>将「{dispatchInfo.name}」调度到：</div>
            <EditorialSelect
              value={dispatchInfo.to}
              onChange={(v) => setDispatchInfo({ ...dispatchInfo, to: v })}
              options={voiceChannels
                .filter((vc) => vc.id !== dispatchInfo.from)
                .map((vc) => ({ value: vc.id, label: vc.name }))}
            />
          </div>
        )}
      </SlideSheet>
    </div>
  );
}
