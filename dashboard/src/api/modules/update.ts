import { request } from "../request";

export interface UpdateStatus {
  current_version: string;
  latest_version: string | null;
  has_update: boolean;
  is_editable: boolean;
  /** Non-null when the process was launched via `octop service start` (systemd or launchd). */
  service_mode: "systemd" | "launchd" | null;
  /** True when Octop is spawned by the desktop shell (or ``OCTOP_DESKTOP=1``). */
  desktop?: boolean;
  error: string | null;
  /** Stable error code (e.g. "pypi_unreachable") for localized UI messages; null on success. */
  error_code: string | null;
  /** Mirror that served the version info (null/`pypi.org` = official source). */
  source: string | null;
  last_check_time: string | null;
  /** Markdown changelog for latest_version, null if not available. */
  release_notes: string | null;
  /** When true (default), automatic checks ignore pre-releases. */
  stable_only?: boolean;
  /** True when latest_version is a PEP 440 pre-release. */
  latest_is_prerelease?: boolean;
}

export interface UpgradeStarted {
  task_id: string;
  status: "started";
}

export interface UpgradeProgress {
  task_id: string;
  status: "running" | "complete" | "error";
  stage: string | null;
  percent: number | null;
  new_version: string | null;
  success: boolean | null;
  error: string | null;
  mirror_errors: string[] | null;
}

export interface RestartResponse {
  status: "restarting";
  service_mode: string;
}

export interface ReleaseArtifact {
  platform: string;
  arch: string;
  kind: string | null;
  filename: string;
  url: string;
  sha256: string;
  size_bytes: number;
}

/** Read-only result of GET /update/check (published release manifest). */
export interface ReleaseCheckResult {
  ok: boolean;
  configured: boolean;
  current_version: string;
  channel: string;
  latest_version: string | null;
  has_update: boolean;
  supported: boolean;
  minimum_supported_version: string | null;
  release_notes: string | null;
  published_at: string | null;
  product: string | null;
  artifacts: ReleaseArtifact[];
  source: string | null;
  cached: boolean;
  stale: boolean;
  checked_at: string;
  error_code: string | null;
  error: string | null;
}

export const updateApi = {
  getUpdateStatus: () => request<UpdateStatus>("/update/status"),
  checkForUpdates: () =>
    request<UpdateStatus>("/update/check", { method: "POST" }),
  checkReleaseFeed: (params: {
    currentVersion?: string | null;
    channel: string;
  }) => {
    const query = new URLSearchParams({ channel: params.channel });
    if (params.currentVersion)
      query.set("current_version", params.currentVersion);
    return request<ReleaseCheckResult>(`/update/check?${query.toString()}`);
  },
  patchSettings: (stableOnly: boolean) =>
    request<UpdateStatus & { stable_only: boolean }>("/update/settings", {
      method: "PATCH",
      body: JSON.stringify({ stable_only: stableOnly }),
    }),
  triggerUpgrade: (version?: string | null) =>
    request<UpgradeStarted>("/update/upgrade", {
      method: "POST",
      body: JSON.stringify({ version: version || null }),
    }),
  getUpgradeProgress: (taskId: string) =>
    request<UpgradeProgress>(
      `/update/progress?task_id=${encodeURIComponent(taskId)}`,
    ),
  restartService: () =>
    request<RestartResponse>("/update/restart", { method: "POST" }),
};
