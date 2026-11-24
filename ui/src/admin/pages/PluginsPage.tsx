import React, { useCallback, useEffect, useState } from "react";
import { AnimatedNumber, EdButton, EditorialSelect, SlideSheet, ToggleSwitch } from "../components/EditorialPrimitives";
import { apiReq } from "../lib/api";
import { useApp } from "../lib/context";

interface LoadedPlugin {
  name: string;
  description?: string;
  version?: string;
  builtin?: boolean;
  mention_prefixes?: string[];
  slash_commands?: string[];
}

function SchemaFields({
  schema,
  value,
  onChange,
}: {
  schema: Record<string, any>;
  value: Record<string, any>;
  onChange: (next: Record<string, any>) => void;
}) {
  const props = schema?.properties;
  if (!props || typeof props !== "object") {
    return null;
  }

  return (
    <div style={{ display: "grid", gap: 14 }}>
      {Object.entries(props).map(([key, rawMeta]) => {
        const meta = (rawMeta || {}) as Record<string, any>;
        const fieldType = Array.isArray(meta.type) ? meta.type.find((t: string) => t !== "null") : meta.type;
        const label = meta.title || key;
        const cur = value?.[key];

        if (fieldType === "object" && meta.properties) {
          return (
            <fieldset key={key} style={{ border: "1px solid var(--rule)", padding: 16, margin: 0 }}>
              <legend style={{ padding: "0 8px", fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--gold)" }}>
                {label}
              </legend>
              <SchemaFields
                schema={meta}
                value={typeof cur === "object" && cur !== null ? cur : {}}
                onChange={(sub) => onChange({ ...value, [key]: sub })}
              />
            </fieldset>
          );
        }

        if (fieldType === "boolean") {
          return (
            <div key={key} className="ed-switch-row">
              <div>
                <div className="ed-field__label">{label}</div>
                {meta.description && <div style={{ fontSize: 11.5, color: "var(--ink-faint)" }}>{meta.description}</div>}
              </div>
              <ToggleSwitch checked={!!cur} onChange={(v) => onChange({ ...value, [key]: v })} />
            </div>
          );
        }

        if (Array.isArray(meta.enum) && meta.enum.length > 0) {
          return (
            <div key={key} className="ed-field">
              <label className="ed-field__label">{label}</label>
              <EditorialSelect
                value={String(cur ?? "")}
                onChange={(v) => onChange({ ...value, [key]: v })}
                options={meta.enum.map((opt: any) => ({ value: String(opt), label: String(opt) }))}
              />
            </div>
          );
        }

        if (fieldType === "integer" || fieldType === "number") {
          return (
            <div key={key} className="ed-field">
              <label className="ed-field__label">{label}</label>
              <input
                className="ed-input"
                type="number"
                value={cur ?? ""}
                onChange={(e) => {
                  const n = e.target.value === "" ? "" : Number(e.target.value);
                  onChange({ ...value, [key]: Number.isFinite(n as number) ? n : e.target.value });
                }}
              />
            </div>
          );
        }

        if (fieldType === "array" || fieldType === "object") {
          return (
            <div key={key} className="ed-field">
              <label className="ed-field__label">{label}</label>
              <textarea
                className="ed-textarea ed-input--mono"
                rows={4}
                value={typeof cur === "string" ? cur : JSON.stringify(cur ?? (fieldType === "array" ? [] : {}), null, 2)}
                onChange={(e) => {
                  try {
                    onChange({ ...value, [key]: JSON.parse(e.target.value) });
                  } catch {
                    onChange({ ...value, [key]: e.target.value });
                  }
                }}
              />
            </div>
          );
        }

        const isSecret = /password|secret|token|cookie|key/i.test(key);
        return (
          <div key={key} className="ed-field">
            <label className="ed-field__label">{label}</label>
            <input
              className="ed-input"
              type={isSecret ? "password" : "text"}
              value={cur ?? ""}
              onChange={(e) => onChange({ ...value, [key]: e.target.value })}
            />
          </div>
        );
      })}
    </div>
  );
}

export function PluginsPage() {
  const { setStatus, toast, confirm, refreshPluginNav } = useApp();
  const [loaded, setLoaded] = useState<LoadedPlugin[]>([]);
  const [available, setAvailable] = useState<string[]>([]);

  const [editName, setEditName] = useState<string | null>(null);
  const [editSchema, setEditSchema] = useState<Record<string, any> | null>(null);
  const [editObj, setEditObj] = useState<Record<string, any>>({});
  const [rawJson, setRawJson] = useState("{}");

  const loadPlugins = useCallback(async () => {
    try {
      const data = await apiReq<any>("/admin/api/plugins");
      setLoaded(data.loaded || []);
      setAvailable(data.available || []);
      setStatus("已同步", "success");
    } catch (e: any) {
      setStatus("加载失败", "error");
      toast(e.message, "error");
    }
  }, [setStatus, toast]);

  useEffect(() => {
    loadPlugins();
  }, [loadPlugins]);

  const loadOne = async (name: string) => {
    try {
      await apiReq(`/admin/api/plugins/${encodeURIComponent(name)}/load`, { method: "POST", body: "{}" });
      toast(`已加载：${name}`, "success");
      await Promise.all([loadPlugins(), refreshPluginNav()]);
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  const unloadOne = async (name: string) => {
    const ok = await confirm("卸载插件", `确认卸载插件「${name}」？`, { okText: "确认卸载" });
    if (!ok) return;
    try {
      await apiReq(`/admin/api/plugins/${encodeURIComponent(name)}/unload`, { method: "POST", body: "{}" });
      toast(`已卸载：${name}`, "warning");
      await Promise.all([loadPlugins(), refreshPluginNav()]);
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  const reloadOne = async (name: string) => {
    try {
      await apiReq(`/admin/api/plugins/${encodeURIComponent(name)}/reload-config`, { method: "POST", body: "{}" });
      toast(`配置已重载：${name}`, "success");
    } catch (e: any) {
      toast(e.message, "error");
    }
  };

  const openEditor = async (name: string) => {
    setEditName(name);
    setEditSchema(null);
    setEditObj({});
    setRawJson("加载中...");
    try {
      const data = await apiReq<any>(`/admin/api/plugins/${encodeURIComponent(name)}/config`);
      const cfg = data.config || {};
      setEditSchema(data.schema || null);
      setEditObj(cfg);
      setRawJson(JSON.stringify(cfg, null, 2));
    } catch (e: any) {
      setRawJson("{}");
      toast(`读取失败：${e.message}`, "error");
    }
  };

  const saveEditor = async () => {
    if (!editName) return;
    let parsed: Record<string, any>;
    try {
      parsed = JSON.parse(rawJson);
    } catch (e: any) {
      toast(`JSON 格式无效：${e.message}`, "error");
      return;
    }
    try {
      const res = await apiReq<any>(`/admin/api/plugins/${encodeURIComponent(editName)}/config`, {
        method: "POST",
        body: JSON.stringify({ config: parsed }),
      });
      toast(res.reload ? `已保存 (${res.reload})` : "插件配置已保存", "success");
      setEditName(null);
    } catch (e: any) {
      toast(`保存失败：${e.message}`, "error");
    }
  };

  return (
    <div className="ed-chapter">
      <div className="ed-chapter-bar">
        <div className="ed-chapter-bar__left">
          <h2 className="ed-chapter-bar__title">插件</h2>
        </div>
        <div className="ed-chapter-bar__actions">
          <EdButton size="sm" variant="ghost" onClick={loadPlugins}>刷新</EdButton>
        </div>
      </div>

      <div className="ed-grid ed-grid--2">
        <div className="ed-cell">
          <div className="ed-label"><span>已加载</span></div>
          <div className="ed-num-lg"><AnimatedNumber value={loaded.length} /></div>
        </div>
        <div className="ed-cell">
          <div className="ed-label"><span>可加载</span></div>
          <div className="ed-num-lg"><AnimatedNumber value={available.length} /></div>
        </div>
      </div>

      <section className="ed-cell ed-cell--flush">
        <div className="ed-cell-head">
          <div className="ed-label"><span>已加载插件</span></div>
        </div>
        <div className="ed-table-wrap">
          <table className="ed-table">
            <thead>
              <tr>
                <th style={{ width: "16%" }}>名称</th>
                <th style={{ width: "25%" }}>描述</th>
                <th style={{ width: "8%" }}>版本</th>
                <th style={{ width: "8%" }}>类型</th>
                <th style={{ width: "19%" }}>命令</th>
                <th style={{ width: "24%" }}>操作</th>
              </tr>
            </thead>
            <tbody>
              {loaded.length === 0 ? (
                <tr><td colSpan={6} className="ed-empty">暂无已加载插件</td></tr>
              ) : (
                loaded.map((p) => {
                  const cmds = [
                    ...(p.mention_prefixes || []),
                    ...(p.slash_commands || []).map((c) => (c.startsWith("/") ? c : `/${c}`)),
                  ];
                  return (
                    <tr key={p.name}>
                      <td style={{ fontFamily: "var(--font-mono)", color: "var(--ink)", fontWeight: 500 }}>{p.name}</td>
                      <td>{p.description || "-"}</td>
                      <td style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}>{p.version || "-"}</td>
                      <td>
                        <span className={`ed-tag ${p.builtin ? "ed-tag--gold" : "ed-tag--ok"}`}>
                          {p.builtin ? "内置" : "扩展"}
                        </span>
                      </td>
                      <td>
                        <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                          {cmds.length ? cmds.map((c) => <span key={c} className="ed-tag">{c}</span>) : "—"}
                        </div>
                      </td>
                      <td>
                        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                          {!p.builtin && <EdButton size="sm" variant="danger" onClick={() => unloadOne(p.name)}>卸载</EdButton>}
                          <EdButton size="sm" variant="ghost" onClick={() => reloadOne(p.name)}>重载</EdButton>
                          <EdButton size="sm" variant="default" onClick={() => openEditor(p.name)}>配置</EdButton>
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

      {available.length > 0 && (
        <section className="ed-cell ed-cell--flush">
          <div className="ed-cell-head">
            <div className="ed-label"><span>可加载插件</span></div>
          </div>
          <div className="ed-table-wrap">
            <table className="ed-table">
              <thead>
                <tr>
                  <th>插件名称</th>
                  <th style={{ width: 160 }}>操作</th>
                </tr>
              </thead>
              <tbody>
                {available.map((name) => (
                  <tr key={name}>
                    <td style={{ fontFamily: "var(--font-mono)", color: "var(--ink)" }}>{name}</td>
                    <td>
                      <EdButton size="sm" variant="primary" onClick={() => loadOne(name)}>加载</EdButton>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <SlideSheet
        open={!!editName}
        wide
        title={`配置 · ${editName || ""}`}
        onClose={() => setEditName(null)}
        footer={
          <>
            <EdButton variant="ghost" onClick={() => setEditName(null)}>取消</EdButton>
            <EdButton variant="primary" onClick={saveEditor}>保存并重载</EdButton>
          </>
        }
      >
        {editSchema?.properties && (
          <div style={{ marginBottom: 20 }}>
            <SchemaFields
              schema={editSchema}
              value={editObj}
              onChange={(next) => {
                setEditObj(next);
                setRawJson(JSON.stringify(next, null, 2));
              }}
            />
          </div>
        )}
        <details open={!editSchema?.properties} style={{ border: "1px solid var(--rule)", borderRadius: 14, padding: 14 }}>
          <summary style={{ cursor: "pointer", fontSize: 12.5, fontWeight: 500, color: "var(--ink-soft)" }}>
            原始 JSON
          </summary>
          <textarea
            className="ed-textarea ed-input--mono"
            style={{ marginTop: 12, minHeight: 240 }}
            spellCheck={false}
            value={rawJson}
            onChange={(e) => {
              setRawJson(e.target.value);
              try {
                const parsed = JSON.parse(e.target.value);
                if (parsed && typeof parsed === "object") setEditObj(parsed);
              } catch {
                // editing in progress
              }
            }}
          />
        </details>
      </SlideSheet>
    </div>
  );
}
