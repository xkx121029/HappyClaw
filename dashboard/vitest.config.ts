/// <reference types="vitest" />
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import svgr from "vite-plugin-svgr";
import path from "path";

/**
 * Standalone Vitest config — kept separate from ``vite.config.ts`` so:
 * 1. The PWA plugin and SPA build tweaks don't run for unit tests
 *    (they pull heavy deps and slow startup by ~3 s).
 * 2. We can keep ``test.environment`` / ``setupFiles`` in one obvious
 *    place without polluting the prod build config.
 */
export default defineConfig({
  plugins: [react(), svgr()],
  // `vite.config.ts` injects the build-time API base as a global constant.
  // Tests must mirror that, otherwise any module resolving `getApiUrl` /
  // `getWsUrl` throws `ReferenceError: BASE_URL is not defined`.
  define: {
    BASE_URL: JSON.stringify(""),
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    pool: "threads",
    // 本机 vite-node 冷转换 antd / pdfjs 单个文件可达 10s+（见 collect 耗时），
    // 默认 5s 会让「慢但正确」的用例在满载时成片超时，不是断言问题。
    testTimeout: 20000,
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
      include: ["src/pages/Agent/Memory/**"],
    },
  },
});
