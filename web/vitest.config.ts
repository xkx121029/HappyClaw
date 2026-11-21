import { fileURLToPath, URL } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

/**
 * Unit tests for the chat logic layer. Kept separate from `vite.config.ts` so
 * the router plugin and the Tailwind pipeline do not run for tests.
 */
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    // Transforming the ported modules is slow on Windows; the default 5s
    // timeout turns "slow but correct" cases into flakes.
    testTimeout: 20000,
  },
});
