import { request } from "../request";

/** 手机端连接器：待批准的配对请求与已配对设备。 */

export interface PendingPairRequest {
  requestId: string;
  code: string;
  status: string;
  deviceId: string;
  deviceName: string;
  platform: string;
  appVersion: string;
  createdAtMs: number;
  expiresAtMs: number;
  /** 服务端生成的一次性审核链接，token 在 query 里。 */
  reviewUrl: string;
}

export interface PairedPhone {
  deviceId: string;
  name: string;
  platform: string;
  appVersion: string;
  createdAtMs: number;
  lastSeenAtMs: number;
  userId: number;
}

/** 手机端通过连接器回复到 dashboard 的消息。 */
export interface PhoneReply {
  id: string;
  deviceId: string;
  deviceName: string;
  text: string;
  receivedAtMs: number;
}

/**
 * 审核 token 只存在于 reviewUrl 的 query 里；手机端拿不到 dashboard 的
 * 登录态，所以服务端用「持有链接」来代替鉴权。这里复用同一个约定。
 */
function reviewToken(reviewUrl: string): string {
  if (!reviewUrl) return "";
  try {
    return new URL(reviewUrl, window.location.origin).searchParams.get("token") ?? "";
  } catch {
    return "";
  }
}

export const connectorPairingApi = {
  pending: () =>
    request<{ ok: boolean; requests: PendingPairRequest[] }>(
      "/connector/pair/pending",
      { cache: "no-store" },
    ),

  approve: (item: PendingPairRequest) =>
    request<{ ok: boolean; status?: string; deviceId?: string; message?: string }>(
      `/connector/pair/${encodeURIComponent(item.requestId)}/approve`,
      {
        method: "POST",
        body: JSON.stringify({ token: reviewToken(item.reviewUrl) }),
      },
    ),

  reject: (item: PendingPairRequest, reason = "用户在网页端拒绝") =>
    request<{ ok: boolean; status?: string; message?: string }>(
      `/connector/pair/${encodeURIComponent(item.requestId)}/reject`,
      {
        method: "POST",
        body: JSON.stringify({
          token: reviewToken(item.reviewUrl),
          reason,
        }),
      },
    ),

  devices: () =>
    request<{ ok: boolean; devices: PairedPhone[] }>("/connector/devices", {
      cache: "no-store",
    }),

  replies: (limit = 50) =>
    request<{ ok: boolean; replies: PhoneReply[] }>(
      `/connector/replies?limit=${limit}`,
      { cache: "no-store" },
    ),

  pushMessage: (text: string) =>
    request<{ ok: boolean; delivered: number; online: number }>(
      "/connector/messages",
      { method: "POST", body: JSON.stringify({ text }) },
    ),

  revokeDevice: (deviceId: string) =>
    request<{ ok: boolean; deviceId: string }>(
      `/connector/devices/${encodeURIComponent(deviceId)}`,
      { method: "DELETE" },
    ),
};
