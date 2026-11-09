import { defineConfig } from "vite";

const backendTarget = process.env.SAHER_BACKEND_URL || "http://127.0.0.1:8765";

function createGracefulProxy(isHealthRoute: boolean) {
  return {
    target: backendTarget,
    changeOrigin: false,
    configure: (proxy: any) => {
      proxy.on("error", (_err: unknown, _req: any, res: any) => {
        if (!res || res.headersSent || typeof res.writeHead !== "function") {
          return;
        }
        if (isHealthRoute) {
          res.writeHead(200, { "Content-Type": "application/json; charset=utf-8" });
          res.end(
            JSON.stringify({
              status: "starting",
              service: "saher-local-api",
              version: "0.3.0",
              database: "initializing",
              demo_mode: false,
              worker_online: false,
            }),
          );
        } else {
          res.writeHead(503, { "Content-Type": "application/json; charset=utf-8" });
          res.end(
            JSON.stringify({
              detail: "سرویس محلی ساهر در حال راه‌اندازی است. لطفاً چند ثانیه صبر کنید.",
              code: "BACKEND_STARTING",
            }),
          );
        }
      });
    },
  };
}

export default defineConfig({
  server: {
    host: "0.0.0.0",
    port: 3000,
    allowedHosts: true,
    proxy: {
      "/api": createGracefulProxy(false),
      "/health": createGracefulProxy(true),
    },
  },
  preview: {
    host: "0.0.0.0",
    port: 3000,
    allowedHosts: true,
    proxy: {
      "/api": createGracefulProxy(false),
      "/health": createGracefulProxy(true),
    },
  },
});

