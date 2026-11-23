import React from "react";
import { createRoot } from "react-dom/client";
import "./player.css";
import { PlayerApp } from "./PlayerApp";

const rootEl = document.getElementById("player-root");
if (rootEl) {
  createRoot(rootEl).render(
    <React.StrictMode>
      <PlayerApp />
    </React.StrictMode>
  );
}
