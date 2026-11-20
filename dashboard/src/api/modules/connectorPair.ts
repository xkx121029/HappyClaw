import { request } from "../request";

/** One phone pairing request as reported by the connector store. */
export interface PairingRequest {
  requestId: string;
  code: string;
  status: string;
  deviceId: string;
  deviceName: string;
  platform: string;
  appVersion: string;
  createdAtMs: number;
  expiresAtMs: number;
  /** Review link; only this query string carries the decision token. */
  reviewUrl: string;
}

interface PairingListResponse {
  ok: boolean;
  requests: PairingRequest[];
}

interface PairingDecisionResponse {
  ok: boolean;
  status?: string;
  code?: string;
  message?: string;
}

/** The backend keeps the decision token in the review URL, not the payload. */
export function tokenFromReviewUrl(reviewUrl: string): string {
  if (!reviewUrl) return "";
  try {
    return new URL(reviewUrl, window.location.origin).searchParams.get("token") ?? "";
  } catch {
    return "";
  }
}

function assertOk(data: PairingDecisionResponse): void {
  if (data.ok) return;
  throw new Error(data.message || data.code || "pairing decision failed");
}

/**
 * Connector pairing API.
 *
 * This is the only frontend implementation of pairing approval: the Home
 * inbox and the connector entry both call these functions, so they read and
 * mutate the same server-side request state.
 */
export const connectorPairApi = {
  pending: () => request<PairingListResponse>("/connector/pair/pending"),

  approve: async (req: PairingRequest) => {
    const data = await request<PairingDecisionResponse>(
      `/connector/pair/${encodeURIComponent(req.requestId)}/approve`,
      {
        method: "POST",
        body: JSON.stringify({ token: tokenFromReviewUrl(req.reviewUrl) }),
      },
    );
    assertOk(data);
    return data;
  },

  reject: async (req: PairingRequest) => {
    const data = await request<PairingDecisionResponse>(
      `/connector/pair/${encodeURIComponent(req.requestId)}/reject`,
      {
        method: "POST",
        body: JSON.stringify({ token: tokenFromReviewUrl(req.reviewUrl) }),
      },
    );
    assertOk(data);
    return data;
  },
};
