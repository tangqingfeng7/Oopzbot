import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion, useSpring } from "framer-motion";
import { Check, ChevronDown, Search, X } from "lucide-react";
import type { AreaItem, NavItem } from "../lib/api";

/* ---------- Smooth Rolling Number ---------- */

export function AnimatedNumber({ value, className }: { value: number; className?: string }) {
  const spring = useSpring(value, { stiffness: 130, damping: 24, mass: 0.75 });
  const [display, setDisplay] = useState(() => new Intl.NumberFormat("zh-CN").format(value));

  useEffect(() => {
    spring.set(value);
  }, [spring, value]);

  useEffect(() => {
    return spring.on("change", (latest) => {
      const rounded = Number.isInteger(value) ? Math.round(latest) : Number(latest.toFixed(2));
      setDisplay(new Intl.NumberFormat("zh-CN").format(rounded));
    });
  }, [spring, value]);

  return <span className={className}>{display}</span>;
}

/* ---------- Action Button (with automatic async loading state) ---------- */

interface EdButtonProps extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "onClick"> {
  variant?: "default" | "primary" | "ghost" | "danger";
  size?: "md" | "sm";
  onClick?: (e: React.MouseEvent<HTMLButtonElement>) => void | Promise<unknown>;
}

export function EdButton({
  variant = "default",
  size = "md",
  className = "",
  disabled,
  onClick,
  children,
  type = "button",
  ...rest
}: EdButtonProps) {
  const [busy, setBusy] = useState(false);

  const handleClick = async (e: React.MouseEvent<HTMLButtonElement>) => {
    if (!onClick || busy || disabled) return;
    let settled = false;
    const timer = window.setTimeout(() => {
      if (!settled) setBusy(true);
    }, 90);
    try {
      await onClick(e);
    } finally {
      settled = true;
      window.clearTimeout(timer);
      setBusy(false);
    }
  };

  const cls = [
    "ed-btn",
    variant !== "default" ? `ed-btn--${variant}` : "",
    size === "sm" ? "ed-btn--sm" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <button type={type} className={cls} disabled={disabled || busy} onClick={handleClick} {...rest}>
      {busy && <span className="ed-spinner" aria-hidden="true" />}
      <span>{children}</span>
    </button>
  );
}

/* ---------- Pill Toggle Switch ---------- */

export function ToggleSwitch({
  checked,
  onChange,
  disabled,
  ariaLabel,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
  ariaLabel?: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabel}
      disabled={disabled}
      className={`ed-switch${checked ? " is-on" : ""}`}
      onClick={() => onChange(!checked)}
    >
      <motion.span
        layout
        transition={{ type: "spring", stiffness: 520, damping: 32 }}
        className="ed-switch__thumb"
      />
    </button>
  );
}

/* ---------- Custom Dropdown Select ---------- */

export interface SelectOption {
  value: string;
  label: string;
  group?: string;
}

export function EditorialSelect({
  value,
  options,
  onChange,
  placeholder = "请选择",
  disabled,
}: {
  value: string;
  options: SelectOption[];
  onChange: (val: string) => void;
  placeholder?: string;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [coords, setCoords] = useState<{ top: number; left: number; width: number; up: boolean } | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const updatePos = () => {
    const el = triggerRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const spaceBelow = window.innerHeight - rect.bottom;
    const up = spaceBelow < 220 && rect.top > spaceBelow;
    setCoords({
      top: up ? rect.top - 6 : rect.bottom + 6,
      left: rect.left,
      width: rect.width,
      up,
    });
  };

  useLayoutEffect(() => {
    if (!open) return;
    updatePos();
    const onReflow = () => updatePos();
    window.addEventListener("scroll", onReflow, true);
    window.addEventListener("resize", onReflow);
    return () => {
      window.removeEventListener("scroll", onReflow, true);
      window.removeEventListener("resize", onReflow);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      const target = e.target as Node;
      if (rootRef.current?.contains(target) || menuRef.current?.contains(target)) return;
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const current = options.find((o) => o.value === value);

  const groups: { name?: string; items: SelectOption[] }[] = [];
  for (const opt of options) {
    const last = groups[groups.length - 1];
    if (last && last.name === opt.group) {
      last.items.push(opt);
    } else {
      groups.push({ name: opt.group, items: [opt] });
    }
  }

  return (
    <div className="ed-select" ref={rootRef}>
      <button
        ref={triggerRef}
        type="button"
        className="ed-select-trigger"
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
      >
        <span className="ed-select-trigger__text">{current ? current.label : placeholder}</span>
        <ChevronDown
          size={15}
          style={{
            flexShrink: 0,
            transform: open ? "rotate(180deg)" : "rotate(0deg)",
            transition: "transform 0.2s cubic-bezier(0.22, 1, 0.36, 1)",
            opacity: 0.6,
          }}
        />
      </button>

      {typeof document !== "undefined" &&
        createPortal(
          <AnimatePresence>
            {open && coords && (
              <motion.div
                ref={menuRef}
                className="ed-select-menu"
                style={{
                  position: "fixed",
                  left: coords.left,
                  width: coords.width,
                  top: coords.up ? undefined : coords.top,
                  bottom: coords.up ? window.innerHeight - coords.top : undefined,
                  right: "auto",
                  zIndex: 1200,
                }}
                initial={{ opacity: 0, y: coords.up ? 6 : -6, scale: 0.98 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: coords.up ? 4 : -4, scale: 0.98 }}
                transition={{ duration: 0.16, ease: [0.22, 1, 0.36, 1] }}
              >
                {options.length === 0 ? (
                  <div className="ed-empty" style={{ padding: "14px" }}>无选项</div>
                ) : (
                  groups.map((grp, gi) => (
                    <React.Fragment key={grp.name || `g-${gi}`}>
                      {grp.name && <div className="ed-select-group">{grp.name}</div>}
                      {grp.items.map((opt) => (
                        <button
                          key={`${opt.value}-${opt.label}`}
                          type="button"
                          className={`ed-select-opt${opt.value === value ? " is-selected" : ""}`}
                          onClick={() => {
                            onChange(opt.value);
                            setOpen(false);
                          }}
                        >
                          <span>{opt.label}</span>
                          {opt.value === value && <Check size={14} />}
                        </button>
                      ))}
                    </React.Fragment>
                  ))
                )}
              </motion.div>
            )}
          </AnimatePresence>,
          document.body
        )}
    </div>
  );
}

/* ---------- Floating Side Sheet ---------- */

export function SlideSheet({
  open,
  title,
  wide,
  onClose,
  footer,
  children,
}: {
  open: boolean;
  title: string;
  wide?: boolean;
  onClose: () => void;
  footer?: React.ReactNode;
  children: React.ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (typeof document === "undefined") return null;

  return createPortal(
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            className="ed-backdrop-dim"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={onClose}
          />
          <motion.aside
            className={`ed-sheet${wide ? " ed-sheet--wide" : ""}`}
            initial={{ x: 40, opacity: 0, scale: 0.98 }}
            animate={{ x: 0, opacity: 1, scale: 1 }}
            exit={{ x: 32, opacity: 0, scale: 0.98 }}
            transition={{ type: "spring", stiffness: 400, damping: 34 }}
          >
            <header className="ed-sheet__head">
              <h3 style={{ margin: 0, fontSize: 16, fontWeight: 600, letterSpacing: "-0.02em" }}>{title}</h3>
              <button
                type="button"
                className="ed-sheet__close"
                onClick={onClose}
                aria-label="关闭"
              >
                <X size={15} />
              </button>
            </header>
            <div className="ed-sheet__body">{children}</div>
            {footer && <footer className="ed-sheet__foot">{footer}</footer>}
          </motion.aside>
        </>
      )}
    </AnimatePresence>,
    document.body
  );
}

/* ---------- Confirmation Dialog ---------- */

export interface ConfirmState {
  title: string;
  message: string;
  okText?: string;
  danger?: boolean;
  resolve: (ok: boolean) => void;
}

export function ConfirmDialog({ state }: { state: ConfirmState | null }) {
  useEffect(() => {
    if (!state) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") state.resolve(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [state]);

  return (
    <AnimatePresence>
      {state && (
        <>
          <motion.div
            className="ed-backdrop-dim"
            style={{ zIndex: 950 }}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => state.resolve(false)}
          />
          <motion.div
            className="ed-modal"
            role="dialog"
            aria-modal="true"
            initial={{ opacity: 0, x: "-50%", y: "-46%", scale: 0.94 }}
            animate={{ opacity: 1, x: "-50%", y: "-50%", scale: 1 }}
            exit={{ opacity: 0, x: "-50%", y: "-48%", scale: 0.95 }}
            transition={{ type: "spring", stiffness: 440, damping: 32 }}
          >
            <div className="ed-sheet__head">
              <h3 style={{ margin: 0, fontSize: 16, fontWeight: 600, letterSpacing: "-0.02em" }}>{state.title}</h3>
              <button
                type="button"
                className="ed-sheet__close"
                onClick={() => state.resolve(false)}
                aria-label="关闭"
              >
                <X size={15} />
              </button>
            </div>
            <div className="ed-sheet__body" style={{ fontSize: 14, color: "var(--ink-soft)", lineHeight: 1.65 }}>
              {state.message}
            </div>
            <div className="ed-sheet__foot">
              <EdButton variant="ghost" onClick={() => state.resolve(false)}>取消</EdButton>
              <EdButton
                variant={state.danger === false ? "primary" : "danger"}
                onClick={() => state.resolve(true)}
              >
                {state.okText || "确认"}
              </EdButton>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

/* ---------- Toast Notifications ---------- */

export interface ToastItem {
  id: number;
  text: string;
  kind: "info" | "success" | "warning" | "error";
}

export function ToastStack({ items, onDismiss }: { items: ToastItem[]; onDismiss: (id: number) => void }) {
  return (
    <div className="ed-toast-stack" aria-live="polite">
      <AnimatePresence initial={false}>
        {items.map((t) => (
          <motion.div
            key={t.id}
            layout
            className={`ed-toast ed-toast--${t.kind}`}
            initial={{ opacity: 0, y: 16, scale: 0.94 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 10, scale: 0.94 }}
            transition={{ type: "spring", stiffness: 420, damping: 30 }}
            onClick={() => onDismiss(t.id)}
          >
            <span className={`ed-live-dot ed-live-dot--${t.kind}`} />
            <span>{t.text}</span>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}

/* ---------- Quick Jump Palette (Ctrl+K) ---------- */

export function CommandPalette({
  open,
  navItems,
  onNavigate,
  onLogout,
  onClose,
}: {
  open: boolean;
  navItems: NavItem[];
  onNavigate: (key: string) => void;
  onLogout: () => void;
  onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  const [idx, setIdx] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const entries = [
    ...navItems.map((n) => ({
      id: n.key,
      label: n.label,
      code: n.code,
      run: () => onNavigate(n.key),
    })),
    {
      id: "__logout__",
      label: "退出登录",
      code: "LOGOUT",
      run: () => onLogout(),
    },
  ].filter((e) => {
    const q = query.trim().toLowerCase();
    return !q || e.label.toLowerCase().includes(q) || e.code.toLowerCase().includes(q);
  });

  useEffect(() => {
    if (open) {
      setQuery("");
      setIdx(0);
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  useEffect(() => {
    setIdx(0);
  }, [query]);

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            className="ed-backdrop-dim"
            style={{ zIndex: 960 }}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
          />
          <motion.div
            className="ed-cmdk"
            initial={{ opacity: 0, x: "-50%", y: -14, scale: 0.96 }}
            animate={{ opacity: 1, x: "-50%", y: 0, scale: 1 }}
            exit={{ opacity: 0, x: "-50%", y: -10, scale: 0.97 }}
            transition={{ type: "spring", stiffness: 460, damping: 34 }}
          >
            <div className="ed-cmdk__head">
              <Search size={16} style={{ opacity: 0.55 }} />
              <input
                ref={inputRef}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="搜索页面或操作..."
                onKeyDown={(e) => {
                  if (e.key === "Escape") onClose();
                  else if (e.key === "ArrowDown" && entries.length) {
                    e.preventDefault();
                    setIdx((i) => (i + 1) % entries.length);
                  } else if (e.key === "ArrowUp" && entries.length) {
                    e.preventDefault();
                    setIdx((i) => (i - 1 + entries.length) % entries.length);
                  } else if (e.key === "Enter" && entries[idx]) {
                    e.preventDefault();
                    const fn = entries[idx].run;
                    onClose();
                    fn();
                  }
                }}
              />
              <span className="ed-kbd">ESC</span>
            </div>
            <div className="ed-cmdk__list">
              {entries.length === 0 ? (
                <div className="ed-empty" style={{ padding: 24 }}>未找到匹配项</div>
              ) : (
                entries.map((entry, i) => (
                  <button
                    key={entry.id}
                    type="button"
                    className={`ed-cmdk__row${i === idx ? " is-active" : ""}`}
                    onMouseEnter={() => setIdx(i)}
                    onClick={() => {
                      onClose();
                      entry.run();
                    }}
                  >
                    <span>{entry.label}</span>
                  </button>
                ))
              )}
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

/* ---------- Segmented Draggable Area Switcher ---------- */

export function AreaStrip({
  areas,
  value,
  includeAll,
  onChange,
  onReorder,
}: {
  areas: AreaItem[];
  value: string;
  includeAll?: boolean;
  onChange: (id: string) => void;
  onReorder: (next: AreaItem[]) => void;
}) {
  const dragIdRef = useRef<string | null>(null);

  return (
    <div className="ed-area-strip" role="tablist">
      {includeAll && (
        <button
          type="button"
          className={`ed-area-tab${value === "__all__" ? " is-active" : ""}`}
          onClick={() => onChange("__all__")}
        >
          {value === "__all__" && (
            <motion.span
              layoutId="area-active-pill"
              className="ed-area-tab__pill"
              transition={{ type: "spring", stiffness: 460, damping: 34 }}
            />
          )}
          <span>全部域</span>
        </button>
      )}
      {areas.map((a) => {
        const active = value === a.id;
        return (
          <button
            key={a.id}
            type="button"
            draggable
            title="拖动可调整顺序"
            className={`ed-area-tab${active ? " is-active" : ""}`}
            onClick={() => onChange(a.id)}
            onDragStart={() => {
              dragIdRef.current = a.id;
            }}
            onDragOver={(e) => {
              e.preventDefault();
              const fromId = dragIdRef.current;
              if (!fromId || fromId === a.id) return;
              const list = [...areas];
              const fromIdx = list.findIndex((x) => x.id === fromId);
              const toIdx = list.findIndex((x) => x.id === a.id);
              if (fromIdx < 0 || toIdx < 0) return;
              const [moved] = list.splice(fromIdx, 1);
              list.splice(toIdx, 0, moved);
              onReorder(list);
            }}
            onDragEnd={() => {
              dragIdRef.current = null;
            }}
          >
            {active && (
              <motion.span
                layoutId="area-active-pill"
                className="ed-area-tab__pill"
                transition={{ type: "spring", stiffness: 460, damping: 34 }}
              />
            )}
            <span>{a.name || a.code || a.id}</span>
          </button>
        );
      })}
    </div>
  );
}
