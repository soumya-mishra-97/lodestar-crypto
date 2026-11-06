/// <reference types="vitest/config" />
import { fileURLToPath, URL } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    port: 5173,
    // Same-origin proxy: the refresh cookie stays SameSite=Strict and no CORS is needed in dev.
    // 127.0.0.1, not "localhost": Node may resolve localhost to ::1 while uvicorn listens on IPv4 only.
    proxy: { "/api": { target: process.env.LS_API_URL ?? "http://127.0.0.1:8000", changeOrigin: false } },
  },
  build: {
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks: { charts: ["lightweight-charts"], vendor: ["react", "react-dom", "react-router", "@tanstack/react-query"] },
      },
    },
  },
  test: { environment: "jsdom", include: ["src/**/*.test.{ts,tsx}"] },
});
