import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import { fileURLToPath, URL } from "node:url";

export default defineConfig(({ mode }) => ({
  plugins: [vue()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    host: "0.0.0.0",
    port: 8090,
    proxy: {
      "/api": {
        target: process.env.VITE_API_PROXY || "http://127.0.0.1:8099",
        changeOrigin: true,
      },
    },
  },
  build: {
    target: "es2022",
    sourcemap: false,
    chunkSizeWarningLimit: 1600,
  },
  define: {
    __DEMO__: JSON.stringify(mode === "demo" || process.env.VITE_DEMO === "1"),
  },
}));
