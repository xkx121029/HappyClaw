import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAgent } from "../../context/AgentContext";
import { baoApi, type BaoTask } from "../../api/modules/bao";
import {
  connectorPairApi,
  type PairingRequest,
} from "../../api/modules/connectorPair";
import { hitlPendingApi } from "../../api/modules/hitlPending";
import { buildDashboardNotifyWsUrl } from "../../api/modules/wsNotifications";
import {
  countInbox,
  hitlItem,
  isOpen,
  mergeInbox,
  pairingItem,
  patchInbox,
  reconcileInbox,
  sortInbox,
  taskItem,
  type InboxCounts,
  type InboxItem,
} from "./homeInboxModel";

const TASK_LIMIT = 80;
const PING_MS = 25_000;
const PUSH_DEBOUNCE_MS = 800;

interface InboxState {
  items: InboxItem[];
  counts: InboxCounts;
  loading: boolean;
  /** True while the notification socket is down. */
  offline: boolean;
  /** Short description of the last partial load failure, or null. */
  error: string | null;
  refresh: () => void;
  approvePairing: (item: InboxItem) => Promise<void>;
  rejectPairing: (item: InboxItem) => Promise<void>;
  answerQuestion: (item: InboxItem, message: string) => Promise<void>;
  ackTask: (item: InboxItem) => Promise<void>;
  followUpTask: (item: InboxItem, text: string) => Promise<void>;
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function taskNeedsInbox(task: BaoTask): boolean {
  if (task.status === "done" || task.status === "failed") {
    return !task.acknowledged_at;
  }
  return task.status === "awaiting";
}

/**
 * Home inbox aggregation.
 *
 * Sources are the real stores only: connector pairing requests, the HITL
 * pending store and Bao's dispatch ledger. Realtime updates arrive on the
 * existing dashboard notification socket; there is no polling loop.
 */
export function useHomeInbox(): InboxState {
  const { agents } = useAgent();
  const [items, setItems] = useState<InboxItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [offline, setOffline] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const agentsRef = useRef(agents);
  agentsRef.current = agents;
  const hitlLoadedRef = useRef<Set<string>>(new Set());
  const pushTimerRef = useRef<number | null>(null);

  const loadPairing = useCallback(async () => {
    const data = await connectorPairApi.pending();
    const incoming = (data.requests ?? [])
      .filter((request) => request.status === "pending")
      .map((request) => pairingItem(request));
    const keys = new Set(incoming.map((item) => item.key));
    setItems((previous) =>
      reconcileInbox(
        mergeInbox(previous, incoming),
        new Set(["pairing"]),
        keys,
      ),
    );
  }, []);

  const loadHitl = useCallback(async (agentId: string) => {
    const data = await hitlPendingApi.list(agentId);
    const incoming = data.items.map(hitlItem);
    const keys = new Set(incoming.map((item) => item.key));
    setItems((previous) => {
      const merged = mergeInbox(previous, incoming);
      // A pending row this agent no longer reports was answered elsewhere or
      // expired; keep the row but mark it settled instead of dropping it.
      return merged.map((item) => {
        if (
          (item.source === "question" || item.source === "approval") &&
          item.agentId === agentId &&
          isOpen(item) &&
          !keys.has(item.key)
        ) {
          return { ...item, state: "expired" };
        }
        return item;
      });
    });
  }, []);

  const loadTasks = useCallback(async () => {
    const data = await baoApi.tasks(TASK_LIMIT, false);
    const tasks = data.tasks ?? [];
    const incoming = tasks.filter(taskNeedsInbox).map(taskItem);
    const keys = new Set(incoming.map((item) => item.key));
    setItems((previous) => {
      // Awaiting tasks are usually the Bao view of a HITL pause; keep only
      // the ones the pending-question list does not already cover.
      const hitlThreads = new Set(
        previous
          .filter(
            (item) =>
              (item.source === "question" || item.source === "approval") &&
              isOpen(item) &&
              item.threadId,
          )
          .map((item) => item.threadId),
      );
      const filtered = incoming.filter(
        (item) =>
          item.task?.status !== "awaiting" ||
          !item.threadId ||
          !hitlThreads.has(item.threadId),
      );
      return reconcileInbox(
        mergeInbox(previous, filtered),
        new Set(["task"]),
        keys,
      );
    });
  }, []);

  const refresh = useCallback(() => {
    setLoading(true);
    const agentIds = agentsRef.current.map((agent) => agent.agent_id);
    void Promise.allSettled([
      loadPairing(),
      loadTasks(),
      ...agentIds.map((agentId) => loadHitl(agentId)),
    ]).then((results) => {
      const failed = results.filter((result) => result.status === "rejected");
      setError(
        failed.length > 0
          ? messageOf(
              (failed[0] as PromiseRejectedResult).reason,
            )
          : null,
      );
      setLoading(false);
    });
  }, [loadHitl, loadPairing, loadTasks]);

  // Initial load. Agent-scoped questions arrive after the agent list resolves.
  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    for (const agent of agents) {
      if (hitlLoadedRef.current.has(agent.agent_id)) continue;
      hitlLoadedRef.current.add(agent.agent_id);
      void loadHitl(agent.agent_id).catch((cause) => {
        setError(messageOf(cause));
      });
    }
  }, [agents, loadHitl]);

  const scheduleTaskRefresh = useCallback(() => {
    if (pushTimerRef.current !== null) return;
    pushTimerRef.current = window.setTimeout(() => {
      pushTimerRef.current = null;
      void loadTasks().catch((cause) => setError(messageOf(cause)));
    }, PUSH_DEBOUNCE_MS);
  }, [loadTasks]);

  const handlerRef = useRef<(frame: Record<string, unknown>) => void>(() => {});
  handlerRef.current = (frame) => {
    const type = String(frame.type ?? "");
    if (type === "connector_pair_request") {
      const requestId = String(frame.requestId ?? "");
      if (!requestId) return;
      const request: PairingRequest = {
        requestId,
        code: String(frame.code ?? ""),
        status: "pending",
        deviceId: "",
        deviceName: String(frame.deviceName ?? ""),
        platform: String(frame.platform ?? ""),
        appVersion: String(frame.appVersion ?? ""),
        createdAtMs: Date.now(),
        expiresAtMs: Number(frame.expiresAtMs ?? 0),
        reviewUrl: String(frame.reviewUrl ?? ""),
      };
      setItems((previous) =>
        mergeInbox(previous, [pairingItem(request)]),
      );
      return;
    }
    if (type === "connector_pair_resolved") {
      const requestId = String(frame.requestId ?? "");
      const status = String(frame.status ?? "");
      if (!requestId) return;
      setItems((previous) =>
        patchInbox(previous, `pair:${requestId}`, {
          state:
            status === "approved"
              ? "approved"
              : status === "rejected"
              ? "rejected"
              : "expired",
        }),
      );
      return;
    }
    if (type === "hitl_pending") {
      const agentId = String(frame.agentId ?? "");
      if (agentId) {
        void loadHitl(agentId).catch((cause) => setError(messageOf(cause)));
      } else {
        for (const agent of agentsRef.current) {
          void loadHitl(agent.agent_id).catch(() => undefined);
        }
      }
      return;
    }
    if (type === "hitl_resolved") {
      const pendingId = String(frame.pendingId ?? "");
      if (!pendingId) return;
      setItems((previous) =>
        patchInbox(previous, `hitl:${pendingId}`, { state: "answered" }),
      );
      return;
    }
    if (type === "bao_task_update") {
      const task = frame.task as BaoTask | undefined;
      if (!task?.id) return;
      const item = taskItem(task);
      if (task.status === "running") {
        setItems((previous) =>
          patchInbox(previous, item.key, { state: "followed_up" }),
        );
        return;
      }
      if (!taskNeedsInbox(task)) return;
      setItems((previous) => mergeInbox(previous, [item]));
      return;
    }
    if (type === "dashboard_push") {
      scheduleTaskRefresh();
    }
  };

  useEffect(() => {
    let disposed = false;
    let socket: WebSocket | null = null;
    let retry = 0;
    let retryTimer = 0;
    let pingTimer = 0;

    const connect = () => {
      if (disposed) return;
      const next = new WebSocket(buildDashboardNotifyWsUrl());
      socket = next;
      next.onopen = () => {
        if (disposed) return;
        retry = 0;
        setOffline(false);
        pingTimer = window.setInterval(() => {
          if (next.readyState === WebSocket.OPEN) {
            next.send(JSON.stringify({ type: "ping" }));
          }
        }, PING_MS);
      };
      next.onmessage = (event) => {
        try {
          const frame = JSON.parse(String(event.data)) as Record<string, unknown>;
          if (frame && typeof frame === "object") handlerRef.current(frame);
        } catch {
          // Ignore non-JSON frames; the socket stays usable.
        }
      };
      next.onerror = () => next.close();
      next.onclose = () => {
        if (pingTimer) {
          window.clearInterval(pingTimer);
          pingTimer = 0;
        }
        if (disposed) return;
        setOffline(true);
        const wait = Math.min(30_000, 1_000 * 2 ** retry);
        retry += 1;
        retryTimer = window.setTimeout(connect, wait);
      };
    };

    connect();
    return () => {
      disposed = true;
      if (retryTimer) window.clearTimeout(retryTimer);
      if (pingTimer) window.clearInterval(pingTimer);
      socket?.close();
    };
  }, []);

  useEffect(
    () => () => {
      if (pushTimerRef.current !== null) {
        window.clearTimeout(pushTimerRef.current);
      }
    },
    [],
  );

  const approvePairing = useCallback(async (item: InboxItem) => {
    if (!item.pairing) return;
    try {
      await connectorPairApi.approve(item.pairing);
      setItems((previous) =>
        patchInbox(previous, item.key, { state: "approved", error: undefined }),
      );
    } catch (cause) {
      setItems((previous) =>
        patchInbox(previous, item.key, { error: messageOf(cause) }),
      );
    }
  }, []);

  const rejectPairing = useCallback(async (item: InboxItem) => {
    if (!item.pairing) return;
    try {
      await connectorPairApi.reject(item.pairing);
      setItems((previous) =>
        patchInbox(previous, item.key, { state: "rejected", error: undefined }),
      );
    } catch (cause) {
      setItems((previous) =>
        patchInbox(previous, item.key, { error: messageOf(cause) }),
      );
    }
  }, []);

  const answerQuestion = useCallback(
    async (item: InboxItem, message: string) => {
      if (!item.agentId || !item.threadId || !item.pendingId) return;
      setItems((previous) =>
        patchInbox(previous, item.key, {
          state: "answered",
          answer: message,
          error: undefined,
        }),
      );
      try {
        await hitlPendingApi.answer({
          agentId: item.agentId,
          threadId: item.threadId,
          pendingId: item.pendingId,
          message,
        });
      } catch (cause) {
        setItems((previous) =>
          patchInbox(previous, item.key, {
            state: "pending",
            answer: undefined,
            error: messageOf(cause),
          }),
        );
      }
    },
    [],
  );

  const ackTask = useCallback(async (item: InboxItem) => {
    if (!item.task) return;
    try {
      await baoApi.ackTasks([item.task.id]);
      setItems((previous) =>
        patchInbox(previous, item.key, {
          state: "acknowledged",
          error: undefined,
        }),
      );
    } catch (cause) {
      setItems((previous) =>
        patchInbox(previous, item.key, { error: messageOf(cause) }),
      );
    }
  }, []);

  const followUpTask = useCallback(async (item: InboxItem, text: string) => {
    const task = item.task;
    if (!task || !text.trim()) return;
    try {
      await baoApi.dispatch({
        agent_id: task.agent_id,
        thread_id: task.thread_id,
        text: text.trim(),
        source: "home_inbox",
      });
      await baoApi.ackTasks([task.id]).catch(() => undefined);
      setItems((previous) =>
        patchInbox(previous, item.key, {
          state: "followed_up",
          reply: text.trim(),
          error: undefined,
        }),
      );
    } catch (cause) {
      setItems((previous) =>
        patchInbox(previous, item.key, { error: messageOf(cause) }),
      );
    }
  }, []);

  const sorted = useMemo(() => sortInbox(items), [items]);
  const counts = useMemo(() => countInbox(items), [items]);

  return {
    items: sorted,
    counts,
    loading,
    offline,
    error,
    refresh,
    approvePairing,
    rejectPairing,
    answerQuestion,
    ackTask,
    followUpTask,
  };
}
