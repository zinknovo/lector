import react from "@vitejs/plugin-react";
import { loadEnv } from "vite";
import { defineConfig } from "vitest/config";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const target = env.VITE_API_TARGET || "http://127.0.0.1:8000";
  const headers = env.LECTOR_API_KEY
    ? { "X-API-Key": env.LECTOR_API_KEY }
    : undefined;

  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        "/api": { target, headers },
        "/ws": {
          target: target.replace(/^http/, "ws"),
          headers,
          ws: true,
        },
      },
    },
    test: {
      environment: "jsdom",
      setupFiles: "./src/test/setup.ts",
      clearMocks: true,
    },
  };
});
