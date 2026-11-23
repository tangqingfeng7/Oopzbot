import React from "react";
import { createRoot } from "react-dom/client";
import "./styles/editorial.css";
import { App } from "./App";

const rootEl = document.getElementById("admin-root");
if (rootEl) {
  createRoot(rootEl).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>
  );
}
