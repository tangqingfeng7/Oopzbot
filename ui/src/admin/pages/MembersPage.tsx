import React, { useCallback, useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import {
  AnimatedNumber,
  AreaStrip,
  EdButton,
  EditorialSelect,
  SlideSheet,
  type SelectOption,
} from "../components/EditorialPrimitives";
import { apiReq, applyAreaOrder, saveAreaOrder, type AreaItem } from "../lib/api";
import { useApp } from "../lib/context";

const MUTE_DURATIONS = [
  { label: "5", unit: "分钟", sec: 300 },
  { label: "10", unit: "分钟", sec: 600 },
  { label: "30", unit: "分钟", sec: 1800 },
  { label: "1", unit: "小时", sec: 3600 },
  { label: "12", unit: "小时", sec: 43200 },
  { label: "24", unit: "小时", sec: 86400 },
];

interface MembersSnapshot {
  members: any[];
  total: number;
  online: number;
  ts: number;
}

const CLIENT_CACHE_TTL_MS = 30_000;
const CLIENT_STALE_MS = 12_000;
let _cachedAreas: { items: AreaItem[]; ts: number } | null = null;
const _cachedMembers = new Map<string, MembersSnapshot>();
const _cachedBlocks = new Map<string, { items: any[]; ts: number }>();

function readHintFirstArea(): string {
  try {
    const raw = localStorage.getItem("oopz_admin_area_order_v1");
    if (raw) {
      const ids = JSON.parse(raw);
      if (Array.isArray(ids) && typeof ids[0] === "string" && ids[0].trim()) {
        return ids[0].trim();
      }
    }
  } catch {
    // ignore
  }
  return "";
}

export function MembersPage() {
  const { setStatus, toast, confirm } = useApp();
  const initialAreas = _cachedAreas?.items || [];
  const initialArea = initialAreas[0]?.id || readHintFirstArea() || "__all__";
  const initialSnap = _cachedMembers.get(`${initialArea}:0:`);

  const [areas, setAreas] = useState<AreaItem[]>(initialAreas);
  const [currentArea, setCurrentArea] = useState<string>(initialArea);
  const [keyword, setKeyword] = useState("");
  const [offset, setOffset] = useState(0);
  const pageSize = 20;

  const [members, setMembers] = useState<any[]>(initialSnap?.members || []);
  const [membersLoading, setMembersLoading] = useState(!initialSnap);
  const [loadError, setLoadError] = useState(false);
  const [total, setTotal] = useState(initialSnap?.total || 0);
  const [online, setOnline] = useState(initialSnap?.online || 0);
  const [blocks, setBlocks] = useState<any[]>(_cachedBlocks.get(initialArea)?.items || []);
  const [showBlocks, setShowBlocks] = useState(false);
  const loadSeqRef = useRef(0);

  // Detail sheet
  const [detailUid, setDetailUid] = useState<string | null>(null);
  const [detailArea, setDetailArea] = useState<string>("");
  const [detailData, setDetailData] = useState<any | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // Duration & cross-area picker sheets
  const [durPicker, setDurPicker] = useState<{ mode: "text" | "mic"; resolve: (sec: number) => void } | null>(null);
  const [areaPicker, setAreaPicker] = useState<{ list: { areaId: string; areaName?: string }[]; resolve: (id: string) => void } | null>(null);

  // Broadcast composer
  const [sendArea, setSendArea] = useState("");
  const [channelOpts, setChannelOpts] = useState<SelectOption[]>([]);
  const [sendChannel, setSendChannel] = useState("");
  const [sendText, setSendText] = useState("");

  const loadChannels = useCallback(async (areaId: string) => {
    if (!areaId) { setChannelOpts([]); return; }
    try {
      const data = await apiReq<any>(`/admin/api/channels?area=${encodeURIComponent(areaId)}`);
      const opts: SelectOption[] = (data.channels || [])
        .filter((ch: any) => String(ch.type || "").toUpperCase() !== "ARTICLE")
        .map((ch: any) => {
          const chType = String(ch.type || "").toUpperCase();
          return {
            value: ch.id,
            label: (ch.name || ch.id) + (chType === "VOICE" || chType === "AUDIO" ? " [语音]" : ""),
            group: ch.group || undefined,
          };
        });
      setChannelOpts(opts);
    } catch {
      setChannelOpts([]);
    }
  }, []);

  const loadMembers = useCallback(
    async (area = currentArea, kw = keyword, off = offset, opts?: { force?: boolean }) => {
      const force = !!opts?.force;
      const cacheKey = `${area}:${off}:${kw.trim()}`;
      const cached = !force ? _cachedMembers.get(cacheKey) : undefined;
      const now = Date.now();
      const hasWarm = Boolean(cached && now - cached.ts < CLIENT_CACHE_TTL_MS);

      const seq = ++loadSeqRef.current;
      setLoadError(false);
      if (cached && hasWarm) {
        setMembers(cached.members);
        setTotal(cached.total);
        setOnline(cached.online);
        setMembersLoading(false);
        setStatus(`成员 ${cached.members.length} / ${cached.total}`, "success");
        if (now - cached.ts < CLIENT_STALE_MS) {
          return;
        }
      } else {
        setMembersLoading(true);
      }

      const isAll = area === "__all__";
      const size = isAll ? 500 : pageSize;
      let url = `/admin/api/members?offset=${off}&limit=${size}&area=${encodeURIComponent(area)}`;
      if (kw.trim()) url += `&keyword=${encodeURIComponent(kw.trim())}`;
      if (force) url += "&refresh=1";
      try {
        const data = await apiReq<any>(url);
        if (seq !== loadSeqRef.current) return;
        const nextSnap: MembersSnapshot = {
          members: data.members || [],
          total: data.total || 0,
          online: data.online || 0,
          ts: Date.now(),
        };
        _cachedMembers.set(cacheKey, nextSnap);
        setMembers(nextSnap.members);
        setTotal(nextSnap.total);
        setOnline(nextSnap.online);
        setStatus(`成员 ${nextSnap.members.length} / ${nextSnap.total}`, "success");
      } catch (e: any) {
        if (seq !== loadSeqRef.current) return;
        if (!hasWarm) {
          setLoadError(true);
          setStatus("加载失败", "error");
          toast(e.message, "error");
        }
      } finally {
        if (seq === loadSeqRef.current) {
          setMembersLoading(false);
        }
      }
    },
    [currentArea, keyword, offset, setStatus, toast]
  );

  const loadBlocks = useCallback(async (area = currentArea, opts?: { force?: boolean }) => {
    const force = !!opts?.force;
    const cached = !force ? _cachedBlocks.get(area) : undefined;
    if (cached && Date.now() - cached.ts < CLIENT_CACHE_TTL_MS) {
      setBlocks(cached.items);
      if (Date.now() - cached.ts < CLIENT_STALE_MS) return;
    }
    try {
      const url = `/admin/api/members/blocks?area=${encodeURIComponent(area)}${force ? "&refresh=1" : ""}`;
      const data = await apiReq<any>(url);
      const list = data.blocks || [];
      _cachedBlocks.set(area, { items: list, ts: Date.now() });
      setBlocks(list);
    } catch {
      if (!cached) setBlocks([]);
    }
  }, [currentArea]);

  const initLoad = useCallback(async () => {
    const hintArea = _cachedAreas?.items?.[0]?.id || readHintFirstArea();
    // 若本地已知首选域，直接并发拉取域列表与该域成员，消除串行等待。
    const speculative = hintArea ? loadMembers(hintArea, "", 0) : null;
    try {
      let ordered: AreaItem[];
      if (_cachedAreas && Date.now() - _cachedAreas.ts < CLIENT_CACHE_TTL_MS) {
        ordered = _cachedAreas.items;
      } else {
        const data = await apiReq<any>("/admin/api/areas");
        ordered = applyAreaOrder<AreaItem>(data.areas || []);
        _cachedAreas = { items: ordered, ts: Date.now() };
      }
      setAreas(ordered);
      const first = ordered[0]?.id || "__all__";
      setCurrentArea(first);
      if (ordered[0]?.id) {
        setSendArea(ordered[0].id);
        loadChannels(ordered[0].id);
      }
      if (!speculative || first !== hintArea) {
        await loadMembers(first, "", 0);
      } else {
        await speculative;
      }
      loadBlocks(first);
    } catch (e: any) {
      setLoadError(true);
      setMembersLoading(false);
      toast(e.message, "error");
    }
  }, [loadBlocks, loadChannels, loadMembers, toast]);

  useEffect(() => { initLoad(); }, []);

  const pickDuration = (mode: "text" | "mic") =>
    new Promise<number>((resolve) => setDurPicker({ mode, resolve }));

  const resolveMemberArea = async (uid: string): Promise<string> => {
    if (currentArea && currentArea !== "__all__") return currentArea;
    const m = members.find((x) => x.uid === uid);
    const list: { areaId: string; areaName?: string }[] = m?.areas || [];
    if (list.length === 1) return list[0].areaId;
    if (list.length > 1) {
      return new Promise<string>((resolve) => setAreaPicker({ list, resolve }));
    }
    return areas[0]?.id || "";
  };

  const openDetail = async (uid: string, explicitArea?: string) => {
    const area = explicitArea || (currentArea !== "__all__" ? currentArea : members.find((m) => m.uid === uid)?.areas?.[0]?.areaId || areas[0]?.id || "");
    setDetailUid(uid);
    setDetailArea(area);
    setDetailLoading(true);
    setDetailData(null);
    try {
      const data = await apiReq<any>(`/admin/api/members/${encodeURIComponent(uid)}?area=${encodeURIComponent(area)}`);
      setDetailData(data);
    } catch (e: any) {
      toast(`加载详情失败：${e.message}`, "error");
    } finally {
      setDetailLoading(false);
    }
  };

  const moderate = async (uid: string, action: string, label: string, extra?: Record<string, any>, closeAfter?: boolean) => {
    const area = await resolveMemberArea(uid);
    if (!area) return;
    try {
      await apiReq(`/admin/api/members/${encodeURIComponent(uid)}/${action}`, {
        method: "POST",
        body: JSON.stringify({ area, ...(extra || {}) }),
      });
      toast(`已${label}`, "success");
      _cachedMembers.clear();
      if (closeAfter) setDetailUid(null);
      else if (detailUid === uid) openDetail(uid, area);
      loadMembers(currentArea, keyword, offset, { force: true });
    } catch (e: any) {
      toast(`${label}失败：${e.message}`, "error");
    }
  };

  const doMute = async (uid: string) => {
    const sec = await pickDuration("text");
    if (sec) await moderate(uid, "mute", "禁言", { duration: sec });
  };

  const doMuteMic = async (uid: string) => {
    const sec = await pickDuration("mic");
    if (sec) await moderate(uid, "mute-mic", "禁麦", { duration: sec });
  };

  const doKick = async (uid: string) => {
    if (await confirm("踢出用户", "确认将该用户踢出域？此操作不可撤销。", { okText: "确认踢出" })) {
      await moderate(uid, "kick", "踢出", undefined, true);
    }
  };

  const doBlock = async (uid: string) => {
    if (await confirm("封禁用户", "确认封禁该用户？封禁后将无法重新加入。", { okText: "确认封禁" })) {
      await moderate(uid, "block", "封禁", undefined, true);
      _cachedBlocks.clear();
      loadBlocks(currentArea, { force: true });
    }
  };

  const doRole = async (uid: string, roleId: number, action: "add" | "remove") => {
    const area = await resolveMemberArea(uid);
    if (!area) return;
    try {
      const res = await apiReq<any>(`/admin/api/members/${encodeURIComponent(uid)}/role`, {
        method: "POST",
        body: JSON.stringify({ role_id: roleId, action, area }),
      });
      toast(res.message || "身份组已更新", "success");
      _cachedMembers.clear();
      openDetail(uid, area);
      loadMembers(currentArea, keyword, offset, { force: true });
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  const doAdminToggle = async (uid: string, grant: boolean) => {
    const ok = await confirm(
      grant ? "设为 Bot 管理员" : "撤销 Bot 管理员",
      grant ? "确认授予该用户 Bot 管理员权限？" : "确认撤销该用户的 Bot 管理员权限？",
      { okText: grant ? "确认授予" : "确认撤销", danger: !grant }
    );
    if (!ok) return;
    try {
      if (grant) {
        await apiReq("/admin/api/bot-admins", { method: "POST", body: JSON.stringify({ uid }) });
      } else {
        await apiReq(`/admin/api/bot-admins/${encodeURIComponent(uid)}`, { method: "DELETE" });
      }
      toast(grant ? "已设为管理员" : "已撤销管理员", "success");
      _cachedMembers.clear();
      openDetail(uid, detailArea);
      loadMembers(currentArea, keyword, offset, { force: true });
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  const sendMsg = async (announce: boolean) => {
    if (!sendChannel) { toast("请先选择频道", "warning"); return; }
    if (!sendText.trim()) { toast("内容不能为空", "warning"); return; }
    try {
      await apiReq(announce ? "/admin/api/send-announcement" : "/admin/api/send-message", {
        method: "POST",
        body: JSON.stringify({ area: sendArea, channel: sendChannel, text: sendText }),
      });
      setSendText("");
      toast(announce ? "公告已发送" : "消息已发送", "success");
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  const step = currentArea === "__all__" ? 500 : pageSize;
  const page = Math.floor(offset / step) + 1;
  const pages = Math.max(1, Math.ceil(total / step));

  return (
    <div className="ed-chapter">
      <div className="ed-chapter-bar">
        <div className="ed-chapter-bar__left">
          <h2 className="ed-chapter-bar__title">成员</h2>
        </div>
        <div className="ed-chapter-bar__actions">
          <input
            className="ed-input"
            style={{ width: 200, minHeight: 32 }}
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { setOffset(0); loadMembers(currentArea, keyword, 0); } }}
            placeholder="搜索昵称 / UID..."
          />
          <EdButton size="sm" variant="primary" onClick={() => { setOffset(0); loadMembers(currentArea, keyword, 0); }}>搜索</EdButton>
          <EdButton size="sm" variant="ghost" onClick={() => { _cachedMembers.clear(); _cachedBlocks.clear(); loadMembers(currentArea, keyword, offset, { force: true }); loadBlocks(currentArea, { force: true }); }}>
            刷新
          </EdButton>
          <EdButton size="sm" variant="ghost" onClick={() => { setShowBlocks((b) => !b); loadBlocks(currentArea, { force: true }); }}>
            封禁列表 ({blocks.length})
          </EdButton>
        </div>
      </div>

      <AreaStrip
        areas={areas}
        value={currentArea}
        includeAll
        onChange={(id) => {
          setCurrentArea(id);
          setOffset(0);
          loadMembers(id, keyword, 0);
          loadBlocks(id);
        }}
        onReorder={(next) => {
          setAreas(next);
          saveAreaOrder(next.map((a) => a.id));
        }}
      />

      <div className="ed-grid ed-grid--3">
        <div className="ed-cell">
          <div className="ed-label"><span>总成员</span></div>
          <div className="ed-num-lg"><AnimatedNumber value={total} /></div>
        </div>
        <div className="ed-cell">
          <div className="ed-label"><span>在线</span></div>
          <div className="ed-num-lg"><AnimatedNumber value={online} /></div>
        </div>
        <div className="ed-cell">
          <div className="ed-label"><span>封禁中</span></div>
          <div className="ed-num-lg"><AnimatedNumber value={blocks.length} /></div>
        </div>
      </div>

      {showBlocks && (
        <section className="ed-cell ed-cell--flush">
          <div className="ed-cell-head">
            <div className="ed-label"><span>封禁列表</span></div>
          </div>
          <div className="ed-table-wrap">
            <table className="ed-table">
              <thead>
                <tr>
                  <th style={{ width: "40%" }}>昵称</th>
                  <th style={{ width: "40%" }}>UID</th>
                  <th style={{ width: "20%" }}>操作</th>
                </tr>
              </thead>
              <tbody>
                {blocks.length === 0 ? (
                  <tr><td colSpan={3} className="ed-empty">暂无封禁</td></tr>
                ) : (
                  blocks.map((b) => (
                    <tr key={`${b.uid}-${b.areaId || ""}`}>
                      <td style={{ color: "var(--ink)" }}>
                        {b.name} {b.areaName && <span className="ed-tag">{b.areaName}</span>}
                      </td>
                      <td style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}>{b.uid}</td>
                      <td>
                        <EdButton
                          size="sm"
                          variant="ghost"
                          onClick={async () => {
                            const area = b.areaId || (currentArea !== "__all__" ? currentArea : "");
                            if (!area) return;
                            await apiReq(`/admin/api/members/${encodeURIComponent(b.uid)}/unblock`, {
                              method: "POST",
                              body: JSON.stringify({ area }),
                            });
                            toast("已解封", "success");
                            _cachedBlocks.clear();
                            loadBlocks(currentArea, { force: true });
                          }}
                        >
                          解封
                        </EdButton>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Members Table */}
      <section className="ed-cell ed-cell--flush ed-cell--bb">
        <div className="ed-table-wrap">
          <table className="ed-table">
            <thead>
              <tr>
                <th style={{ width: "38%" }}>成员</th>
                <th style={{ width: "24%" }}>身份组</th>
                <th style={{ width: "12%" }}>状态</th>
                <th style={{ width: "26%" }}>操作</th>
              </tr>
            </thead>
            <tbody>
              {membersLoading ? (
                Array.from({ length: 5 }).map((_, idx) => (
                  <motion.tr
                    key={`skel-${idx}`}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ duration: 0.2, delay: idx * 0.04 }}
                  >
                    <td>
                      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                        <span className="ed-skel ed-skel--circle" style={{ width: 30, height: 30 }} />
                        <div style={{ display: "grid", gap: 6, flex: 1 }}>
                          <span className="ed-skel" style={{ width: `${38 + (idx % 3) * 14}%`, height: 13 }} />
                          <span className="ed-skel" style={{ width: `${22 + (idx % 2) * 12}%`, height: 10, opacity: 0.65 }} />
                        </div>
                      </div>
                    </td>
                    <td>
                      <div style={{ display: "flex", gap: 6 }}>
                        <span className="ed-skel ed-skel--pill" style={{ width: 52, height: 22 }} />
                        <span className="ed-skel ed-skel--pill" style={{ width: 64, height: 22 }} />
                      </div>
                    </td>
                    <td>
                      <span className="ed-skel ed-skel--pill" style={{ width: 44, height: 22 }} />
                    </td>
                    <td>
                      <div style={{ display: "flex", gap: 6 }}>
                        <span className="ed-skel" style={{ width: 48, height: 28, borderRadius: 9 }} />
                        <span className="ed-skel" style={{ width: 48, height: 28, borderRadius: 9 }} />
                        <span className="ed-skel" style={{ width: 48, height: 28, borderRadius: 9 }} />
                      </div>
                    </td>
                  </motion.tr>
                ))
              ) : members.length === 0 ? (
                <tr>
                  <td colSpan={4} className="ed-empty">
                    {loadError ? (
                      <div style={{ display: "inline-flex", alignItems: "center", gap: 12 }}>
                        <span>成员加载失败</span>
                        <EdButton size="sm" variant="ghost" onClick={() => loadMembers(currentArea, keyword, offset)}>重试</EdButton>
                      </div>
                    ) : keyword.trim() ? (
                      "未找到匹配成员"
                    ) : (
                      <div className="ed-loading-dots" aria-label="同步成员中">
                        <span />
                        <span />
                        <span />
                      </div>
                    )}
                  </td>
                </tr>
              ) : (
                members.map((m, idx) => (
                  <motion.tr
                    key={m.uid}
                    initial={{ opacity: 0, y: 6 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.22, delay: Math.min(idx * 0.02, 0.22), ease: [0.22, 1, 0.36, 1] }}
                  >
                    <td>
                      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                        {m.avatar ? (
                          <img src={m.avatar} alt="" style={{ width: 30, height: 30, borderRadius: "50%", objectFit: "cover", flexShrink: 0 }} loading="lazy" />
                        ) : (
                          <div style={{ width: 30, height: 30, borderRadius: "50%", border: "1px solid var(--rule)", display: "grid", placeItems: "center", fontSize: 12, flexShrink: 0 }}>
                            {(m.name || "?").slice(0, 1)}
                          </div>
                        )}
                        <div style={{ minWidth: 0 }}>
                          <div style={{ color: "var(--ink)", fontWeight: 500, display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                            <span>{m.name}</span>
                            {(m.areas || []).map((a: any) => (
                              <span key={a.areaId} className="ed-tag">{a.areaName}</span>
                            ))}
                          </div>
                          {m.playingState && (
                            <div style={{ fontSize: 11.5, color: "var(--ink-faint)", marginTop: 2 }}>{m.playingState}</div>
                          )}
                        </div>
                      </div>
                    </td>
                    <td>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                        {m.is_bot_admin && <span className="ed-tag ed-tag--gold">管理员</span>}
                        {m.roleName && <span className="ed-tag">{m.roleName}</span>}
                        {!m.is_bot_admin && !m.roleName && "—"}
                      </div>
                    </td>
                    <td>
                      <span className={`ed-tag ${m.online ? "ed-tag--ok" : "ed-tag--muted"}`}>
                        {m.online ? "在线" : "离线"}
                      </span>
                    </td>
                    <td>
                      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                        <EdButton size="sm" variant="default" onClick={() => openDetail(m.uid)}>详情</EdButton>
                        <EdButton size="sm" variant="ghost" onClick={() => doMute(m.uid)}>禁言</EdButton>
                        <EdButton size="sm" variant="danger" onClick={() => doKick(m.uid)}>踢出</EdButton>
                      </div>
                    </td>
                  </motion.tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        <div style={{ padding: "12px 24px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ display: "flex", gap: 6 }}>
            <EdButton size="sm" variant="ghost" disabled={offset < step} onClick={() => { const next = Math.max(0, offset - step); setOffset(next); loadMembers(currentArea, keyword, next); }}>上一页</EdButton>
            <EdButton size="sm" variant="ghost" disabled={offset + step >= total} onClick={() => { const next = offset + step; setOffset(next); loadMembers(currentArea, keyword, next); }}>下一页</EdButton>
          </div>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--ink-faint)" }}>
            {page} / {pages}
          </span>
        </div>
      </section>

      <section className="ed-cell">
        <div className="ed-label" style={{ marginBottom: 16 }}>
          <span>发送消息 / 公告</span>
        </div>
        <div className="ed-form-grid" style={{ marginBottom: 12 }}>
          <div className="ed-field">
            <label className="ed-field__label">目标域</label>
            <EditorialSelect
              value={sendArea}
              onChange={(a) => { setSendArea(a); setSendChannel(""); loadChannels(a); }}
              options={areas.map((a) => ({ value: a.id, label: a.name || a.id }))}
            />
          </div>
          <div className="ed-field">
            <label className="ed-field__label">目标频道</label>
            <EditorialSelect
              value={sendChannel}
              onChange={setSendChannel}
              options={channelOpts}
              placeholder="选择频道..."
            />
          </div>
        </div>
        <textarea
          className="ed-textarea"
          rows={3}
          value={sendText}
          onChange={(e) => setSendText(e.target.value)}
          placeholder="输入消息内容，支持 Markdown..."
        />
        <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
          <EdButton size="sm" variant="default" onClick={() => sendMsg(false)}>发送消息</EdButton>
          <EdButton size="sm" variant="primary" onClick={() => sendMsg(true)}>发送公告</EdButton>
          <EdButton size="sm" variant="ghost" onClick={() => loadChannels(sendArea)}>刷新频道</EdButton>
        </div>
      </section>

      {/* Member Detail SlideSheet */}
      <SlideSheet
        open={!!detailUid}
        title={detailData?.person?.name || "成员详情"}
        onClose={() => setDetailUid(null)}
      >
        {detailLoading || !detailData ? (
          <div className="ed-empty">LOADING...</div>
        ) : (
          <div style={{ display: "grid", gap: 20 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 16, paddingBottom: 18, borderBottom: "1px solid var(--rule)" }}>
              {detailData.person?.avatar && (
                <img src={detailData.person.avatar} alt="" style={{ width: 64, height: 64, borderRadius: "50%", objectFit: "cover" }} />
              )}
              <div>
                <div style={{ fontSize: 18, fontWeight: 600 }}>{detailData.person?.name || detailUid}</div>
                <div style={{ fontFamily: "var(--font-mono)", fontSize: 11.5, color: "var(--ink-faint)", marginTop: 3 }}>
                  UID: {detailUid}
                </div>
                <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
                  <span className={`ed-tag ${detailData.person?.online ? "ed-tag--ok" : "ed-tag--muted"}`}>
                    {detailData.person?.online ? "在线" : "离线"}
                  </span>
                  {detailData.is_bot_admin && <span className="ed-tag ed-tag--gold">Bot 管理员</span>}
                  {detailData.muted && <span className="ed-tag ed-tag--err">禁言中</span>}
                  {detailData.mic_muted && <span className="ed-tag ed-tag--err">禁麦中</span>}
                </div>
              </div>
            </div>

            <div className="ed-grid ed-grid--2">
              <div style={{ padding: 14, borderRadius: 14, background: "rgba(255,255,255,0.04)", border: "1px solid var(--rule)" }}>
                <div className="ed-label"><span>近 7 天消息</span></div>
                <div className="ed-num-md">{detailData.messages_7d || 0}</div>
              </div>
              <div style={{ padding: 14, borderRadius: 14, background: "rgba(255,255,255,0.04)", border: "1px solid var(--rule)" }}>
                <div className="ed-label"><span>PID</span></div>
                <div style={{ fontFamily: "var(--font-mono)", marginTop: 10 }}>{detailData.person?.pid || "-"}</div>
              </div>
            </div>

            <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              <EdButton size="sm" variant={detailData.is_bot_admin ? "danger" : "primary"} onClick={() => doAdminToggle(detailUid!, !detailData.is_bot_admin)}>
                {detailData.is_bot_admin ? "撤销管理员" : "设为管理员"}
              </EdButton>
              {detailData.muted ? (
                <EdButton size="sm" variant="ghost" onClick={() => moderate(detailUid!, "unmute", "解除禁言")}>解除禁言</EdButton>
              ) : (
                <EdButton size="sm" variant="ghost" onClick={() => doMute(detailUid!)}>禁言</EdButton>
              )}
              {detailData.mic_muted ? (
                <EdButton size="sm" variant="ghost" onClick={() => moderate(detailUid!, "unmute-mic", "解除禁麦")}>解除禁麦</EdButton>
              ) : (
                <EdButton size="sm" variant="ghost" onClick={() => doMuteMic(detailUid!)}>禁麦</EdButton>
              )}
              <EdButton size="sm" variant="danger" onClick={() => doKick(detailUid!)}>踢出</EdButton>
              <EdButton size="sm" variant="danger" onClick={() => doBlock(detailUid!)}>封禁</EdButton>
            </div>

            {Array.isArray(detailData.assignable_roles) && detailData.assignable_roles.length > 0 && (
              <div>
                <div className="ed-label" style={{ marginBottom: 10 }}>
                  <span>身份组</span>
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                  {detailData.assignable_roles.map((r: any) => {
                    const rid = Number(r.roleID || r.id);
                    const owned = (detailData.roles || []).some((ur: any) => Number(ur.roleID || ur.id) === rid);
                    return (
                      <EdButton
                        key={rid}
                        size="sm"
                        variant={owned ? "primary" : "ghost"}
                        onClick={() => doRole(detailUid!, rid, owned ? "remove" : "add")}
                      >
                        {r.name || rid} {owned ? "×" : "+"}
                      </EdButton>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        )}
      </SlideSheet>

      {/* Duration Picker Modal */}
      <SlideSheet
        open={!!durPicker}
        title={durPicker?.mode === "mic" ? "选择禁麦时长" : "选择禁言时长"}
        onClose={() => { durPicker?.resolve(0); setDurPicker(null); }}
      >
        <div className="ed-grid ed-grid--3">
          {MUTE_DURATIONS.map((d) => (
            <button
              key={d.sec}
              type="button"
              style={{
                padding: "20px 12px",
                border: "1px solid var(--rule)",
                borderRadius: 14,
                background: "rgba(255,255,255,0.05)",
                color: "var(--ink)",
                cursor: "pointer",
              }}
              onClick={() => {
                const fn = durPicker?.resolve;
                setDurPicker(null);
                fn?.(d.sec);
              }}
            >
              <div style={{ fontSize: 28, fontWeight: 300 }}>{d.label}</div>
              <div style={{ fontSize: 11.5, color: "var(--ink-faint)", marginTop: 4 }}>{d.unit}</div>
            </button>
          ))}
        </div>
      </SlideSheet>

      {/* Cross-area Picker */}
      <SlideSheet
        open={!!areaPicker}
        title="选择目标域"
        onClose={() => { areaPicker?.resolve(""); setAreaPicker(null); }}
      >
        <div style={{ display: "grid", gap: 8 }}>
          {(areaPicker?.list || []).map((a) => (
            <EdButton
              key={a.areaId}
              variant="ghost"
              onClick={() => {
                const fn = areaPicker?.resolve;
                setAreaPicker(null);
                fn?.(a.areaId);
              }}
            >
              {a.areaName || a.areaId}
            </EdButton>
          ))}
        </div>
      </SlideSheet>
    </div>
  );
}
