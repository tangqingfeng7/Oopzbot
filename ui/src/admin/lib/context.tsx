import React, { createContext, useContext } from "react";
import type { NavItem } from "./api";

export type StatusKind = "neutral" | "success" | "warning" | "error";

export interface AppContextValue {
  navItems: NavItem[];
  hasPlugin: (key: string) => boolean;
  navigate: (key: string) => void;
  setStatus: (text: string, kind?: StatusKind) => void;
  toast: (text: string, kind?: "info" | "success" | "warning" | "error") => void;
  confirm: (title: string, message: string, opts?: { okText?: string; danger?: boolean }) => Promise<boolean>;
  refreshPluginNav: () => Promise<void>;
}

export const AppContext = createContext<AppContextValue | null>(null);

export function useApp(): AppContextValue {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("AppContext missing");
  return ctx;
}
