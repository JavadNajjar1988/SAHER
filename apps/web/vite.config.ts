import { defineConfig } from "vite";

const backendTarget = process.env.SAHER_BACKEND_URL || "http://127.0.0.1:8765";

function createGracefulProxy(isHealthRoute: boolean) {
  return {
    target: backendTarget,
    changeOrigin: false,
    xfwd: true,
    configure: (proxy: any) => {
      const origOn = proxy.on.bind(proxy);
      origOn("error", (_err: unknown, _req: any, res: any) => {
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
              storage_accessible: true,
              demo_mode: false,
              worker_online: false,
              ocr_ready: false,
            }),
          );
        } else {
          // Use HTTP 425 (Too Early) instead of 503 so Cloud Run / Nginx proxy_intercept_errors
          // (which intercepts 502/503/504 into HTML /warmup.html) preserves the JSON payload.
          res.writeHead(425, { "Content-Type": "application/json; charset=utf-8" });
          res.end(
            JSON.stringify({
              detail: "سرویس محلی ساهر در حال راه‌اندازی اولیه است. لطفاً چند ثانیه صبر کنید…",
              code: "BACKEND_STARTING",
            }),
          );
        }
      });
      // Prevent Vite's default proxyMiddleware from registering its redundant
      // stderr logger (`[vite] http proxy error` / `ECONNREFUSED`) while FastAPI boots.
      proxy.on = (event: string, listener: (...args: any[]) => void) => {
        if (event === "error") {
          return proxy;
        }
        return origOn(event, listener);
      };
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

