import { describe, expect, it } from "vitest";
import {
  buildRingSessions,
  classifyTool,
  eventsPerMinute,
  HOME_EVENT_LIMIT,
  HOME_RING_SESSION_LIMIT,
  makeEventId,
  mergeSessions,
  segmentIndexAt,
  normalizeTimestamp,
  patchEvent,
  readToolResults,
  upsertEvent,
  watchTargets,
  type HomeEvent,
  type HomeSession,
} from "./homeActivityModel";
import type { OctopAgent } from "../../context/AgentContext";
import type { OctopThread } from "../../api/modules/octopThreads";

function agent(id: string, name = id): OctopAgent {
  return { agent_id: id, name } as OctopAgent;
}

function thread(
  id: string,
  patch: Partial<OctopThread> = {},
): OctopThread {
  return {
    thread_id: id,
    title: id,
    channel_type: "web",
    session_key: id,
    last_active: 1_700_000_000,
    created_at: 1_700_000_000,
    ...patch,
  };
}

function event(id: string, patch: Partial<HomeEvent> = {}): HomeEvent {
  return {
    id,
    at: 1_700_000_000_000,
    kind: "tool",
    agentId: "a",
    agentName: "A",
    threadId: "t",
    threadTitle: "T",
    status: "running",
    ...patch,
  };
}

function session(id: string, patch: Partial<HomeSession> = {}): HomeSession {
  return {
    agentId: "a",
    agentName: "A",
    threadId: id,
    title: id,
    lastActive: 1_700_000_000_000,
    turnActive: false,
    awaitingUser: false,
    ...patch,
  };
}

describe("classifyTool", () => {
  it("maps file, device and plugin tools", () => {
    expect(classifyTool("read_file")).toBe("file");
    expect(classifyTool("edit_file")).toBe("file");
    expect(classifyTool("phone_screenshot")).toBe("device");
    expect(classifyTool("desktop_screenshot")).toBe("device");
    expect(classifyTool("chart_render", new Set(["chart_render"]))).toBe(
      "plugin",
    );
    expect(classifyTool("web_search")).toBe("tool");
  });
});

describe("normalizeTimestamp / mergeSessions", () => {
  it("normalises seconds to milliseconds", () => {
    expect(normalizeTimestamp(1_700_000_000)).toBe(1_700_000_000_000);
    expect(normalizeTimestamp(1_700_000_000_000)).toBe(1_700_000_000_000);
    expect(normalizeTimestamp(0)).toBe(0);
  });

  it("puts active sessions first and caps the window", () => {
    const threads = new Map<string, OctopThread[]>([
      [
        "a",
        [
          thread("idle", { last_active: 1_700_000_500 }),
          thread("live", { last_active: 1_700_000_100, turn_active: true }),
          thread("wait", { last_active: 1_700_000_200, awaiting_user: true }),
        ],
      ],
    ]);
    const sessions = mergeSessions([agent("a", "Agent A")], threads, 2);
    expect(sessions).toHaveLength(2);
    expect(sessions[0].threadId).toBe("live");
    expect(sessions[1].threadId).toBe("wait");
    expect(sessions[0].lastActive).toBe(1_700_000_100_000);
    expect(sessions[0].agentName).toBe("Agent A");
  });
});

describe("segmentIndexAt", () => {
  const TURN = Math.PI * 2;

  it("maps the angle right of centre to arc 0 and the left side to the middle", () => {
    // 3 arcs at rotation 0: centres at π/3, π, 5π/3.
    expect(segmentIndexAt(0, 0, 3)).toBe(0);
    expect(segmentIndexAt(Math.PI, 0, 3)).toBe(1);
    expect(segmentIndexAt(-Math.PI / 2, 0, 3)).toBe(2);
  });

  it("follows the global rotation exactly, including mid-tween angles", () => {
    // Rotating just past -π/3 brings arc 2 under the fixed left slot.
    expect(segmentIndexAt(Math.PI, -Math.PI / 3 - 0.01, 3)).toBe(2);
    // Any rotation value is equivalent modulo 2π — no per-arc animation state.
    expect(segmentIndexAt(0.1, 0, 4)).toBe(
      segmentIndexAt(0.1 + TURN * 3, TURN * 2, 4),
    );
    expect(segmentIndexAt(-0.01, 0, 5)).toBe(4);
  });

  it("returns -1 for an empty ring", () => {
    expect(segmentIndexAt(0, 0, 0)).toBe(-1);
  });
});

describe("segmentIndexAt on the half ring", () => {
  const START = Math.PI / 2;
  const SWEEP = Math.PI;
  const SLOT = SWEEP / 4;

  it("tiles only the visible semicircle", () => {
    // Four slots across [π/2, 3π/2], sampled at each slot's centre.
    expect(segmentIndexAt(START + SLOT / 2, 0, 4, START, SWEEP)).toBe(0);
    expect(segmentIndexAt(START + SLOT * 1.5, 0, 4, START, SWEEP)).toBe(1);
    expect(segmentIndexAt(START + SLOT * 2.5, 0, 4, START, SWEEP)).toBe(2);
    expect(segmentIndexAt(START + SLOT * 3.5, 0, 4, START, SWEEP)).toBe(3);
  });

  it("follows the dial rotation and wraps once per half turn", () => {
    const angle = START + SLOT / 2;
    // A quarter turn moves every slot three places backwards.
    expect(segmentIndexAt(angle, Math.PI / 4, 4, START, SWEEP)).toBe(3);
    // Rotation is only meaningful modulo the half turn.
    expect(segmentIndexAt(angle, 0, 4, START, SWEEP)).toBe(
      segmentIndexAt(angle, SWEEP * 5, 4, START, SWEEP),
    );
  });
});

describe("buildRingSessions", () => {
  it("maps one arc per running conversation in thread-id order", () => {
    const segments = buildRingSessions([
      session("t2"),
      session("t1", { turnActive: true }),
      session("t0", { turnActive: true }),
    ]);
    expect(segments.map((segment) => segment.threadId)).toEqual(["t0", "t1"]);
    expect(segments.every((segment) => segment.turnActive)).toBe(true);
    expect(segments.every((segment) => segment.overflow === 0)).toBe(true);
    expect(segments[1].threadIds).toEqual(["t1"]);
  });

  it("drops a conversation as soon as its turn stops", () => {
    const running = [
      session("t1", { turnActive: true }),
      session("t2", { turnActive: true }),
    ];
    expect(buildRingSessions(running)).toHaveLength(2);
    const stopped = [
      running[0],
      { ...running[1], turnActive: false },
    ];
    expect(buildRingSessions(stopped).map((segment) => segment.threadId)).toEqual([
      "t1",
    ]);
  });

  it("folds the tail above the limit into one hatched arc", () => {
    const sessions = Array.from({ length: 30 }, (_, i) =>
      session(`t${String(i).padStart(2, "0")}`, { turnActive: true }),
    );
    const segments = buildRingSessions(sessions);
    expect(segments).toHaveLength(HOME_RING_SESSION_LIMIT);
    const aggregate = segments[segments.length - 1];
    expect(aggregate.key).toBe("overflow");
    expect(aggregate.overflow).toBe(30 - (HOME_RING_SESSION_LIMIT - 1));
    expect(aggregate.threadIds).toHaveLength(aggregate.overflow);
    expect(segments.filter((segment) => segment.overflow > 0)).toHaveLength(1);
  });

  it("never folds a stopped conversation into the aggregate", () => {
    const sessions = Array.from({ length: 30 }, (_, i) =>
      session(`t${String(i).padStart(2, "0")}`, {
        turnActive: i !== 29,
      }),
    );
    const segments = buildRingSessions(sessions);
    expect(segments).toHaveLength(HOME_RING_SESSION_LIMIT);
    expect(segments.some((segment) => segment.threadId === "t29")).toBe(false);
    expect(segments[0].threadId).toBe("t00");
  });

  it("collapses to nothing when nothing is running", () => {
    expect(buildRingSessions([])).toEqual([]);
    expect(buildRingSessions([session("idle")])).toEqual([]);
  });
});

describe("watchTargets", () => {
  it("watches live threads and recently touched idle threads", () => {
    const now = 1_700_000_000_000;
    const targets = watchTargets(
      [
        {
          agentId: "a",
          agentName: "A",
          threadId: "cold",
          title: "cold",
          lastActive: 0,
          turnActive: false,
          awaitingUser: false,
        },
        {
          agentId: "a",
          agentName: "A",
          threadId: "recent",
          title: "recent",
          lastActive: now - 60_000,
          turnActive: false,
          awaitingUser: false,
        },
        {
          agentId: "a",
          agentName: "A",
          threadId: "live",
          title: "live",
          lastActive: 0,
          turnActive: true,
          awaitingUser: false,
        },
      ],
      now,
    );
    expect(targets.map((target) => target.threadId)).toEqual([
      "live",
      "recent",
    ]);
  });
});

describe("event store helpers", () => {
  it("dedupes by id and enforces the limit", () => {
    let events: HomeEvent[] = [];
    for (let i = 0; i < HOME_EVENT_LIMIT + 5; i += 1) {
      events = upsertEvent(events, event(`e${i}`));
    }
    expect(events).toHaveLength(HOME_EVENT_LIMIT);
    expect(events[0].id).toBe(`e${HOME_EVENT_LIMIT + 4}`);

    const replaced = upsertEvent(events, event("e10", { status: "done" }));
    expect(replaced).toHaveLength(HOME_EVENT_LIMIT);
    expect(replaced.filter((item) => item.id === "e10")).toHaveLength(1);
  });

  it("patches only the matching event", () => {
    const before = [event("a"), event("b")];
    const after = patchEvent(before, "b", { status: "failed" });
    expect(after[0]).toBe(before[0]);
    expect(after[1].status).toBe("failed");
    expect(patchEvent(before, "missing", { status: "done" })).toBe(before);
  });

  it("counts events in the trailing window", () => {
    const now = 1_700_000_100_000;
    const events = [
      event("new", { at: now - 10_000 }),
      event("old", { at: now - 70_000 }),
    ];
    expect(eventsPerMinute(events, now)).toBe(1);
  });

  it("builds stable ids", () => {
    expect(makeEventId("turn", "t1", 42)).toBe("turn:t1:42");
  });
});

describe("tool results", () => {
  it("reads the tool call id and output per message", () => {
    const [only] = readToolResults([
      { tool_call_id: "call-1", content: "ok" },
    ]);
    expect(only.callId).toBe("call-1");
    expect(only.output).toBe("ok");
    expect(only.failed).toBe(false);
    expect(readToolResults([{ content: "x" }])[0].callId).toBeUndefined();
  });

  it("judges each message, not the whole frame", () => {
    // The harness can resend prior tool messages in one frame. A failed
    // read_file must not mark a successful ls as failed.
    const [ls, read] = readToolResults([
      { tool_call_id: "call-ls", content: "['/a/', '/b/']" },
      {
        tool_call_id: "call-read",
        status: "error",
        content: "Error: File 'README.md' not found",
      },
    ]);
    expect(ls.failed).toBe(false);
    expect(read.failed).toBe(true);
    expect(read.output).toContain("not found");
  });

  it("reads explicit and envelope-reported errors", () => {
    const [explicit] = readToolResults([{ status: "error", content: "boom" }]);
    expect(explicit.failed).toBe(true);
    const [envelope] = readToolResults([
      { content: '{"status": "failed", "message": "bad"}' },
    ]);
    expect(envelope.failed).toBe(true);
  });
});
