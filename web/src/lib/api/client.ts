import createClient from "openapi-fetch";

import { env } from "@/lib/env";
import { readStored, storageKeys } from "@/lib/storage";

import { applyAuthHeader, persistRenewedToken } from "./auth";
import { ApiError } from "./errors";
import type { paths } from "./schema.gen";

/**
 * The one HTTP client. Types come from `schema.gen.ts`, generated from the
 * backend's own OpenAPI document (`npm run api:gen`), so a renamed field in
 * FastAPI breaks the SPA build instead of silently going undefined at runtime.
 */
export const api = createClient<paths>({
  baseUrl: env.apiBase,
  credentials: "include",
  headers: {
    Accept: "application/json",
  },
});

api.use({
  onRequest({ request }) {
    const locale = readStored(storageKeys.locale) === "en" ? "en" : "zh";
    request.headers.set("Accept-Language", locale);
    // Single-user local builds have no token; desktop and phone-hosted
    // deployments do, and this keeps one client working for all three.
    applyAuthHeader(request);
    return request;
  },
  async onResponse({ response }) {
    persistRenewedToken(response);
    if (response.ok) return response;

    const contentType = response.headers.get("content-type") ?? "";
    let body: unknown;
    if (contentType.includes("application/json")) {
      body = await response.clone().json().catch(() => null);
    } else {
      body = await response.clone().text().catch(() => null);
    }
    throw ApiError.fromResponse(response.status, body);
  },
});

/** Wraps a fetch that never reached the server into the same error type. */
export async function probeBackend(): Promise<boolean> {
  try {
    const { response } = await api.GET("/api/health");
    return Boolean(response?.ok);
  } catch {
    return false;
  }
}
