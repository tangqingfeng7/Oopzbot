import React, { useCallback, useEffect, useState } from "react";
import { EdButton } from "../components/EditorialPrimitives";
import { apiReq } from "../lib/api";
import { useApp } from "../lib/context";

interface SongItem {
  id?: string | number;
  index?: number;
  name?: string;
  artists?: string;
  album?: string;
  durationText?: string;
  [k: string]: any;
}

interface MusicAreaInfo {
  area?: string;
  default_area?: string;
  active_area?: string;
  source?: string;
  source_text?: string;
}

export function MusicPage() {
  const { setStatus, toast, confirm } = useApp();
  const [kw, setKw] = useState("");
  const [activeKw, setActiveKw] = useState("");
  const [searchResults, setSearchResults] = useState<SongItem[]>([]);
  const [searchPage, setSearchPage] = useState(1);
  const [searchPages, setSearchPages] = useState(1);
  const [searchTotal, setSearchTotal] = useState(0);

  const [current, setCurrent] = useState<SongItem | null>(null);
  const [queue, setQueue] = useState<SongItem[]>([]);
  const [queuePage, setQueuePage] = useState(1);
  const [queuePages, setQueuePages] = useState(1);
  const [queueTotal, setQueueTotal] = useState(0);
  const [areaInfo, setAreaInfo] = useState<MusicAreaInfo>({});

  const loadQueue = useCallback(async (page = queuePage) => {
    try {
      const data = await apiReq<any>(`/admin/api/queue?page=${page}&page_size=10`);
      setAreaInfo(data.music_area || {});
      setCurrent(data.current || null);
      setQueue(data.queue || []);
      setQueuePage(data.page || 1);
      setQueuePages(data.pages || 1);
      setQueueTotal(data.total || 0);
      setStatus("队列已同步", "success");
    } catch (e: any) {
      setStatus("队列同步失败", "error");
      toast(e.message || "加载队列失败", "error");
    }
  }, [queuePage, setStatus, toast]);

  useEffect(() => {
    loadQueue(1);
  }, []);

  const control = async (action: string) => {
    try {
      await apiReq("/admin/api/control", { method: "POST", body: JSON.stringify({ action }) });
      toast(`已执行：${action}`, "success");
      await loadQueue(queuePage);
    } catch (e: any) {
      toast(e.message || "控制失败", "error");
    }
  };

  const clearQueue = async () => {
    const ok = await confirm("清空队列", "确认清空当前音乐域的全部待播队列？", { okText: "确认清空" });
    if (!ok) return;
    try {
      await apiReq("/admin/api/queue/clear", { method: "POST", body: "{}" });
      toast("队列已清空", "warning");
      await loadQueue(1);
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  const queueAction = async (action: string, index: number) => {
    try {
      await apiReq("/admin/api/queue/action", { method: "POST", body: JSON.stringify({ action, index }) });
      toast(action === "top" ? "已置顶" : "已移除", "success");
      await loadQueue(queuePage);
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  const searchSongs = async (keyword: string, page: number) => {
    const clean = keyword.trim();
    if (!clean) {
      toast("请输入关键词", "warning");
      return;
    }
    try {
      const data = await apiReq<any>(
        `/admin/api/search?keyword=${encodeURIComponent(clean)}&page=${page}&page_size=10`
      );
      setActiveKw(clean);
      setSearchResults(data.results || []);
      setSearchPage(data.page || 1);
      setSearchPages(data.pages || 1);
      setSearchTotal(data.total || 0);
    } catch (e: any) {
      toast(e.message || "搜索失败", "error");
    }
  };

  const addSong = async (song: SongItem) => {
    try {
      const data = await apiReq<any>("/admin/api/add", { method: "POST", body: JSON.stringify(song) });
      toast(`已加入队列：${data.name || song.name}`, "success");
      await loadQueue(queuePage);
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  return (
    <div className="ed-chapter">
      <div className="ed-chapter-bar">
        <div className="ed-chapter-bar__left">
          <h2 className="ed-chapter-bar__title">音乐</h2>
        </div>
        <div className="ed-chapter-bar__actions">
          <EdButton size="sm" variant="ghost" onClick={() => control("pause")}>暂停</EdButton>
          <EdButton size="sm" variant="ghost" onClick={() => control("resume")}>恢复</EdButton>
          <EdButton size="sm" variant="primary" onClick={() => control("next")}>下一首</EdButton>
          <EdButton size="sm" variant="danger" onClick={() => control("stop")}>停止</EdButton>
          <EdButton size="sm" variant="danger" onClick={clearQueue}>清空队列</EdButton>
          <EdButton size="sm" variant="ghost" onClick={() => loadQueue(queuePage)}>刷新</EdButton>
        </div>
      </div>

      <div
        className="ed-cell"
        style={{
          padding: "13px 20px",
          display: "flex",
          flexWrap: "wrap",
          gap: "10px 22px",
          alignItems: "center",
          fontSize: 12.5,
          color: "var(--ink-faint)",
        }}
      >
        <span className={`ed-tag ${areaInfo.source === "none" ? "ed-tag--err" : "ed-tag--gold"}`}>
          来源：{areaInfo.source_text || "未解析"}
        </span>
        <span>音乐域：<strong style={{ color: "var(--ink-soft)", fontWeight: 500 }}>{areaInfo.area || "-"}</strong></span>
        <span>默认域：<strong style={{ color: "var(--ink-soft)", fontWeight: 500 }}>{areaInfo.default_area || "-"}</strong></span>
        <span>活跃域：<strong style={{ color: "var(--ink-soft)", fontWeight: 500 }}>{areaInfo.active_area || "-"}</strong></span>
      </div>

      <div className="ed-grid ed-grid--2" style={{ flex: 1 }}>
        <section className="ed-cell ed-cell--flush" style={{ display: "flex", flexDirection: "column" }}>
          <div style={{ padding: "18px 22px", borderBottom: "1px solid var(--rule)" }}>
            <div className="ed-label" style={{ marginBottom: 12 }}>
              <span>后台点歌</span>
            </div>
            <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
              <input
                className="ed-input"
                value={kw}
                onChange={(e) => setKw(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") searchSongs(kw, 1); }}
                placeholder="输入歌名或歌手，回车搜索..."
              />
              <EdButton variant="primary" size="sm" onClick={() => searchSongs(kw, 1)}>搜索</EdButton>
            </div>
          </div>

          <div className="ed-table-wrap" style={{ flex: 1 }}>
            <table className="ed-table">
              <thead>
                <tr>
                  <th style={{ width: "34%" }}>歌曲</th>
                  <th style={{ width: "24%" }}>歌手</th>
                  <th style={{ width: "22%" }}>专辑</th>
                  <th style={{ width: "20%" }}>操作</th>
                </tr>
              </thead>
              <tbody>
                {searchResults.length === 0 ? (
                  <tr><td colSpan={4} className="ed-empty">输入关键词开始检索</td></tr>
                ) : (
                  searchResults.map((item, idx) => (
                    <tr key={`${item.id ?? idx}-${idx}`}>
                      <td style={{ color: "var(--ink)", fontWeight: 500 }}>{item.name || "-"}</td>
                      <td>{item.artists || "-"}</td>
                      <td>{item.album || "-"}</td>
                      <td>
                        <EdButton size="sm" variant="primary" onClick={() => addSong(item)}>加入</EdButton>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          <div
            style={{
              padding: "12px 24px",
              borderTop: "1px solid var(--rule)",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <div style={{ display: "flex", gap: 6 }}>
              <EdButton
                size="sm"
                variant="ghost"
                disabled={searchPage <= 1 || !activeKw}
                onClick={() => searchSongs(activeKw, searchPage - 1)}
              >
                上一页
              </EdButton>
              <EdButton
                size="sm"
                variant="ghost"
                disabled={searchPage >= searchPages || !activeKw}
                onClick={() => searchSongs(activeKw, searchPage + 1)}
              >
                下一页
              </EdButton>
            </div>
            <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--ink-faint)" }}>
              {activeKw ? `${searchPage} / ${searchPages} · ${searchTotal} 条` : "—"}
            </span>
          </div>
        </section>

        <section className="ed-cell ed-cell--flush" style={{ display: "flex", flexDirection: "column" }}>
          <div style={{ padding: "18px 22px", borderBottom: "1px solid var(--rule)" }}>
            <div className="ed-label">
              <span>播放队列</span>
            </div>
          </div>

          <div className="ed-table-wrap" style={{ flex: 1 }}>
            <table className="ed-table">
              <thead>
                <tr>
                  <th style={{ width: "10%" }}>#</th>
                  <th style={{ width: "32%" }}>歌曲</th>
                  <th style={{ width: "22%" }}>歌手</th>
                  <th style={{ width: "13%" }}>时长</th>
                  <th style={{ width: "23%" }}>操作</th>
                </tr>
              </thead>
              <tbody>
                {current && (
                  <tr className="is-current">
                    <td style={{ fontFamily: "var(--font-mono)", color: "var(--gold)", fontSize: 11 }}>NOW</td>
                    <td style={{ color: "var(--ink)", fontWeight: 600 }}>{current.name || "-"}</td>
                    <td>{current.artists || "-"}</td>
                    <td style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}>{current.durationText || "-"}</td>
                    <td><span className="ed-tag ed-tag--gold">正在播放</span></td>
                  </tr>
                )}
                {queue.map((item, i) => (
                  <tr key={`${item.index ?? i}-${item.name}`}>
                    <td style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}>{item.index ?? i + 1}</td>
                    <td style={{ color: "var(--ink)" }}>{item.name || "-"}</td>
                    <td>{item.artists || "-"}</td>
                    <td style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}>{item.durationText || "-"}</td>
                    <td>
                      <div style={{ display: "flex", gap: 6 }}>
                        <EdButton size="sm" variant="ghost" onClick={() => queueAction("top", Number(item.index))}>置顶</EdButton>
                        <EdButton size="sm" variant="danger" onClick={() => queueAction("remove", Number(item.index))}>删除</EdButton>
                      </div>
                    </td>
                  </tr>
                ))}
                {!current && queue.length === 0 && (
                  <tr><td colSpan={5} className="ed-empty">当前队列为空</td></tr>
                )}
              </tbody>
            </table>
          </div>

          <div
            style={{
              padding: "12px 24px",
              borderTop: "1px solid var(--rule)",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <div style={{ display: "flex", gap: 6 }}>
              <EdButton size="sm" variant="ghost" disabled={queuePage <= 1} onClick={() => loadQueue(queuePage - 1)}>
                上一页
              </EdButton>
              <EdButton size="sm" variant="ghost" disabled={queuePage >= queuePages} onClick={() => loadQueue(queuePage + 1)}>
                下一页
              </EdButton>
            </div>
            <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--ink-faint)" }}>
              {queuePage} / {queuePages} · {queueTotal} 首
            </span>
          </div>
        </section>
      </div>
    </div>
  );
}
