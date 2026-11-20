import { getApiUrl } from "../config";
import { getAuthToken, request } from "../request";

export type DeviceLinkState =
  | "idle"
  | "connecting"
  | "online"
  | "offline"
  | "unpaired";

export interface DeviceLinkError {
  code: string;
  message: string;
  retryable: boolean;
}

export interface CommandRecord {
  command_id: string;
  name: string;
  ok: boolean;
  duration_ms: number;
  started_at: number;
  error: DeviceLinkError | null;
  replayed: boolean;
  artifact: string | null;
  result: Record<string, unknown> | null;
}

export interface DeviceLinkStatus {
  status: DeviceLinkState;
  host: string;
  port: number;
  device_name: string | null;
  device_fingerprint: string | null;
  client_id: string | null;
  connected_at: number | null;
  last_heartbeat_at: number | null;
  latency_ms: number | null;
  current_action: string | null;
  next_retry_at: number | null;
  reason: string | null;
  reconnect_count: number;
  commands_total: number;
  commands_failed: number;
  paired: boolean;
  recent_commands: CommandRecord[];
}

export interface TodayConfig {
  enabled?: boolean;
  intervalSeconds?: number;
  notificationConsent?: boolean;
  notificationStorage?: string;
  activeHours?: { start?: string; end?: string };
  [key: string]: unknown;
}

export interface TodayItem {
  id?: string;
  kind?: string;
  source?: string;
  title?: string;
  text?: string;
  at?: number;
  importance?: number;
  [key: string]: unknown;
}

export interface TodaySnapshot {
  config: TodayConfig;
  snapshot: {
    updatedAt?: number | null;
    day?: string | null;
    items?: TodayItem[];
    permissions?: Record<string, unknown>;
  };
}

export interface CommandReply {
  ok: boolean;
  command_id: string;
  result?: Record<string, unknown> | null;
  error?: DeviceLinkError | null;
  replayed?: boolean;
  duration_ms?: number;
  artifact?: string | null;
}

export interface CommandSpec {
  name: string;
  summary: string;
  params: Record<string, string>;
}

export interface DeviceLinkEvent {
  seq: number;
  kind: string;
  at: number;
  data: Record<string, unknown>;
}

const BASE = "/device-link";

export const deviceLinkApi = {
  status: () => request<DeviceLinkStatus>(`${BASE}/status`, { cache: "no-store" }),

  today: () =>
    request<TodaySnapshot>(`${BASE}/today`, { cache: "no-store" }),

  updateToday: (patch: Record<string, unknown>) =>
    request<{ config: TodayConfig }>(`${BASE}/today`, {
      method: "PUT",
      body: JSON.stringify(patch),
    }),

  catalog: () =>
    request<{ commands: CommandSpec[] }>(`${BASE}/commands`, {
      cache: "no-store",
    }),

  pair: (host: string, port: number, code: string, clientName = "HappyClaw") =>
    request<{ ok: boolean; device_name: string; client_id: string }>(
      `${BASE}/pair`,
      {
        method: "POST",
        body: JSON.stringify({ host, port, code, client_name: clientName }),
      },
    ),

  connect: (host?: string, port?: number) =>
    request<{ ok: boolean; host: string; port: number }>(`${BASE}/connect`, {
      method: "POST",
      body: JSON.stringify({ host, port }),
    }),

  disconnect: () =>
    request<{ ok: boolean }>(`${BASE}/disconnect`, { method: "POST" }),

  command: (
    name: string,
    params: Record<string, unknown> = {},
    commandId?: string,
    timeoutMs?: number,
  ) =>
    request<CommandReply>(`${BASE}/command`, {
      method: "POST",
      body: JSON.stringify({
        name,
        params,
        command_id: commandId,
        timeout_ms: timeoutMs,
      }),
    }),

  screenshotUrl: (artifactPath: string) => {
    const filename = artifactPath.split(/[\\/]/).pop() ?? "";
    return getApiUrl(`${BASE}/screenshot/${encodeURIComponent(filename)}`);
  },

  /**
   * 订阅设备事件流。fetch + Authorization 头（EventSource 不能带 token）。
   * 返回取消函数。
   */
  streamEvents: (
    onStatus: (status: DeviceLinkStatus) => void,
    onEvent: (event: DeviceLinkEvent) => void,
    onStateChange?: (connected: boolean) => void,
  ) => {
    const controller = new AbortController();
    const token = getAuthToken();
    let settled = false;

    const run = async () => {
      try {
        const res = await fetch(getApiUrl(`${BASE}/events`), {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          signal: controller.signal,
        });
        if (!res.ok || !res.body) {
          onStateChange?.(false);
          return;
        }
        onStateChange?.(true);
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (!settled) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const blocks = buffer.split("\n\n");
          buffer = blocks.pop() ?? "";
          for (const block of blocks) {
            let eventName = "message";
            let data = "";
            for (const line of block.split("\n")) {
              if (line.startsWith("event:")) eventName = line.slice(6).trim();
              else if (line.startsWith("data:")) data += line.slice(5).trim();
            }
            if (!data) continue;
            try {
              const payload = JSON.parse(data);
              if (eventName === "status") onStatus(payload as DeviceLinkStatus);
              else if (eventName === "device") onEvent(payload as DeviceLinkEvent);
            } catch {
              /* 忽略无法解析的帧，保持流不断 */
            }
          }
        }
      } catch (err) {
        if ((err as Error).name !== "AbortError") {
          // 断流交给调用方退回轮询
        }
      } finally {
        onStateChange?.(false);
      }
    };
    void run();

    return () => {
      settled = true;
      controller.abort();
    };
  },
};
