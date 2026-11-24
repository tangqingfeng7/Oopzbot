import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  publicDir: false,
  base: "/admin-assets/bundle/",
  build: {
    outDir: path.resolve(__dirname, "public/admin/bundle"),
    emptyOutDir: true,
    cssCodeSplit: false,
    chunkSizeWarningLimit: 700,
    rollupOptions: {
      input: path.resolve(__dirname, "src/admin/main.tsx"),
      output: {
        entryFileNames: "admin-app.js",
        chunkFileNames: "chunks/[name]-[hash].js",
        assetFileNames: (info) => {
          if (info.names && info.names.some((n) => n.endsWith(".css"))) {
            return "admin-app.css";
          }
          return "assets/[name]-[hash][extname]";
        },
      },
    },
  },
});
