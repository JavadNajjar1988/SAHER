import { defineConfig } from "vite";

const backendTarget = process.env.SAHER_BACKEND_URL || "http://127.0.0.1:8765";

export default defineConfig({
  server: {
    host: "0.0.0.0",
    port: 3000,
    allowedHosts: true,
    proxy: {
      "/api": {
        target: backendTarget,
        changeOrigin: false,
      },
      "/health": {
        target: backendTarget,
        changeOrigin: false,
      },
    },
  },
  preview: {
    host: "0.0.0.0",
    port: 3000,
    allowedHosts: true,
    proxy: {
      "/api": {
        target: backendTarget,
        changeOrigin: false,
      },
      "/health": {
        target: backendTarget,
        changeOrigin: false,
      },
    },
  },
});
