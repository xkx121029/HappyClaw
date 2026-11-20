import { describe, expect, it } from "vitest";

import { classifyCronRunError } from "./cronDisplay";

describe("classifyCronRunError", () => {
  it("treats every missed row as the offline reason regardless of error text", () => {
    expect(
      classifyCronRunError({
        status: "missed",
        error: "scheduled time passed while the server was offline",
      }),
    ).toBe("missed");
  });

  it.each([
    ["agent 'main' has no model configured", "noModel"],
    ["agent 'main' not found", "agentNotFound"],
    ["agent 'main' not running", "agentNotRunning"],
    ["cron agent run requires user interaction", "interactionRequired"],
    ["cron agent run produced no visible response", "emptyResponse"],
    ["another run was already in progress", "alreadyRunning"],
    ["run lease was lost while executing", "leaseLost"],
    ["run cancelled: the server is shutting down", "cancelled"],
    ["gateway is not ready", "gatewayNotReady"],
    ["request timed out after 60s", "timeout"],
  ])("maps %s to %s", (error, kind) => {
    expect(classifyCronRunError({ status: "error", error })).toBe(kind);
  });

  it("keeps unknown failures raw", () => {
    expect(
      classifyCronRunError({ status: "error", error: "boom from plugin" }),
    ).toBe("unknown");
    expect(classifyCronRunError({ status: "error", error: null })).toBe(
      "unknown",
    );
  });
});
