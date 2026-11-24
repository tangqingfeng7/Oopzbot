import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  publicDir: false,
  base: "/player-assets/bundle/",
  build: {
    outDir: path.resolve(__dirname, "public/player/bundle"),
    emptyOutDir: true,
    cssCodeSplit: false,
    chunkSizeWarningLimit: 700,
    rollupOptions: {
      input: path.resolve(__dirname, "src/player/main.tsx"),
      output: {
        entryFileNames: "player-app.js",
        chunkFileNames: "chunks/[name]-[hash].js",
        assetFileNames: (info) => {
          if (info.names && info.names.some((n) => n.endsWith(".css"))) {
            return "player-app.css";
          }
          return "assets/[name]-[hash][extname]";
        },
      },
    },
  },
});
