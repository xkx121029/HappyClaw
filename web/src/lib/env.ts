/**
 * Build-time configuration. Vite inlines these at compile time, so they must be
 * read through `import.meta.env` and never from `process.env`.
 */
export const env = {
  /**
   * Origin the SPA calls for `/api/*`. Empty in development because Vite
   * proxies `/api` to the backend (see `vite.config.ts`), and empty in
   * production because FastAPI serves the built SPA from the same origin.
   * Set it only for a cross-origin deployment.
   */
  apiBase: (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, ""),
  /** Shown in the sidebar footer; matches the running build. */
  appVersion: import.meta.env.VITE_APP_VERSION ?? "dev",
  /** Falls back to the mocked API when the backend is unreachable (see lib/api). */
  useMockApi: import.meta.env.VITE_USE_MOCK_API === "1",
} as const;
