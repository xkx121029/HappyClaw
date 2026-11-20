import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAgent } from "../../context/AgentContext";
import { runtimeApi, type RuntimeActivity } from "../../api/modules/runtime";
import {
  octopThreadsApi,
  type OctopThread,
} from "../../api/modules/octopThreads";
import { agentToolsApi } from "../../api/modules/agentTools";
import { buildDashboardChatWsUrl } from "../../api/modules/wsChat";
import {
  buildRingSessions,
  classifyTool,
  eventsPerMinute,
  HOME_EVENT_LIMIT,
  HOME_LINK_LIMIT,
  HOME_RING_SOURCE_LIMIT,
  HOME_TICK_LIMIT,
  makeEventId,
  mergeSessions,
  patchEvent,
  readToolResults,
  upsertEvent,
  watchTargets,
  type HomeEvent,
  type HomeLink,
  type HomeLinkKind,
  type HomeSession,
  type HomeTick,
  type HomeTone,
  type RingSegment,
} from "./homeActivityModel";

const ACTIVITY_POLL_MS = 3_000;
const THREAD_POLL_MS = 5_000;
const TOOL_META_REFRESH_MS = 60_000;
const PING_MS = 25_000;

/**
 * Outcome of a ring quick action.
 * ``reason`` is a stable code (``socket``/``no_ack``/``forbidden``/…) or the
 * server message; the menu translates the codes and shows the rest verbatim.
 */
export interface HomeActionResult {
  ok: boolean;
  reason?: string;
  /** True when a running turn queued the message instead of starting one. */
  queued?: boolean;
}

interface HomeActivityState {
  activity: RuntimeActivity | null;
  sessions: HomeSession[];
  /** One arc per session; 24 max, the remainder folded into a final arc. */
  ringSessions: RingSegment[];
  events: HomeEvent[];
  /** True when the last HTTP poll failed (network/backend down). */
  offline: boolean;
  /** Number of chat sockets currently subscribed by this page. */
  watchedThreads: number;
  ratePerMinute: number;
  /** Throttled per-tone pulses for the background core. */
  ticks: HomeTick[];
  /** Real team-room collaborator signals (speaker → room thread). */
  links: HomeLink[];
  /** Deliver a follow-up; the server queues it while a turn is active. */
  sendMessage: (
    agentId: string,
    threadId: string,
    text: string,
  ) => Promise<HomeActionResult>;
  /** Ask the server to cancel the thread's current turn (WS ``cancel``). */
  cancelTurn: (
    agentId: string,
    threadId: string,
  ) => Promise<HomeActionResult>;
  refresh: () => void;
}

function previewText(value: unknown, max = 100): string {
  if (typeof value !== "string") return "";
  const flat = value.replace(/\s+/g, " ").trim();
  if (!flat) return "";
  return flat.length > max ? `${flat.slice(0, max)}…` : flat;
}

function mapEqual(
  left: ReadonlyMap<string, OctopThread[]>,
  right: ReadonlyMap<string, OctopThread[]>,
): boolean {
  if (left.size !== right.size) return false;
  for (const [key, value] of right) {
    const prev = left.get(key);
    if (!prev || prev.length !== value.length) return false;
    for (let i = 0; i < value.length; i += 1) {
      const a = prev[i];
      const b = value[i];
      if (
        a.thread_id !== b.thread_id ||
        a.title !== b.title ||
        a.last_active !== b.last_active ||
        a.turn_active !== b.turn_active ||
        a.awaiting_user !== b.awaiting_user
      ) {
        return false;
      }
    }
  }
  return true;
}

interface SocketEntry {
  socket: WebSocket;
  ping: number | null;
  retryTimer: number | null;
  retries: number;
}

/**
 * Real activity feed for the Home page.
 *
 * Sources (all existing):
 *  • ``GET /api/runtime/activity`` — backend counters.
 *  • ``GET /api/agents/{id}/threads`` — active/recent sessions.
 *  • ``GET /api/agents/{id}/tool-settings`` — plugin tool metadata.
 *  • ``WS /api/agents/{id}/chat/ws`` + ``subscribe`` — live turn/tool frames.
 *
 * No synthetic data is produced: when nothing is running the feed stays empty.
 */
export function useHomeActivity(): HomeActivityState {
  const { agents, refresh: refreshAgents } = useAgent();
  const [activity, setActivity] = useState<RuntimeActivity | null>(null);
  const [threadsByAgent, setThreadsByAgent] = useState<
    Map<string, OctopThread[]>
  >(new Map());
  const [events, setEvents] = useState<HomeEvent[]>([]);
  const [offline, setOffline] = useState(false);
  const [watchedThreads, setWatchedThreads] = useState(0);
  const [nowTick, setNowTick] = useState(() => Date.now());
  const [ticks, setTicks] = useState<HomeTick[]>([]);
  const [links, setLinks] = useState<HomeLink[]>([]);
  /** Turn liveness inferred from frames, so a finished turn leaves the ring
   * before the 5 s thread poll catches up. */
  const [liveTurns, setLiveTurns] = useState<Map<string, boolean>>(new Map());

  const runningAgents = useMemo(
    () =>
      agents.filter(
        (agent) =>
          agent.state === "running" || Boolean(agent.bridge_disconnected),
      ),
    [agents],
  );

  const pluginToolsRef = useRef<Set<string>>(new Set());
  const pluginNamesRef = useRef<Map<string, string>>(new Map());

  // ---- event batching (one React update per frame) -----------------------
  const pendingRef = useRef<Array<(current: HomeEvent[]) => HomeEvent[]>>([]);
  const frameRef = useRef<number | null>(null);

  const flush = useCallback(() => {
    frameRef.current = null;
    const tasks = pendingRef.current;
    pendingRef.current = [];
    if (tasks.length === 0) return;
    setEvents((current) => tasks.reduce((acc, task) => task(acc), current));
  }, []);

  const enqueue = useCallback(
    (task: (current: HomeEvent[]) => HomeEvent[]) => {
      pendingRef.current.push(task);
      if (frameRef.current === null) {
        frameRef.current = window.requestAnimationFrame(flush);
      }
    },
    [flush],
  );

  // ---- tone pulses for the background core -------------------------------
  const tickBufRef = useRef<HomeTick[]>([]);
  const tickSeqRef = useRef(0);
  const tickTimerRef = useRef<number | null>(null);
  /** Last pulse per ``threadId:tone``: streaming frames are throttled per
   * session so one busy thread cannot mute another. */
  const lastTickAtRef = useRef<Map<string, number>>(new Map());

  const pushTick = useCallback(
    (tone: HomeTone, threadId: string, opKey: string, label?: string) => {
      const now = Date.now();
      // Streaming chunks arrive dozens of times per second; a pulse every
      // 120–200 ms reads as continuous output without a render per chunk.
      const minGap = tone === "text" ? 120 : tone === "think" ? 200 : 0;
      const key = `${threadId}:${tone}`;
      const last = lastTickAtRef.current.get(key) ?? 0;
      if (minGap > 0 && now - last < minGap) return;
      lastTickAtRef.current.set(key, now);
      tickBufRef.current.push({
        id: (tickSeqRef.current += 1),
        at: now,
        tone,
        threadId,
        opKey,
        label,
      });
      if (tickBufRef.current.length > HOME_TICK_LIMIT) {
        tickBufRef.current.splice(
          0,
          tickBufRef.current.length - HOME_TICK_LIMIT,
        );
      }
      if (tickTimerRef.current !== null) return;
      tickTimerRef.current = window.setTimeout(() => {
        tickTimerRef.current = null;
        setTicks(tickBufRef.current.slice());
      }, 120);
    },
    [],
  );

  // ---- turn liveness + team collaboration links --------------------------
  const liveTurnRef = useRef<Map<string, boolean>>(new Map());
  const markLiveTurn = useCallback((threadId: string, active: boolean) => {
    if (liveTurnRef.current.get(threadId) === active) return;
    const next = new Map(liveTurnRef.current);
    next.set(threadId, active);
    liveTurnRef.current = next;
    setLiveTurns(next);
  }, []);

  const linkSeqRef = useRef(0);
  const lastLinkRef = useRef({ at: 0, key: "" });

  /** A stamped team-room frame proves ``fromAgentId`` is working for the room
   * thread. Frames are stamped in ``infra/agents/teams/team_manager.py``
   * (``stamp_stream_speaker``); the host's own frames carry the host id and
   * are skipped here. */
  const pushLink = useCallback(
    (fromAgentId: string, toThreadId: string, kind: HomeLinkKind) => {
      const now = Date.now();
      const key = `${fromAgentId}>${toThreadId}:${kind}`;
      const last = lastLinkRef.current;
      if (key === last.key && now - last.at < 800) return;
      if (now - last.at < 400) return;
      lastLinkRef.current = { at: now, key };
      setLinks((current) => {
        const next = [
          ...current,
          {
            id: (linkSeqRef.current += 1),
            at: now,
            fromAgentId,
            toThreadId,
            kind,
          },
        ];
        return next.length > HOME_LINK_LIMIT
          ? next.slice(next.length - HOME_LINK_LIMIT)
          : next;
      });
    },
    [],
  );

  useEffect(() => {
    // Refresh the "now" clock so relative timestamps and the rate window move
    // even when no event arrives.
    const id = window.setInterval(() => setNowTick(Date.now()), 15_000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(
    () => () => {
      if (frameRef.current !== null) {
        window.cancelAnimationFrame(frameRef.current);
      }
      if (tickTimerRef.current !== null) {
        window.clearTimeout(tickTimerRef.current);
      }
      pendingRef.current = [];
      tickBufRef.current = [];
    },
    [],
  );

  // ---- backend runtime counters -----------------------------------------
  const loadActivity = useCallback(async () => {
    if (document.hidden) return;
    try {
      const next = await runtimeApi.activity();
      setActivity(next);
      setOffline(false);
    } catch {
      setOffline(true);
    }
  }, []);

  useEffect(() => {
    void loadActivity();
    const id = window.setInterval(() => void loadActivity(), ACTIVITY_POLL_MS);
    return () => window.clearInterval(id);
  }, [loadActivity]);

  // ---- sessions ----------------------------------------------------------
  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      if (document.hidden || runningAgents.length === 0) {
        if (!cancelled) setThreadsByAgent(new Map());
        return;
      }
      const results = await Promise.allSettled(
        runningAgents.map(async (agent) => {
          const threads = await octopThreadsApi.list(agent.agent_id, 20);
          return [agent.agent_id, threads] as const;
        }),
      );
      if (cancelled) return;
      const next = new Map<string, OctopThread[]>();
      for (const result of results) {
        if (result.status === "fulfilled") {
          next.set(result.value[0], result.value[1]);
        }
      }
      setThreadsByAgent((prev) => (mapEqual(prev, next) ? prev : next));
    };

    void load();
    const id = window.setInterval(() => void load(), THREAD_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [runningAgents]);

  // Refresh the agent list once so a newly started expert is not missed.
  useEffect(() => {
    void refreshAgents({ silent: true });
  }, [refreshAgents]);

  // ---- plugin tool metadata ---------------------------------------------
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      if (runningAgents.length === 0) return;
      const names = new Set<string>();
      const labels = new Map<string, string>();
      await Promise.allSettled(
        runningAgents.map(async (agent) => {
          const response = await agentToolsApi.get(agent.agent_id);
          for (const tool of response.tools) {
            if (tool.source !== "plugin") continue;
            names.add(tool.name);
            if (tool.plugin_name) labels.set(tool.name, tool.plugin_name);
          }
        }),
      );
      if (cancelled) return;
      pluginToolsRef.current = names;
      pluginNamesRef.current = labels;
    };
    void load();
    const id = window.setInterval(() => void load(), TOOL_META_REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [runningAgents]);

  // ---- live chat sockets -------------------------------------------------
  const sessions = useMemo(
    () => mergeSessions(runningAgents, threadsByAgent),
    [runningAgents, threadsByAgent],
  );
  const ringSource = useMemo(
    () =>
      mergeSessions(runningAgents, threadsByAgent, HOME_RING_SOURCE_LIMIT),
    [runningAgents, threadsByAgent],
  );
  const ringSessions = useMemo(() => {
    const effective = ringSource.map((session) => {
      const live = liveTurns.get(session.threadId);
      if (live === undefined || live === session.turnActive) return session;
      return { ...session, turnActive: live };
    });
    return buildRingSessions(effective);
  }, [ringSource, liveTurns]);
  const targets = useMemo(() => watchTargets(sessions), [sessions]);
  const watchKey = targets
    .map((target) => `${target.agentId}:${target.threadId}`)
    .sort()
    .join("|");
  const targetsRef = useRef(targets);
  targetsRef.current = targets;

  useEffect(() => {
    if (!watchKey) {
      setWatchedThreads(0);
      return;
    }
    const wanted = new Map(
      targetsRef.current.map((target) => [
        `${target.agentId}:${target.threadId}`,
        target,
      ]),
    );
    const sockets = new Map<string, SocketEntry>();
    let disposed = false;
    setWatchedThreads(wanted.size);

    const handleFrame = (target: HomeSession, raw: string) => {
      let frame: Record<string, unknown>;
      try {
        const parsed: unknown = JSON.parse(raw);
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
          return;
        }
        frame = parsed as Record<string, unknown>;
      } catch {
        return;
      }
      const type = typeof frame.type === "string" ? frame.type : "";
      const threadId =
        typeof frame.thread_id === "string" && frame.thread_id
          ? frame.thread_id
          : target.threadId;
      const now = Date.now();

      // Team rooms stamp the speaking agent on relayed frames
      // (``infra/agents/teams/team_manager.py`` → ``stamp_stream_speaker``).
      // A speaker that is not this thread's own agent is a real
      // member → room collaboration signal; without it we draw no link.
      const speaker =
        typeof frame.agent_id === "string" ? frame.agent_id.trim() : "";
      if (speaker && speaker !== target.agentId) {
        const kind: HomeLinkKind =
          frame.team_snapshot === true
            ? "summary"
            : frame.team_wrapup === true
              ? "handoff"
              : "relay";
        pushLink(speaker, threadId, kind);
      }

      const runningTurn = (current: HomeEvent[]) =>
        current.find(
          (event) =>
            event.threadId === threadId &&
            event.kind === "turn" &&
            event.status === "running",
        );

      switch (type) {
        case "turn.started":
        case "turn.resumed":
        case "turn_status": {
          const active =
            type !== "turn_status" || frame.active === true;
          markLiveTurn(threadId, active);
          if (!active) return;
          // The turn is running but has not emitted tool/text frames yet.
          pushTick("think", threadId, "turn");
          const turnId =
            typeof frame.turn_id === "string" ? frame.turn_id : String(now);
          enqueue((current) => {
            const existing = runningTurn(current);
            if (existing) {
              return patchEvent(current, existing.id, {
                status: "running",
                detail:
                  type === "turn.resumed"
                    ? "继续处理中"
                    : existing.detail,
              });
            }
            return upsertEvent(current, {
              id: makeEventId("turn", threadId, Number(turnId) || now),
              at: now,
              kind: "turn",
              agentId: target.agentId,
              agentName: target.agentName,
              threadId,
              threadTitle: target.title,
              status: "running",
              detail: type === "turn_status" ? "正在处理" : "开始处理消息",
            });
          });
          return;
        }
        case "user": {
          markLiveTurn(threadId, true);
          const preview = previewText(frame.content);
          enqueue((current) => {
            const existing = runningTurn(current);
            if (existing) {
              return preview
                ? patchEvent(current, existing.id, { detail: preview })
                : current;
            }
            return upsertEvent(current, {
              id: makeEventId("turn", threadId, now),
              at: now,
              kind: "turn",
              agentId: target.agentId,
              agentName: target.agentName,
              threadId,
              threadTitle: target.title,
              status: "running",
              detail: preview || "收到新消息",
            });
          });
          return;
        }
        case "token": {
          markLiveTurn(threadId, true);
          pushTick("text", threadId, "text");
          return;
        }
        case "reasoning": {
          markLiveTurn(threadId, true);
          pushTick("think", threadId, "reasoning");
          return;
        }
        case "turn.ended": {
          const failed = frame.failed === true;
          markLiveTurn(threadId, false);
          pushTick(failed ? "error" : "done", threadId, "turn");
          enqueue((current) => {
            const existing = runningTurn(current);
            if (!existing) return current;
            return patchEvent(current, existing.id, {
              status: failed ? "failed" : "done",
              detail: failed ? "本轮执行失败" : existing.detail,
            });
          });
          return;
        }
        case "error": {
          const message = previewText(frame.message, 160) || "未知错误";
          const code =
            typeof frame.error_code === "string" ? frame.error_code : "";
          markLiveTurn(threadId, false);
          pushTick("error", threadId, "error");
          enqueue((current) => {
            const withTurn = runningTurn(current);
            const patched = withTurn
              ? patchEvent(current, withTurn.id, { status: "failed" })
              : current;
            return upsertEvent(patched, {
              id: makeEventId("error", threadId, now),
              at: now,
              kind: "error",
              agentId: target.agentId,
              agentName: target.agentName,
              threadId,
              threadTitle: target.title,
              status: "failed",
              detail: code ? `${message} (${code})` : message,
            });
          });
          return;
        }
        case "hitl_required": {
          markLiveTurn(threadId, true);
          enqueue((current) =>
            upsertEvent(current, {
              id: makeEventId("hitl", threadId, now),
              at: now,
              kind: "hitl",
              agentId: target.agentId,
              agentName: target.agentName,
              threadId,
              threadTitle: target.title,
              status: "running",
              detail: "等待你确认后继续",
            }),
          );
          return;
        }
        case "tool_call_chunk": {
          const name =
            typeof frame.name === "string" ? frame.name.trim() : "";
          if (!name) return;
          const callId =
            typeof frame.id === "string" && frame.id.trim()
              ? frame.id.trim()
              : `${threadId}:${String(frame.index ?? 0)}:${name}`;
          const id = `tool:${threadId}:${callId}`;
          const kind = classifyTool(name, pluginToolsRef.current);
          markLiveTurn(threadId, true);
          const pluginName =
            kind === "plugin" ? pluginNamesRef.current.get(name) : "";
          const detail =
            pluginName ||
            (typeof frame.display_name === "string" && frame.display_name) ||
            name;
          pushTick("tool", threadId, callId, detail);
          enqueue((current) => {
            if (current.some((event) => event.id === id)) return current;
            return upsertEvent(current, {
              id,
              at: now,
              kind,
              toolName: name,
              detail,
              agentId: target.agentId,
              agentName: target.agentName,
              threadId,
              threadTitle: target.title,
              status: "running",
            });
          });
          return;
        }
        case "tool_result": {
          const messages = Array.isArray(frame.messages)
            ? frame.messages
            : [];
          const results = readToolResults(messages);
          // A frame may resend the whole tool-message history; only an
          // unambiguous single result may fall back to "latest running".
          const soleResult = results.length === 1 ? results[0] : undefined;
          enqueue((current) => {
            let next = current;
            for (const result of results) {
              const eventId = result.callId
                ? `tool:${threadId}:${result.callId}`
                : "";
              let targetEvent = eventId
                ? next.find((event) => event.id === eventId)
                : undefined;
              if (!targetEvent && soleResult === result) {
                targetEvent = next.find(
                  (event) =>
                    event.threadId === threadId &&
                    event.status === "running" &&
                    event.kind !== "turn" &&
                    event.kind !== "hitl",
                );
              }
              if (!targetEvent || targetEvent.status !== "running") continue;
              next = patchEvent(next, targetEvent.id, {
                status: result.failed ? "failed" : "done",
                durationMs: now - targetEvent.at,
                detail: result.failed
                  ? previewText(result.output, 160) || "工具执行失败"
                  : targetEvent.detail,
              });
            }
            return next;
          });
          return;
        }
        case "done": {
          // Per-message end marker: a finished turn must leave the ring now,
          // not when the 5 s thread poll catches up.
          markLiveTurn(threadId, false);
          return;
        }
        default:
          return;
      }
    };

    const open = (key: string) => {
      const target = wanted.get(key);
      if (!target || disposed) return;
      const url = buildDashboardChatWsUrl(target.agentId);
      let socket: WebSocket;
      try {
        socket = new WebSocket(url);
      } catch {
        return;
      }
      const entry: SocketEntry = {
        socket,
        ping: null,
        retryTimer: null,
        retries: 0,
      };
      sockets.set(key, entry);

      socket.onopen = () => {
        entry.retries = 0;
        socket.send(
          JSON.stringify({ type: "subscribe", thread_id: target.threadId }),
        );
        entry.ping = window.setInterval(() => {
          if (socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({ type: "ping" }));
          }
        }, PING_MS);
      };
      socket.onmessage = (event) => {
        if (typeof event.data === "string") {
          handleFrame(target, event.data);
        }
      };
      socket.onclose = (event) => {
        if (entry.ping !== null) window.clearInterval(entry.ping);
        sockets.delete(key);
        if (disposed) return;
        // 4403/4404 = access denied / thread gone: do not hammer the server.
        if (event.code === 4403 || event.code === 4404) return;
        if (entry.retries >= 5) return;
        const delay = Math.min(15_000, 1_000 * 2 ** entry.retries);
        entry.retryTimer = window.setTimeout(() => {
          entry.retries += 1;
          open(key);
        }, delay);
      };
      socket.onerror = () => {
        // ``onclose`` owns the retry/backoff path.
      };
    };

    for (const key of wanted.keys()) open(key);

    return () => {
      disposed = true;
      for (const entry of sockets.values()) {
        if (entry.ping !== null) window.clearInterval(entry.ping);
        if (entry.retryTimer !== null) window.clearTimeout(entry.retryTimer);
        entry.socket.close();
      }
      sockets.clear();
    };
    // ``handleFrame``/``enqueue``/``pushTick`` are stable; reconnecting only
    // when the watched thread set changes keeps sockets long-lived across
    // polls.
  }, [watchKey, enqueue, pushTick, markLiveTurn, pushLink]);

  /**
   * Run one frame on a dedicated short-lived socket and resolve on the first
   * server acknowledgement, so the UI can report the real outcome instead of
   * assuming success.
   */
  const runThreadAction = useCallback(
    (
      agentId: string,
      threadId: string,
      payload: Record<string, unknown>,
      interpret: (frame: Record<string, unknown>) => HomeActionResult | null,
      timeout: HomeActionResult,
      timeoutMs: number,
    ): Promise<HomeActionResult> =>
      new Promise((resolve) => {
        let settled = false;
        let socket: WebSocket | null = null;
        let timer = 0;
        const finish = (result: HomeActionResult) => {
          if (settled) return;
          settled = true;
          window.clearTimeout(timer);
          try {
            socket?.close();
          } catch {
            // Already closing.
          }
          resolve(result);
        };
        try {
          socket = new WebSocket(buildDashboardChatWsUrl(agentId));
        } catch {
          resolve({ ok: false, reason: "socket" });
          return;
        }
        socket.onopen = () => {
          socket?.send(
            JSON.stringify({ type: "subscribe", thread_id: threadId }),
          );
          socket?.send(JSON.stringify(payload));
        };
        socket.onmessage = (event) => {
          if (typeof event.data !== "string") return;
          let frame: Record<string, unknown>;
          try {
            const parsed: unknown = JSON.parse(event.data);
            if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
              return;
            }
            frame = parsed as Record<string, unknown>;
          } catch {
            return;
          }
          const result = interpret(frame);
          if (result) finish(result);
        };
        socket.onerror = () => finish({ ok: false, reason: "socket" });
        socket.onclose = (event) => {
          if (settled) return;
          finish({
            ok: false,
            reason:
              event.code === 4404
                ? "thread_gone"
                : event.code === 4403
                  ? "forbidden"
                  : "socket",
          });
        };
        timer = window.setTimeout(() => finish(timeout), timeoutMs);
      }),
    [],
  );

  const sendMessage = useCallback(
    (agentId: string, threadId: string, text: string) => {
      const trimmed = text.trim();
      if (!trimmed) return Promise.resolve({ ok: false, reason: "empty" });
      const clientPendingId = `home-${Date.now()}-${Math.random()
        .toString(36)
        .slice(2, 8)}`;
      return runThreadAction(
        agentId,
        threadId,
        {
          type: "user_turn",
          text: trimmed,
          thread_id: threadId,
          // ``auto`` = start a turn when idle, queue as a steer while running.
          delivery: "auto",
          client_pending_id: clientPendingId,
          messages: [{ role: "user", content: trimmed }],
        },
        (frame) => {
          const type = typeof frame.type === "string" ? frame.type : "";
          if (type === "steer.ack") {
            const status =
              typeof frame.status === "string" ? frame.status : "";
            if (status === "queued" || status === "ok") {
              return { ok: true, queued: true };
            }
            return {
              ok: false,
              reason:
                typeof frame.reason === "string" && frame.reason.trim()
                  ? frame.reason.trim()
                  : status || "rejected",
            };
          }
          if (type === "error") {
            return {
              ok: false,
              reason:
                typeof frame.message === "string" && frame.message.trim()
                  ? frame.message.trim()
                  : "error",
            };
          }
          if (type === "user") {
            // Ignore echoes of older messages that a fresh subscribe replays.
            const pending =
              typeof frame.client_pending_id === "string"
                ? frame.client_pending_id
                : "";
            return !pending || pending === clientPendingId
              ? { ok: true }
              : null;
          }
          if (type === "turn.started" || type === "turn.resumed") {
            return { ok: true };
          }
          return null;
        },
        { ok: false, reason: "no_ack" },
        5_000,
      );
    },
    [runThreadAction],
  );

  const cancelTurn = useCallback(
    (agentId: string, threadId: string) =>
      runThreadAction(
        agentId,
        threadId,
        { type: "cancel", thread_id: threadId },
        (frame) => {
          const type = typeof frame.type === "string" ? frame.type : "";
          if (type === "turn.ended" || type === "done") return { ok: true };
          if (type === "turn_status" && frame.active === false) {
            return { ok: true };
          }
          if (type === "error") {
            return {
              ok: false,
              reason:
                typeof frame.message === "string" && frame.message.trim()
                  ? frame.message.trim()
                  : "error",
            };
          }
          return null;
        },
        { ok: false, reason: "no_ack" },
        4_000,
      ),
    [runThreadAction],
  );
  const ratePerMinute = useMemo(
    // ``nowTick`` moves the trailing window forward while idle.
    () => eventsPerMinute(events, nowTick),
    [events, nowTick],
  );

  const refresh = useCallback(() => {
    void loadActivity();
    setNowTick(Date.now());
  }, [loadActivity]);

  return {
    activity,
    sessions,
    ringSessions,
    events,
    offline,
    watchedThreads,
    ratePerMinute,
    ticks,
    links,
    sendMessage,
    cancelTurn,
    refresh,
  };
}

export { HOME_EVENT_LIMIT };
