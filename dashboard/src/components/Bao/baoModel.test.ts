import { describe, expect, it } from "vitest";

import type { BaoOverview } from "../../api/modules/bao";
import type { OctopThreadHistory } from "../../api/modules/octopThreads";
import {
  agentIdFromPath,
  inferScope,
  nextFocusIndex,
  projectKeyForAgent,
  resolveDispatchOutcome,
} from "./baoModel";

function overview(): BaoOverview {
  return {
    updated_at: 1,
    totals: {
      projects: 2,
      agents: 2,
      running_agents: 1,
      active_turns: 0,
      awaiting_user: 0,
      failed_agents: 0,
    },
    projects: [
      {
        key: "default",
        name: "",
        is_default: true,
        workspace_dir: "E:/octop/agents",
        agents: [
          {
            agent_id: "a1",
            name: "A1",
            state: "running",
            last_error: null,
            model_ready: true,
          },
        ],
        sessions: [],
        running_agents: 1,
        active_turns: 0,
        awaiting_user: 0,
        failed_agents: 0,
      },
      {
        key: "ws:e:/work/alpha",
        name: "alpha",
        is_default: false,
        workspace_dir: "E:/work/alpha",
        agents: [
          {
            agent_id: "a2",
            name: "A2",
            state: "stopped",
            last_error: null,
            model_ready: true,
          },
        ],
        sessions: [],
        running_agents: 0,
        active_turns: 0,
        awaiting_user: 0,
        failed_agents: 0,
      },
    ],
  };
}

function history(
  messages: OctopThreadHistory["messages"],
  extra: Record<string, unknown> = {},
): OctopThreadHistory {
  return {
    thread_id: "t1",
    messages,
    turn_active: false,
    hitl_pending: null,
    ...extra,
  } as OctopThreadHistory;
}

function assistant(
  content: string,
  timestamp: number,
  errorCode?: string,
): OctopThreadHistory["messages"][number] {
  return {
    role: "assistant",
    content,
    timestamp,
    error_code: errorCode,
  };
}

describe("Bao scope helpers", () => {
  it("extracts the agent id from chat routes", () => {
    expect(agentIdFromPath("/chat/a1/t1")).toBe("a1");
    expect(agentIdFromPath("/chat/a1")).toBe("a1");
    expect(agentIdFromPath("/experts")).toBeNull();
  });

  it("infers project scope only when the route agent belongs to a project", () => {
    expect(inferScope(overview(), "/chat/a2/t1")).toEqual({
      scope: "project",
      projectKey: "ws:e:/work/alpha",
    });
    expect(inferScope(overview(), "/experts")).toEqual({
      scope: "global",
      projectKey: null,
    });
    expect(projectKeyForAgent(overview(), "a1")).toBe("default");
  });
});

describe("Bao keyboard navigation", () => {
  it("moves within bounds and supports Home/End", () => {
    expect(nextFocusIndex(0, 4, "ArrowDown")).toBe(1);
    expect(nextFocusIndex(3, 4, "ArrowDown")).toBe(3);
    expect(nextFocusIndex(0, 4, "ArrowUp")).toBe(0);
    expect(nextFocusIndex(2, 4, "Home")).toBe(0);
    expect(nextFocusIndex(1, 4, "End")).toBe(3);
    expect(nextFocusIndex(1, 4, "Tab")).toBeNull();
    expect(nextFocusIndex(0, 0, "ArrowDown")).toBeNull();
  });
});

describe("Bao dispatch outcome", () => {
  const dispatchedAt = 1_000;

  it("keeps running while the turn is active", () => {
    expect(
      resolveDispatchOutcome(
        history([assistant("old", 900)], { turn_active: true }),
        dispatchedAt,
        false,
      ),
    ).toEqual({ status: "running", sawActive: true });
  });

  it("reports awaiting approval", () => {
    expect(
      resolveDispatchOutcome(
        history([assistant("old", 900)], { hitl_pending: true }),
        dispatchedAt,
        true,
      ),
    ).toEqual({ status: "awaiting", sawActive: true });
  });

  it("does not treat a stale assistant message as this task's result", () => {
    expect(
      resolveDispatchOutcome(history([assistant("old", 900)]), dispatchedAt, false),
    ).toEqual({ status: "running", sawActive: false });
  });

  it("returns the fresh assistant result", () => {
    expect(
      resolveDispatchOutcome(
        history([assistant("完成", 1_001_000)]),
        dispatchedAt,
        true,
      ),
    ).toEqual({ status: "done", resultText: "完成", sawActive: true });
  });

  it("returns a fresh failure with its reason", () => {
    expect(
      resolveDispatchOutcome(
        history([assistant("模型未配置", 1_001_000, "AGENT_NO_MODEL")]),
        dispatchedAt,
        true,
      ),
    ).toEqual({
      status: "failed",
      errorText: "模型未配置",
      sawActive: true,
    });
  });
});
