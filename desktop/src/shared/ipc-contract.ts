/**
 * Shared IPC contract between main and preload. The renderer only ever sees the
 * typed ``window.octopDesktop`` bridge; raw ``ipcRenderer`` is never exposed.
 */

export interface ClientSettings {
  /** Launch at login / open at login. */
  launchAtLogin: boolean;
  /** Close-window behaviour: quit vs. keep in tray. */
  closeBehavior: "quit" | "tray";
  /**
   * Device light/dark preference shared with the Dashboard (`system` follows
   * the OS). The Early Window paints from this; the page reports changes back.
   */
  themeBackground: "system" | "light" | "dark";
  /** Whether the shell update check should follow the stable channel only. */
  stableOnly: boolean;
  /** The two-step first-run guide has been seen (or skipped). */
  onboardingCompleted: boolean;
  /**
   * Data root the guide was completed on. A different ``HAPPYCLAW_HOME`` counts as
   * a fresh install and shows the guide again; null means "adopt on next boot".
   */
  onboardingHome: string | null;
}

/**
 * Everything the shell knows about this machine. Single-user build: there is
 * exactly one data root and no account chooser behind it.
 */
export interface DesktopInfo {
  appVersion: string;
  platform: "darwin" | "win32" | "linux";
  /** HAPPYCLAW_HOME — database, credentials, workspaces and the log all live here. */
  dataDirectory: string;
  /** Stored backup archives under the data root. */
  backupsDirectory: string;
  logFile: string;
  /** Human-readable accelerators shown by the first-run guide. */
  shortcuts: {
    showWindow: string;
    newSession: string;
  };
  singleUser: true;
}

export interface PlatformInfo {
  platform: "darwin" | "win32" | "linux";
  arch: string;
  isDesktop: true;
}

export interface UpdateCheckResult {
  status: "update-available" | "up-to-date" | "error";
  currentVersion: string;
  latestVersion: string | null;
  error: string | null;
}

/** A JWT minted by the shell from the stored device credential. */
export interface IssuedSession {
  access_token: string;
  expires_in: number;
}

/**
 * Loopback WebSocket relay (§5.2). A custom scheme cannot carry a handshake,
 * so the page dials this instead of ``octop://app/api/…``.
 */
export interface WsRelayEndpoint {
  /** ``ws://127.0.0.1:<port>/<token>`` — append ``/api/…`` to it. */
  baseUrl: string;
  /** Random per-launch path segment; the relay refuses every other path. */
  token: string;
}

/** Theme for the *native* window controls (traffic lights / caption buttons). */
export interface WindowChromeTheme {
  /** Resolved mode the page is showing. */
  mode: "light" | "dark";
  /** The user's preference; kept so "system" keeps following the OS. */
  scheme?: "system" | "light" | "dark";
}

export const IPC_CHANNELS = {
  getPlatformInfo: "octop:get-platform-info",
  openDirectoryPicker: "octop:open-directory-picker",
  openFilePicker: "octop:open-file-picker",
  onBackendReady: "octop:backend-ready",
  windowChromeTheme: "octop:window-chrome-theme",
  windowChromeFullscreen: "octop:window-chrome-fullscreen",
  clientSettingsGet: "octop:client-settings:get",
  clientSettingsSet: "octop:client-settings:set",
  wsEndpoint: "octop:ws-endpoint",
  checkForUpdates: "octop:check-for-updates",
  /** Page already confirmed. No arguments: the shell re-selects the release. */
  installUpdate: "octop:install-update",
  windowsMenuModel: "octop:windows-menu:model",
  windowsMenuInvoke: "octop:windows-menu:invoke",
  /** Linux square caption buttons. No-op on the other platforms. */
  windowMinimize: "octop:window-minimize",
  windowToggleMaximize: "octop:window-toggle-maximize",
  windowClose: "octop:window-close",
  windowIsMaximized: "octop:window-is-maximized",
  windowMaximized: "octop:window-maximized",
  sessionRegister: "octop:session:register",
  sessionRenew: "octop:session:renew",
  sessionRevoke: "octop:session:revoke",
  desktopInfo: "octop:desktop-info",
  openDataDirectory: "octop:open-data-directory",
  openOnboarding: "octop:open-onboarding",
  /** Renderer reports whether it holds unsaved work, so quitting can confirm. */
  unsavedContent: "octop:unsaved-content",
  /** Global accelerator asked for a fresh conversation. */
  newSessionShortcut: "octop:shortcut:new-session",
} as const;
