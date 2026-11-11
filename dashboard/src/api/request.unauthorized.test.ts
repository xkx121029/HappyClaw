import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./config", () => ({
  getApiUrl: (path: string) => `/api${path}`,
}));

vi.mock("../i18n", () => ({
  default: {
    language: "zh",
    t: (
      _key: string,
      fallback?: string | Record<string, unknown>,
      options?: Record<string, unknown>,
    ) => {
      const template =
        typeof fallback === "string" ? fallback : fallback ? _key : _key;
      const values =
        (options ?? (typeof fallback === "object" ? fallback : undefined)) ??
        {};
      return template.replace(/\{\{(\w+)\}\}/g, (match, name: string) =>
        values[name] === undefined ? match : String(values[name]),
      );
    },
  },
}));

function unauthorizedResponse(): Response {
  return new Response("{}", {
    status: 401,
    headers: { "content-type": "application/json" },
  });
}

describe("401 handling", () => {
  const replace = vi.fn();
  let mod: typeof import("./request");

  beforeEach(async () => {
    vi.resetModules();
    localStorage.clear();
    sessionStorage.clear();
    replace.mockClear();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { pathname: "/chat", replace },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(unauthorizedResponse())),
    );
    mod = await import("./request");
    mod.setAuthToken("expired-token");
  });

  it("lets an in-app listener take over the redirect instead of reloading", async () => {
    const listener = vi.fn((event: Event) => event.preventDefault());
    window.addEventListener(mod.UNAUTHORIZED_EVENT, listener);

    await expect(mod.request("/agents")).rejects.toThrow();

    expect(listener).toHaveBeenCalledOnce();
    expect(replace).not.toHaveBeenCalled();
    expect(mod.getAuthToken()).toBe("");

    window.removeEventListener(mod.UNAUTHORIZED_EVENT, listener);
  });

  it("keeps the page alive and reports a readable message when nothing handles the event", async () => {
    await expect(mod.request("/agents")).rejects.toThrow(/本机连接已失效/);

    expect(replace).not.toHaveBeenCalled();
    expect(mod.getAuthToken()).toBe("");
  });

  it("keeps the local session when a 401 is a peer credential error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          new Response(
            JSON.stringify({
              error: {
                code: "BRIDGE_AUTH_FAILED",
                message: "peer rejected credentials",
                details: {},
              },
            }),
            {
              status: 401,
              headers: { "content-type": "application/json" },
            },
          ),
        ),
      ),
    );

    const err = await mod
      .request("/bridge/probe", { method: "POST" })
      .catch((e: unknown) => e);

    expect((err as { code?: string }).code).toBe("BRIDGE_AUTH_FAILED");
    expect((err as Error).message).toBe("peer rejected credentials");
    expect(replace).not.toHaveBeenCalled();
    expect(mod.getAuthToken()).toBe("expired-token");
  });

  it("turns a bare 500 into a readable Chinese message", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          new Response("Internal Server Error", {
            status: 500,
            statusText: "Internal Server Error",
          }),
        ),
      ),
    );

    const err = await mod.request("/agents").catch((e: unknown) => e);

    expect((err as Error).message).toMatch(/本机服务处理请求时出错（500）/);
    expect((err as Error).message).not.toMatch(/Internal Server Error/);
    expect((err as { status?: number }).status).toBe(500);
  });

  it("shows the server error.message from a JSON envelope", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          new Response(
            JSON.stringify({
              error: {
                code: "MODEL_NOT_CONFIGURED",
                message: "还没有配置可用的模型，请先到「本机设置 → 模型」添加。",
              },
            }),
            {
              status: 500,
              headers: { "content-type": "application/json" },
            },
          ),
        ),
      ),
    );

    const err = await mod.request("/agents").catch((e: unknown) => e);

    expect((err as Error).message).toBe(
      "还没有配置可用的模型，请先到「本机设置 → 模型」添加。",
    );
  });

  it("redirects only once when several requests fail concurrently", async () => {
    const listener = vi.fn((event: Event) => event.preventDefault());
    window.addEventListener(mod.UNAUTHORIZED_EVENT, listener);

    await Promise.allSettled([
      mod.request("/agents"),
      mod.request("/skills"),
      mod.request("/cron"),
    ]);

    expect(listener).toHaveBeenCalledOnce();

    window.removeEventListener(mod.UNAUTHORIZED_EVENT, listener);
  });
});
