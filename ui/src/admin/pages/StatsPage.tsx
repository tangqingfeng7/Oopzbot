import React, { useCallback, useEffect, useState } from "react";
import { AnimatedNumber, EdButton } from "../components/EditorialPrimitives";
import { apiReq } from "../lib/api";
import { useApp } from "../lib/context";

interface TopSong {
  song_name?: string;
  artist?: string;
  play_count?: number;
  last_played_at?: string;
}

export function StatsPage() {
  const { setStatus, toast, confirm } = useApp();
  const [songs, setSongs] = useState<TopSong[]>([]);
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);
  const [total, setTotal] = useState(0);

  const loadTop = useCallback(async (targetPage = page) => {
    try {
      const data = await apiReq<any>(`/admin/api/statistics?days=7&top_page=${targetPage}&top_page_size=12`);
      setSongs(data.top_songs || []);
      setPage(data.top_page || 1);
      setPages(data.top_pages || 1);
      setTotal(data.top_total || 0);
      setStatus("统计已同步", "success");
    } catch (e: any) {
      setStatus("加载失败", "error");
      toast(e.message, "error");
    }
  }, [page, setStatus, toast]);

  useEffect(() => {
    loadTop(1);
  }, []);

  const clearHistory = async () => {
    const ok = await confirm("清空播放历史", "确认永久删除全部播放历史记录？此操作不可撤销。", { okText: "确认清空" });
    if (!ok) return;
    try {
      const res = await apiReq<any>("/admin/api/statistics/clear_history", { method: "POST", body: "{}" });
      toast(`已清理 ${res.deleted || 0} 条记录`, "warning");
      await loadTop(1);
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  const leaderCount = songs.length ? Number(songs[0].play_count || 0) : 0;

  return (
    <div className="ed-chapter">
      <div className="ed-chapter-bar">
        <div className="ed-chapter-bar__left">
          <h2 className="ed-chapter-bar__title">统计</h2>
        </div>
        <div className="ed-chapter-bar__actions">
          <EdButton size="sm" variant="ghost" onClick={() => loadTop(page)}>刷新</EdButton>
          <EdButton size="sm" variant="danger" onClick={clearHistory}>清空历史</EdButton>
        </div>
      </div>

      <div className="ed-grid ed-grid--3">
        <div className="ed-cell">
          <div className="ed-label"><span>上榜歌曲</span></div>
          <div className="ed-num-lg"><AnimatedNumber value={total} /></div>
        </div>
        <div className="ed-cell">
          <div className="ed-label"><span>页码</span></div>
          <div className="ed-num-lg">{page} <span style={{ color: "var(--ink-ghost)" }}>/ {pages}</span></div>
        </div>
        <div className="ed-cell">
          <div className="ed-label"><span>榜首播放</span></div>
          <div className="ed-num-lg"><AnimatedNumber value={leaderCount} /></div>
        </div>
      </div>

      <section className="ed-cell ed-cell--flush" style={{ flex: 1 }}>
        <div className="ed-table-wrap">
          <table className="ed-table">
            <thead>
              <tr>
                <th style={{ width: "8%" }}>NO.</th>
                <th style={{ width: "36%" }}>歌曲</th>
                <th style={{ width: "24%" }}>歌手</th>
                <th style={{ width: "12%" }}>次数</th>
                <th style={{ width: "20%" }}>最后播放</th>
              </tr>
            </thead>
            <tbody>
              {songs.length === 0 ? (
                <tr><td colSpan={5} className="ed-empty">暂无统计数据</td></tr>
              ) : (
                songs.map((item, i) => {
                  const rank = (page - 1) * 12 + i + 1;
                  return (
                    <tr key={`${item.song_name}-${i}`}>
                      <td>
                        <span className={`ed-rank-num${rank <= 3 ? " ed-rank-num--top" : ""}`}>
                          {String(rank).padStart(2, "0")}
                        </span>
                      </td>
                      <td style={{ color: "var(--ink)", fontWeight: 500 }}>{item.song_name || "-"}</td>
                      <td>{item.artist || "-"}</td>
                      <td style={{ fontFamily: "var(--font-mono)", color: "var(--ink)" }}>{item.play_count || 0}</td>
                      <td style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}>{item.last_played_at || "-"}</td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        <div
          style={{
            padding: "14px 24px",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <div style={{ display: "flex", gap: 6 }}>
            <EdButton size="sm" variant="ghost" disabled={page <= 1} onClick={() => loadTop(page - 1)}>上一页</EdButton>
            <EdButton size="sm" variant="ghost" disabled={page >= pages} onClick={() => loadTop(page + 1)}>下一页</EdButton>
          </div>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--ink-faint)" }}>
            第 {page} / {pages} 页 · 共 {total} 首
          </span>
        </div>
      </section>
    </div>
  );
}
