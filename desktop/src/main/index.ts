import {
  app,
  BrowserWindow,
  dialog,
  globalShortcut,
  ipcMain,
  Menu,
  MenuItem,
  nativeImage,
  net,
  protocol,
  screen,
  shell,
  Tray,
  type NativeImage,
  type WebContents,
} from "electron";
import { execFileSync, spawn } from "node:child_process";
import { constants as fsConstants, existsSync, promises as fs } from "node:fs";
import { type as osType, release as osRelease } from "node:os";
import { dirname, join } from "node:path";
import { pathToFileURL } from "node:url";

import {
  IPC_CHANNELS,
  type ClientSettings,
  type DesktopInfo,
  type IssuedSession,
  type PlatformInfo,
  type UpdateCheckResult,
} from "../shared/ipc-contract";
import { createManualBackup } from "./backup/manual-backup";
import { inspectBeforeQuit, quitPrompt, type QuitReason } from "./quit-guard";
import {
  chatLocation,
  readSessionSnapshot,
  restoreUrl,
  routeOnlyUrl,
  sessionIdOf,
  writeSessionSnapshot,
  type SessionSnapshot,
} from "./session/session-restore";
import { resolveAppVersion } from "./app-version";
import { desktopLog, installDesktopLog } from "./log/desktop-log";
import { DeviceCredentialStore } from "./session/device-credential";
import { DeviceSessionClient } from "./session/device-session";
import { safeStorageCipher, warnIfKeychainUnavailable } from "./session/safe-storage-cipher";
import { ClientSettingsStore, defaultClientSettingsPath, isOnboardingCompletedFor } from "./storage/client-settings";
import { readLoginShellEnv, resolveOctopHome } from "./supervisor/shell-env";
import { reserveRandomPort } from "./supervisor/random-port";
import {
  bundledDashboardDir,
  classifyRuntime,
  portableZipName,
  extractPortableZip,
  installedOnedirBackendDir,
  installedRuntimeDir,
  onedirDashboardDir,
  type BundledPortable,
  type LocalRuntime,
} from "./supervisor/runtime-extractor";
import { compareVersions } from "./supervisor/version";
import { sha256File } from "./supervisor/sha256";
import { buildSidecarEnv } from "./supervisor/process-tree";
import { resolveHealthTimeoutMs } from "./supervisor/health";
import { SidecarSupervisor } from "./supervisor/sidecar";
import { contentTypeFor, isExternalLink, resolveDashboardFile, resolveStaticPath } from "./protocol/static-handler";
import { isApiPath, sanitizeForwardHeaders, toBackendUrl } from "./protocol/stream-proxy";
import { WsRelay } from "./protocol/ws-relay";
import {
  channelHeadTag,
  manifestFromDownloadsResponse,
  platformAssetKey,
  selectRelease,
  type DownloadManifest,
  type SelectedRelease,
} from "./update/update-coordinator";
import { downloadToFile } from "./update/download";
import { installUpdate, type InstallOutcome, type InstallerKind } from "./update/installer";
import {
  dashboardDevOrigin,
  readDashboardDev,
  startDashboardDevServer,
  stopDashboardDevServer,
} from "./dev/dashboard-dev-server";
import {
  formatAboutDetail,
  formatAboutOs,
  resolveGitStamp,
  windowsInstallScope,
} from "./windows/about-info";
import {
  windowsApplicationMenu,
  windowsMenuCommandId,
  windowsMenuModel,
  type WindowsMenuCommandId,
} from "./windows/app-menu";
import { createEarlyWindow } from "./windows/early-window";
import { createMainWindow, installDashboardGuards } from "./windows/main-window";
import type { EarlyWindow } from "./windows/early-window";
import { createOnboardingWindow } from "./windows/onboarding-window";
import { isWindowOnScreen, presentWindows, shouldKeepWindowOnClose } from "./windows/present";
import { MIN_WINDOW_SIZE } from "./windows/size";
import { writeLinuxAutostart } from "./windows/auto-launch";
import {
  readWindowState,
  usableWindowBounds,
  writeWindowState,
} from "./windows/window-state";
import {
  shouldInstallSystemTray,
  trayExecutableFallback,
  trayIconCandidates,
  trayIconImagePath,
  trayMenuLabels,
  WINDOWS_APP_USER_MODEL_ID,
} from "./windows/tray";
import {
  applyNativeTheme,
  applyWindowChromeTheme,
  dashboardEntryUrl,
  PACKAGED_APP_ORIGIN,
  parseWindowChromeTheme,
  resolveWindowChromeTheme,
  usesCaptionOverlay,
  windowBackground,
} from "./windows/chrome";

const UPDATE_ENDPOINT = "https://octop.cloud/api/downloads";
// Packaged renderer origin. Local dev replaces this with the Vite origin before
// the relay starts, and the relay accepts upgrades only from that origin (§5.2).
const WINDOW_ORIGIN = "octop://app";
const PRELOAD_PATH = join(__dirname, "../preload/index.js");
const SPLASH_PATH = join(__dirname, "../renderer/splash.html");
const ERROR_PATH = join(__dirname, "../renderer/error.html");
const ONBOARDING_PATH = join(__dirname, "../renderer/onboarding.html");

/** Global accelerators. `CommandOrControl` maps to ⌘ on macOS and Ctrl elsewhere. */
const SHORTCUT_SHOW_WINDOW = "CommandOrControl+Shift+H";
const SHORTCUT_NEW_SESSION = "CommandOrControl+Shift+N";

interface PortableManifestFile {
  version: string;
  sha256: string;
}

let supervisor: SidecarSupervisor | null = null;
let settingsStore: ClientSettingsStore;
// §7 accounts: renews the Dashboard session without a password. Registered by
// the renderer once it holds a JWT; used whenever that JWT has expired.
let deviceSession: DeviceSessionClient | null = null;
// Resolved after `whenReady` — `app.getVersion()` must not run at module load.
let appVersion = "";
// §6.3 step 1: once an install is under way the proxy answers 503 so no new API
// request is admitted while Python shuts down.
let apiAdmissionClosed = false;
let updateInFlight = false;
let quitting = false;
// Default matches ClientSettingsStore. Boot and the settings IPC keep it current.
let closeBehavior: "quit" | "tray" = "tray";
// Windows notification area. Null until the icon is actually on screen.
let tray: Tray | null = null;
// Kept for the life of the tray. A resized bitmap is dropped from the
// notification area once the window hides, and a collected image goes blank.
let trayIcon: NativeImage | null = null;
// Set once the Dashboard has opened, so a later Dock click can open it again.
let dashboardOrigin: string | null = null;
// Current loopback port of the sidecar. Read per request (not captured), so a
// restart after a failed install can hand the proxy a new port.
let backendPort = 0;
// Single-user data root. Resolved once at boot and shared with the guide.
let octopHomePath = "";
// The Dashboard window (not the guide). Global shortcuts target it.
let dashboardWindow: BrowserWindow | null = null;
let onboardingWindow: BrowserWindow | null = null;
// Geometry and crash-recovery files live beside the client settings.
let windowStatePath = "";
let sessionSnapshotPath = "";
let lastDashboardUrl: string | null = null;
// A launch that reads an unclean snapshot keeps it here until the first window
// picks an entry URL; a second window must not replay the recovery.
let pendingRecovery: SessionSnapshot | null = null;
// Renderer-reported unsaved work, used by the quit guard.
let rendererUnsaved = false;
// User quits may ask; updates and signals must not block the exit path.
let quitReason: QuitReason = "user";
let quitGuardRunning = false;
let quitConfirmed = false;
let backupInFlight = false;
// §5.2: WebSockets cannot ride the custom scheme, so the page dials this relay.
let wsRelay: WsRelay | null = null;
// Everything needed to (re)spawn the sidecar for this launch. Two install
// shapes are supported: a green Python runtime (`launch.py` + `runtime/`) and
// the PyInstaller onedir build (`octop.exe` + `_internal/`).
type BackendLaunch =
  | {
      kind: "python";
      interpreter: string;
      launchScript: string;
      cwd: string;
      octopHome: string;
      portableDir: string;
    }
  | {
      kind: "onedir";
      executable: string;
      cwd: string;
      octopHome: string;
    };
let backend: BackendLaunch | null = null;

// A custom scheme used as the renderer origin must be declared privileged
// BEFORE the app is ready, otherwise `octop://app/` is not treated as a
// standard/secure origin and fetch/XHR/CORS break.
protocol.registerSchemesAsPrivileged([
  {
    scheme: "octop",
    privileges: {
      standard: true,
      secure: true,
      supportFetchAPI: true,
      stream: true,
      corsEnabled: true,
    },
  },
]);

function resourcesRoot(): string {
  return app.isPackaged ? process.resourcesPath : join(__dirname, "../../resources");
}

function dashboardRoot(launch: BackendLaunch): string {
  const override = (process.env.OCTOP_DASHBOARD_DIR ?? "").trim();
  if (override) return override;
  // The onedir backend already carries the built Dashboard under _internal,
  // so the installer does not ship a second copy of the same files.
  return launch.kind === "onedir"
    ? onedirDashboardDir(launch.cwd)
    : bundledDashboardDir(launch.portableDir);
}

/** Map to the green-pack naming used by desktop/portable (`darwin-arm64`, …). */
function portablePlatformTag(): string {
  const arch = process.arch === "arm64" ? "arm64" : "amd64";
  if (process.platform === "darwin") return `darwin-${arch}`;
  if (process.platform === "win32") return `windows-${arch}`;
  return `linux-${arch}`;
}

function portableZipPath(): string {
  // CI places one zip at resources/portable.
  return join(resourcesRoot(), "portable", portableZipName(portablePlatformTag(), appVersion));
}

async function readBundledPortable(): Promise<BundledPortable> {
  const manifest = JSON.parse(
    await fs.readFile(join(resourcesRoot(), "portable", "portable-version.json"), "utf8"),
  ) as PortableManifestFile;
  return { version: manifest.version, sha256: manifest.sha256 };
}

async function readLocalRuntime(octopHome: string): Promise<LocalRuntime> {
  const versionPath = join(octopHome, "portable", "version.json");
  let version: string | null = null;
  try {
    const raw = JSON.parse(await fs.readFile(versionPath, "utf8")) as { version?: unknown };
    version = typeof raw.version === "string" ? raw.version : null;
  } catch {
    version = null;
  }
  const interpreterPath = join(octopHome, "portable", "runtime", process.platform === "win32" ? "python.exe" : "bin/python3");
  let interpreterExists = false;
  try {
    // X_OK, not F_OK. A previous extract could leave `python3` as a mode-0666
    // text file where the archive stored a symlink. The path exists, spawn
    // fails with EACCES, and a same-version launch would otherwise skip
    // extraction forever. On Windows X_OK is the same check as F_OK.
    await fs.access(interpreterPath, fsConstants.X_OK);
    interpreterExists = true;
  } catch {
    interpreterExists = false;
  }
  return { version, interpreterExists };
}

/**
 * The one product version (shell + Dashboard + runtime share a release). Read
 * the bundled portable manifest first, then the dev runtime, and only then fall
 * back to `package.json` — see `app-version.ts` for why the placeholder there
 * must not win.
 */
async function resolveProductVersion(): Promise<string> {
  return resolveAppVersion({
    readBundled: async () => (await readBundledPortable()).version,
    readDevRuntime: async () => {
      const dir = (process.env.OCTOP_PORTABLE_DIR ?? "").trim();
      if (!dir) return null;
      const raw = JSON.parse(await fs.readFile(join(dir, "version.json"), "utf8")) as {
        version?: unknown;
      };
      return typeof raw.version === "string" ? raw.version : null;
    },
    readPackage: () => app.getVersion(),
  });
}

async function writeLocalVersion(octopHome: string, version: string): Promise<void> {
  const dir = join(octopHome, "portable");
  await fs.mkdir(dir, { recursive: true });
  await fs.writeFile(join(dir, "version.json"), JSON.stringify({ version, sha256: "" }, null, 2), "utf8");
}

function registerProtocol(staticRootDir: string): void {
  protocol.handle("octop", async (request) => {
    const url = new URL(request.url);
    const pathname = url.pathname;

    if (isApiPath(pathname)) {
      if (apiAdmissionClosed) return new Response("update in progress", { status: 503 });
      const target = toBackendUrl(backendPort, pathname, url.search);
      const headers = sanitizeForwardHeaders(request.headers);
      headers["x-octop-proxy"] = "1";
      return net.fetch(target, {
        method: request.method,
        headers,
        body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
        // @ts-expect-error duplex is required for streaming request bodies in undici
        duplex: "half",
      });
    }

    // Escape stays forbidden. A client route with no file falls back to
    // index.html; otherwise View → Reload of /chat returns an empty page.
    if (!resolveStaticPath(staticRootDir, pathname)) {
      return new Response("forbidden", { status: 403 });
    }
    const filePath = resolveDashboardFile(staticRootDir, pathname, existsSync);
    if (!filePath) return new Response("not found", { status: 404 });
    // Serve via file URL so large assets stream instead of buffering in memory.
    return net.fetch(pathToFileURL(filePath).toString()).then((res) => {
      const out = new Response(res.body, { status: res.status, headers: res.headers });
      if (!out.headers.get("content-type")) out.headers.set("content-type", contentTypeFor(filePath));
      return out;
    });
  });
}

async function fetchUpdateManifest(): Promise<{ manifest: DownloadManifest; stableOnly: boolean }> {
  const settings = settingsStore.load();
  const res = await net.fetch(UPDATE_ENDPOINT, { cache: "no-store" });
  if (!res.ok) throw new Error(`downloads endpoint returned ${res.status}`);
  return {
    manifest: manifestFromDownloadsResponse(await res.json()),
    stableOnly: settings.stableOnly,
  };
}

async function resolveSelectedRelease(): Promise<SelectedRelease | null> {
  const { manifest, stableOnly } = await fetchUpdateManifest();
  return selectRelease(
    manifest,
    appVersion,
    platformAssetKey(process.platform, process.arch),
    stableOnly,
  );
}

function errorMessageOf(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/** A JWT the shell will forward: non-empty, bounded, nothing else assumed. */
function isUsableAccessToken(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= 4096;
}

async function showShellMessage(
  win: BrowserWindow | null,
  message: string,
  detail: string,
): Promise<void> {
  const options = { type: "info" as const, buttons: ["好"], message, detail, noLink: true };
  if (win) await dialog.showMessageBox(win, options);
  else await dialog.showMessageBox(options);
}

async function showShellError(
  win: BrowserWindow | null,
  message: string,
  detail: string,
): Promise<void> {
  const options = {
    type: "error" as const,
    buttons: ["好"],
    message,
    detail,
    noLink: true,
  };
  if (win) await dialog.showMessageBox(win, options);
  else await dialog.showMessageBox(options);
}

/** Temp staging area for installers — never inside OCTOP_HOME (user data). */
function updateDownloadDir(): string {
  return join(app.getPath("temp"), "octop-update");
}

async function handOffToInstaller(kind: InstallerKind, path: string): Promise<void> {
  if (kind === "appimage") await fs.chmod(path, 0o755);
  if (process.platform === "win32" && (kind === "exe" || kind === "msi")) {
    // NSIS/MSI must replace the running shell: start the installer detached and
    // let this process exit right after (§6.3 step 3).
    spawn(path, [], { detached: true, stdio: "ignore" }).unref();
    return;
  }
  const failure = await shell.openPath(path);
  if (failure) throw new Error(failure);
}

/** Stop Python cleanly and restart it when the installer never took over. */
async function restartBackend(win: BrowserWindow | null): Promise<void> {
  apiAdmissionClosed = false;
  const ready = await startBackend();
  if (ready) win?.webContents.reload();
}

async function runShellUpdate(
  win: BrowserWindow | null,
  selected: SelectedRelease,
): Promise<InstallOutcome> {
  updateInFlight = true;
  try {
    const dir = updateDownloadDir();
    // Start from an empty staging dir so an aborted earlier attempt cannot be
    // mistaken for (or re-used as) this download.
    await fs.rm(dir, { recursive: true, force: true });
    await fs.mkdir(dir, { recursive: true });
    return await installUpdate(selected, {
      download: async (plan) => {
        const dest = join(dir, plan.filename);
        await downloadToFile(plan.url, dest, net.fetch, {
          onProgress: (received, total) => {
            if (total > 0) win?.setProgressBar(received / total);
          },
        });
        return dest;
      },
      // §6.1 assets carry no digest; the URL is already pinned to https on
      // download.octop.cloud by isValidAssetUrl() before it reaches this point.
      verify: async () => true,
      stopSidecar: async () => {
        // §6.3 step 1 — refuse new API admissions, then ask Python to exit.
        apiAdmissionClosed = true;
        if (!supervisor) return { clean: true, exitCode: null };
        return supervisor.stop();
      },
      handOff: handOffToInstaller,
      onHandOffFailure: async () => {
        await restartBackend(win);
      },
    });
  } finally {
    win?.setProgressBar(-1);
    updateInFlight = false;
  }
}

function registerIpcHandlers(): void {
  ipcMain.handle(IPC_CHANNELS.getPlatformInfo, (): PlatformInfo => ({
    platform: process.platform as PlatformInfo["platform"],
    arch: process.arch,
    isDesktop: true,
  }));

  ipcMain.handle(IPC_CHANNELS.windowsMenuModel, () => {
    if (!usesCaptionOverlay()) return null;
    return windowsMenuModel(app.getLocale());
  });
  ipcMain.handle(IPC_CHANNELS.windowsMenuInvoke, (event, id: unknown) => {
    const command = windowsMenuCommandId(id);
    if (!command || !usesCaptionOverlay()) return;
    const win = BrowserWindow.fromWebContents(event.sender);
    if (!win || win.isDestroyed()) return;
    runWindowsMenuCommand(win, command);
  });

  ipcMain.on(IPC_CHANNELS.windowMinimize, (event) => {
    linuxCaptionWindow(event.sender)?.minimize();
  });
  ipcMain.on(IPC_CHANNELS.windowToggleMaximize, (event) => {
    const win = linuxCaptionWindow(event.sender);
    if (!win) return;
    if (win.isMaximized()) win.unmaximize();
    else win.maximize();
  });
  ipcMain.on(IPC_CHANNELS.windowClose, (event) => {
    linuxCaptionWindow(event.sender)?.close();
  });
  ipcMain.handle(IPC_CHANNELS.windowIsMaximized, (event): boolean => {
    return linuxCaptionWindow(event.sender)?.isMaximized() ?? false;
  });

  ipcMain.handle(IPC_CHANNELS.clientSettingsGet, (): ClientSettings => {
    const current = settingsStore.load();
    // The guide's completion is per data root, not per Electron profile.
    return { ...current, onboardingCompleted: isOnboardingCompletedFor(current, octopHomePath) };
  });
  ipcMain.handle(IPC_CHANNELS.clientSettingsSet, (_e, patch: Partial<ClientSettings>) => {
    const next = { ...patch };
    // Finishing the guide pins it to the home that finished it.
    if (next.onboardingCompleted === true) next.onboardingHome = octopHomePath;
    const saved = settingsStore.save(next);
    closeBehavior = saved.closeBehavior;
    if (patch && Object.prototype.hasOwnProperty.call(patch, "launchAtLogin")) {
      applyAutoLaunchSetting(saved.launchAtLogin);
    }
    return { ...saved, onboardingCompleted: isOnboardingCompletedFor(saved, octopHomePath) };
  });

  // Synchronous on purpose: the renderer builds WebSocket URLs inside render
  // paths and cannot await (§5.2). Answers null (never the sidecar port) while
  // no relay is listening.
  ipcMain.on(IPC_CHANNELS.wsEndpoint, (event) => {
    event.returnValue = wsRelay?.endpoint ?? null;
  });

  ipcMain.handle(IPC_CHANNELS.checkForUpdates, async (): Promise<UpdateCheckResult> => {
    try {
      const { manifest, stableOnly } = await fetchUpdateManifest();
      const platform = platformAssetKey(process.platform, process.arch);
      // Channel head is what the page shows, even when it is not an upgrade.
      // The installable selection still has to be newer and carry a local asset.
      const listed = channelHeadTag(manifest, stableOnly);
      const selected = selectRelease(manifest, appVersion, platform, stableOnly);
      if (!selected) {
        return { status: "up-to-date", currentVersion: appVersion, latestVersion: listed, error: null };
      }
      return {
        status: "update-available",
        currentVersion: appVersion,
        latestVersion: selected.tag,
        error: null,
      };
    } catch (err) {
      return {
        status: "error",
        currentVersion: appVersion,
        latestVersion: null,
        error: errorMessageOf(err),
      };
    }
  });

  ipcMain.handle(IPC_CHANNELS.installUpdate, async (event) => {
    // The page already confirmed. Ignore every argument and re-select the
    // release here, so the renderer cannot name a package URL (§6.2).
    if (updateInFlight) return;
    const win = BrowserWindow.fromWebContents(event.sender) ?? BrowserWindow.getAllWindows()[0] ?? null;

    let selected: SelectedRelease | null;
    try {
      selected = await resolveSelectedRelease();
    } catch (err) {
      await showShellError(win, "检查更新失败", errorMessageOf(err));
      return;
    }
    if (!selected) {
      await showShellMessage(win, "已是最新版本", `当前版本 ${appVersion}。`);
      return;
    }

    const outcome = await runShellUpdate(win, selected);
    if (!outcome.ok) {
      await showShellError(win, "升级失败", outcome.message);
      return;
    }
    // §6.3 step 3: the installer owns the rest — hand it our exit. An update
    // must never stop on the "still running" prompt.
    quitReason = "update";
    app.quit();
  });

  ipcMain.handle(IPC_CHANNELS.sessionRegister, (_event, accessToken: unknown): Promise<boolean> => {
    if (!isUsableAccessToken(accessToken)) return Promise.resolve(false);
    return deviceSession?.register(accessToken) ?? Promise.resolve(false);
  });

  ipcMain.handle(IPC_CHANNELS.sessionRenew, (): Promise<IssuedSession | null> => {
    return deviceSession?.renew() ?? Promise.resolve(null);
  });

  ipcMain.handle(IPC_CHANNELS.sessionRevoke, (_event, accessToken: unknown): Promise<boolean> => {
    if (!isUsableAccessToken(accessToken)) return Promise.resolve(false);
    return deviceSession?.revoke(accessToken) ?? Promise.resolve(false);
  });

  // Single-user machine facts. No account list, no team, one data root.
  ipcMain.handle(IPC_CHANNELS.desktopInfo, (): DesktopInfo => desktopInfoData());
  ipcMain.handle(IPC_CHANNELS.openDataDirectory, (): Promise<boolean> => openDataDirectory());
  ipcMain.handle(IPC_CHANNELS.openOnboarding, (): void => showOnboarding());

  // The Dashboard owns "is there unsaved work"; the shell only asks on quit.
  ipcMain.on(IPC_CHANNELS.unsavedContent, (_event, dirty: unknown) => {
    rendererUnsaved = dirty === true;
  });

  // The page reports its theme so the native controls follow it; window buttons
  // themselves are native and never cross this bridge. The preference is also
  // the device setting the next Early Window paints from — the splash cannot
  // read the Dashboard's localStorage.
  ipcMain.on(IPC_CHANNELS.windowChromeTheme, (event, theme: unknown) => {
    const parsed = parseWindowChromeTheme(theme);
    if (!parsed) return;
    const win = BrowserWindow.fromWebContents(event.sender);
    if (win) applyWindowChromeTheme(win, parsed);
    if (parsed.scheme && settingsStore.load().themeBackground !== parsed.scheme) {
      settingsStore.save({ themeBackground: parsed.scheme });
    }
  });
}

/** Append the desktop log path so a packaged failure says where to look. */
function errorDetail(detail?: string): string | undefined {
  const path = desktopLog().path;
  const text = [detail, path ? `日志: ${path}` : ""].filter((line) => line).join("\n");
  return text || undefined;
}

function shortcutDisplay(accelerator: string): string {
  if (process.platform !== "darwin") return accelerator.replace("CommandOrControl", "Ctrl");
  return accelerator
    .replace("CommandOrControl", "⌘")
    .replace("Shift", "⇧")
    .replace("Alt", "⌥")
    .replace(/\+/g, "");
}

/** Single-user facts for the guide and for any settings page that asks. */
function desktopInfoData(): DesktopInfo {
  return {
    appVersion,
    platform: process.platform as DesktopInfo["platform"],
    dataDirectory: octopHomePath,
    backupsDirectory: octopHomePath ? join(octopHomePath, "backups") : "",
    logFile: desktopLog().path,
    shortcuts: {
      showWindow: shortcutDisplay(SHORTCUT_SHOW_WINDOW),
      newSession: shortcutDisplay(SHORTCUT_NEW_SESSION),
    },
    singleUser: true,
  };
}

async function openDataDirectory(): Promise<boolean> {
  if (!octopHomePath) return false;
  try {
    await fs.mkdir(octopHomePath, { recursive: true });
    const failure = await shell.openPath(octopHomePath);
    if (failure) {
      desktopLog().warn(`open data directory failed: ${failure}`);
      return false;
    }
    return true;
  } catch (err) {
    desktopLog().warn(`open data directory failed: ${errorMessageOf(err)}`);
    return false;
  }
}

/** Reveal the shell log in the OS file manager; fall back to its folder. */
function openLogFile(): void {
  const path = desktopLog().path;
  if (!path) return;
  if (existsSync(path)) shell.showItemInFolder(path);
  else void shell.openPath(dirname(path));
}

/** Apply "open at login". Linux writes its own freedesktop entry. */
function applyAutoLaunchSetting(enabled: boolean): void {
  try {
    if (process.platform === "linux") {
      writeLinuxAutostart({
        homeDir: app.getPath("home"),
        enabled,
        name: "HappyClaw",
        execPath: process.execPath,
        args: app.isPackaged ? [] : [app.getAppPath()],
      });
      return;
    }
    app.setLoginItemSettings({ openAtLogin: enabled });
  } catch (err) {
    desktopLog().warn(`launch-at-login update failed: ${errorMessageOf(err)}`);
  }
}

/** Two-step guide. Reused by the first launch and Help → 首次引导. */
function showOnboarding(): void {
  if (onboardingWindow && !onboardingWindow.isDestroyed()) {
    onboardingWindow.show();
    onboardingWindow.focus();
    return;
  }
  if (!settingsStore) return;
  const chromeTheme = resolveWindowChromeTheme(settingsStore.load().themeBackground);
  onboardingWindow = createOnboardingWindow({
    file: ONBOARDING_PATH,
    preload: PRELOAD_PATH,
    theme: chromeTheme,
    parent: dashboardWindow,
  });
  onboardingWindow.on("closed", () => {
    onboardingWindow = null;
  });
}

/**
 * Global "new conversation". The chat route is the one URL the Dashboard
 * already treats as a fresh conversation; when we are already there, the page
 * gets a chance to start one in place (Dashboard wiring is tracked separately).
 */
function openNewSession(): void {
  if (quitting) return;
  revealAppWindow();
  const win = dashboardWindow && !dashboardWindow.isDestroyed() ? dashboardWindow : null;
  if (!win) return;
  try {
    const current = new URL(win.webContents.getURL());
    if (current.pathname !== "/chat") {
      const chromeTheme = resolveWindowChromeTheme(settingsStore.load().themeBackground);
      current.pathname = "/chat";
      current.hash = "";
      current.searchParams.set("octopTheme", chromeTheme.scheme ?? chromeTheme.mode);
      void win.loadURL(current.toString());
      return;
    }
  } catch {
    // Not an app URL (still on the splash): fall through to the page event.
  }
  win.webContents.send(IPC_CHANNELS.newSessionShortcut);
}

/** Tray "back up now" — the same archive the settings page creates. */
async function runTrayBackup(): Promise<void> {
  if (backupInFlight) {
    await showShellMessage(null, "正在备份", "上一次备份还没有结束，请稍候。");
    return;
  }
  if (!backendPort || apiAdmissionClosed) {
    await showShellError(null, "暂时无法备份", "本地服务还没有准备好，请等主界面加载完成后再试。");
    return;
  }
  // 单人模式允许空 token：凭据缺失就匿名调用，续期失败也再兜底一次。
  const session = await deviceSession?.renew();
  const baseUrl = `http://127.0.0.1:${backendPort}`;
  backupInFlight = true;
  try {
    let result = await createManualBackup({ baseUrl, token: session?.access_token });
    if (!result.ok && session) {
      result = await createManualBackup({ baseUrl });
    }
    if (!result.ok) {
      await showShellError(null, "备份失败", result.message ?? "未知错误");
      return;
    }
    const backupsDir = octopHomePath ? join(octopHomePath, "backups") : null;
    const detail = [
      `文件: ${result.name ?? "已生成归档"}`,
      backupsDir ? `位置: ${backupsDir}` : "",
    ]
      .filter((line) => line)
      .join("\n");
    // A tray backup happens while the user is elsewhere in the app, so the
    // dialog offers the folder instead of only naming it.
    const choice = await dialog.showMessageBox({
      type: "info",
      buttons: backupsDir ? ["打开备份文件夹", "好"] : ["好"],
      defaultId: backupsDir ? 1 : 0,
      cancelId: backupsDir ? 1 : 0,
      noLink: true,
      message: "备份完成",
      detail,
    });
    if (backupsDir && choice.response === 0) await shell.openPath(backupsDir);
  } finally {
    backupInFlight = false;
  }
}

/** Last validated geometry, or Electron's defaults on first launch. */
function windowStateOptions(): {
  bounds: { x: number; y: number; width: number; height: number } | null;
  maximized: boolean;
} {
  if (!windowStatePath) return { bounds: null, maximized: false };
  const stored = readWindowState(windowStatePath) ?? {};
  const workAreas = screen.getAllDisplays().map((display) => display.workArea);
  return {
    bounds: usableWindowBounds(stored, workAreas, MIN_WINDOW_SIZE),
    maximized: stored.maximized === true,
  };
}

/** Persist bounds while the user drags/resizes, and once more on close. */
function attachWindowStatePersistence(win: BrowserWindow): void {
  if (!windowStatePath) return;
  let timer: NodeJS.Timeout | null = null;
  const save = () => {
    if (win.isDestroyed()) return;
    try {
      writeWindowState(windowStatePath, {
        ...win.getNormalBounds(),
        maximized: win.isMaximized(),
      });
    } catch (err) {
      desktopLog().warn(`window state save failed: ${errorMessageOf(err)}`);
    }
  };
  const schedule = () => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      save();
    }, 400);
  };
  win.on("resize", schedule);
  win.on("move", schedule);
  win.on("maximize", save);
  win.on("unmaximize", save);
  win.on("close", save);
}

let locationTimer: NodeJS.Timeout | null = null;

/** Remember the last in-app URL so an unclean exit can reopen it. */
function rememberDashboardLocation(url: string): void {
  if (!sessionSnapshotPath || !dashboardOrigin) return;
  if (
    url !== dashboardOrigin &&
    !url.startsWith(`${dashboardOrigin}/`) &&
    !url.startsWith(`${dashboardOrigin}?`)
  ) {
    return;
  }
  lastDashboardUrl = url;
  if (locationTimer) clearTimeout(locationTimer);
  locationTimer = setTimeout(() => {
    locationTimer = null;
    if (!lastDashboardUrl || !dashboardOrigin) return;
    try {
      writeSessionSnapshot(sessionSnapshotPath, {
        url: lastDashboardUrl,
        cleanExit: false,
        sessionId: sessionIdOf(lastDashboardUrl, dashboardOrigin),
      });
    } catch (err) {
      desktopLog().warn(`session snapshot save failed: ${errorMessageOf(err)}`);
    }
  }, 500);
}

function markCleanExit(): void {
  if (!sessionSnapshotPath) return;
  if (locationTimer) {
    clearTimeout(locationTimer);
    locationTimer = null;
  }
  try {
    writeSessionSnapshot(sessionSnapshotPath, {
      url: lastDashboardUrl,
      cleanExit: true,
      sessionId: lastDashboardUrl && dashboardOrigin ? sessionIdOf(lastDashboardUrl, dashboardOrigin) : null,
    });
  } catch (err) {
    desktopLog().warn(`clean-exit snapshot failed: ${errorMessageOf(err)}`);
  }
}

/** The recovered URL on the first window only; later windows use the entry URL. */
function entryUrlFor(
  appOrigin: string,
  theme: "system" | "light" | "dark",
): string {
  const snapshot = pendingRecovery;
  pendingRecovery = null;
  return (snapshot ? restoreUrl(snapshot, appOrigin, theme) : null) ?? dashboardEntryUrl(theme, appOrigin);
}

function registerGlobalShortcuts(): void {
  const bind = (accelerator: string, run: () => void) => {
    try {
      if (!globalShortcut.register(accelerator, run)) {
        desktopLog().warn(`global shortcut already taken: ${accelerator}`);
      }
    } catch (err) {
      desktopLog().warn(`global shortcut failed (${accelerator}): ${errorMessageOf(err)}`);
    }
  };
  bind(SHORTCUT_SHOW_WINDOW, () => revealAppWindow());
  bind(SHORTCUT_NEW_SESSION, () => openNewSession());
}

/**
 * macOS keeps the system menu bar, which the shell never builds. Add the two
 * shell-owned Help entries to the default Help submenu so the guide and the
 * data folder stay reachable without a Dashboard settings page.
 */
let macHelpInstalled = false;

function installMacHelpMenu(): void {
  if (process.platform !== "darwin" || macHelpInstalled) return;
  const menu = Menu.getApplicationMenu();
  const help = menu?.items.find((item) => item.role === "help");
  if (!help?.submenu) return;
  help.submenu.append(
    new MenuItem({ id: "onboarding", label: "首次引导", click: () => showOnboarding() }),
  );
  help.submenu.append(
    new MenuItem({
      id: "openDataDirectory",
      label: "打开数据目录",
      click: () => void openDataDirectory(),
    }),
  );
  help.submenu.append(
    new MenuItem({ id: "openLogFile", label: "打开日志文件", click: () => void openLogFile() }),
  );
  macHelpInstalled = true;
}

/** Spawn the sidecar on a fresh loopback port and wait for health. */
async function startBackend(): Promise<boolean> {
  if (!backend) return false;
  // Local const so the union narrows: the module-level binding is mutable.
  const launch = backend;
  const onedir = launch.kind === "onedir";
  const port = await reserveRandomPort();
  const env = buildSidecarEnv(process.env, {
    octopHome: launch.octopHome,
    portableDir: launch.kind === "onedir" ? launch.cwd : launch.portableDir,
    port,
    bindHost: "127.0.0.1",
    onedir,
  });
  backendPort = port;
  const sidecar = new SidecarSupervisor({
    executable: launch.kind === "onedir" ? launch.executable : launch.interpreter,
    args:
      launch.kind === "onedir"
        ? ["run", "--port", String(port)]
        : [launch.launchScript, "run"],
    env,
    cwd: launch.cwd,
    port,
    onExit: ({ code, signal, output }) => {
      const summary = `sidecar exited code=${code ?? "null"} signal=${signal ?? "null"}`;
      // A clean exit, or a stop this shell already asked for, is not a crash.
      if (quitting || (code === 0 && signal === null)) {
        desktopLog().info(summary);
        return;
      }
      desktopLog().error(summary);
      const tail = output.trim();
      if (tail) desktopLog().error(tail);
    },
  });
  supervisor = sidecar;
  // Cold starts of the bundled runtime have needed over four minutes; the
  // budget is wide and ``OCTOP_READY_TIMEOUT_MS`` can widen it further.
  const readyTimeoutMs = resolveHealthTimeoutMs();
  desktopLog().info(
    `starting sidecar on 127.0.0.1:${port} (ready timeout ${Math.round(readyTimeoutMs / 1000)}s)`,
  );
  sidecar.start();
  const ready = await sidecar.waitUntilReady(readyTimeoutMs);
  if (!ready) {
    desktopLog().error(`sidecar was not ready on 127.0.0.1:${port}`);
    // The exit handler already kept the tail when the process died. A timeout
    // leaves it running, so that tail still has to be written from here.
    if (sidecar.isRunning()) {
      const tail = sidecar.outputTail().trim();
      if (tail) desktopLog().error(tail);
    }
  }
  return ready;
}

function openExternal(url: string): void {
  if (isExternalLink(url)) void shell.openExternal(url);
}

const HEALTH_PROBE_MS = 20_000;

let healthWatchTimer: NodeJS.Timeout | null = null;
let healthFailures = 0;
let reconnectPromptOpen = false;

/** Poll the sidecar while a Dashboard window exists so a dead backend is noticed. */
function startHealthWatch(): void {
  if (healthWatchTimer) return;
  healthFailures = 0;
  healthWatchTimer = setInterval(() => void probeBackendHealth(), HEALTH_PROBE_MS);
}

function stopHealthWatch(): void {
  if (healthWatchTimer) clearInterval(healthWatchTimer);
  healthWatchTimer = null;
  healthFailures = 0;
}

async function probeBackendHealth(): Promise<void> {
  if (quitting || !backendPort) return;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 5_000);
  try {
    const response = await net.fetch(`http://127.0.0.1:${backendPort}/api/health`, {
      signal: controller.signal,
    });
    if (response.ok) {
      healthFailures = 0;
      return;
    }
    healthFailures += 1;
  } catch {
    healthFailures += 1;
  } finally {
    clearTimeout(timer);
  }
  // One missed probe is a blip (backup, update download). Two in a row is an outage.
  if (healthFailures >= 2) {
    healthFailures = 0;
    await offerReconnect();
  }
}

/** The backend stopped answering: say so and offer a restart instead of a dead page. */
async function offerReconnect(): Promise<void> {
  if (reconnectPromptOpen || quitting) return;
  reconnectPromptOpen = true;
  try {
    const win = dashboardWindow && !dashboardWindow.isDestroyed() ? dashboardWindow : null;
    const options = {
      type: "warning" as const,
      buttons: ["重新连接", "稍后"],
      defaultId: 0,
      cancelId: 1,
      noLink: true,
      message: "与本地服务的连接已断开",
      detail: "本地 Python 服务没有响应。重新连接会重启该服务并刷新页面。",
    };
    const { response } = win
      ? await dialog.showMessageBox(win, options)
      : await dialog.showMessageBox(options);
    if (response !== 0) return;
    await supervisor?.stop();
    apiAdmissionClosed = false;
    if (!(await startBackend())) {
      await showShellError(win, "重连失败", errorDetail("本地服务仍未能启动。") ?? "请查看日志后重试。");
      return;
    }
    if (win && !win.isDestroyed()) win.webContents.reload();
  } finally {
    reconnectPromptOpen = false;
  }
}

/** Close-to-tray and the "backend ready" signal. Shared by the first window and a later one. */
function watchDashboardLifetime(win: BrowserWindow): void {
  startHealthWatch();
  win.on("close", (event) => {
    if (
      !shouldKeepWindowOnClose({
        platform: process.platform,
        closeBehavior,
        quitting,
        trayReady: tray !== null,
      })
    ) {
      return;
    }
    // Hide instead of destroy. macOS comes back from the Dock; Windows and
    // Linux come back from the tray icon. The next click shows this same
    // window rather than a fresh load.
    event.preventDefault();
    win.hide();
    // Hiding the last window makes Windows drop a bitmap tray icon. Put the
    // same image back so the notification area still has a way to reopen.
    if (tray && trayIcon && !tray.isDestroyed()) tray.setImage(trayIcon);
  });
  win.webContents.on("did-finish-load", () => {
    if (win.isDestroyed()) return;
    win.webContents.send(IPC_CHANNELS.onBackendReady, { ok: true });
  });
}

/** Linux page-drawn caption buttons. Other platforms keep the native ones. */
function linuxCaptionWindow(sender: WebContents): BrowserWindow | null {
  if (process.platform !== "linux") return null;
  const win = BrowserWindow.fromWebContents(sender);
  if (!win || win.isDestroyed()) return null;
  return win;
}

/** Tell the page when maximize flips, so the glyph can switch to restore. */
function watchLinuxCaptionState(win: BrowserWindow): void {
  if (process.platform !== "linux") return;
  const publish = () => {
    if (win.isDestroyed() || win.webContents.isDestroyed()) return;
    win.webContents.send(IPC_CHANNELS.windowMaximized, win.isMaximized());
  };
  win.on("maximize", publish);
  win.on("unmaximize", publish);
}

function openDashboardWindow(appOrigin: string): BrowserWindow {
  dashboardOrigin = appOrigin;
  const chromeTheme = resolveWindowChromeTheme(settingsStore.load().themeBackground);
  const geometry = windowStateOptions();
  const win = createMainWindow({
    preload: PRELOAD_PATH,
    theme: chromeTheme,
    backgroundColor: windowBackground(chromeTheme.mode),
    entryUrl: entryUrlFor(appOrigin, chromeTheme.scheme ?? chromeTheme.mode),
    appOrigin,
    onNavigate: openExternal,
    bounds: geometry.bounds,
    maximized: geometry.maximized,
  });
  dashboardWindow = win;
  attachWindowStatePersistence(win);
  watchDashboardLifetime(win);
  watchLinuxCaptionState(win);
  win.on("closed", () => {
    if (dashboardWindow === win) dashboardWindow = null;
  });
  return win;
}

/** A restored conversation must still exist; the first query after a cold boot can be slow. */
const SESSION_PROBE_TIMEOUT_MS = 10_000;

/**
 * Does this data root still hold the conversation? Only a definitive 404 counts
 * as "gone" — a timeout or server error keeps the restored URL, because a slow
 * backend must not silently throw the user back to the agent root.
 */
async function chatSessionExists(agentId: string, sessionId: string): Promise<boolean> {
  if (apiAdmissionClosed || !backendPort) return true;
  const url = toBackendUrl(
    backendPort,
    `/api/agents/${encodeURIComponent(agentId)}/threads/${encodeURIComponent(sessionId)}/history`,
    "",
  );
  try {
    const response = await net.fetch(url, {
      cache: "no-store",
      signal: AbortSignal.timeout(SESSION_PROBE_TIMEOUT_MS),
    });
    return response.status !== 404;
  } catch (err) {
    desktopLog().warn(`session restore probe failed: ${errorMessageOf(err)}`);
    return true;
  }
}

/** Keep the splash window and load the Dashboard into it. */
async function continueInEarlyWindow(early: EarlyWindow, appOrigin: string): Promise<void> {
  dashboardOrigin = appOrigin;
  const win = early.browserWindow;
  if (win.isDestroyed()) {
    openDashboardWindow(appOrigin);
    return;
  }
  installDashboardGuards(win, { appOrigin, onNavigate: openExternal });
  dashboardWindow = win;
  attachWindowStatePersistence(win);
  watchDashboardLifetime(win);
  win.webContents.on("did-navigate", (_event, url) => rememberDashboardLocation(url));
  win.webContents.on("did-navigate-in-page", (_event, url, isMainFrame) => {
    if (isMainFrame) rememberDashboardLocation(url);
  });
  win.on("closed", () => {
    if (dashboardWindow === win) dashboardWindow = null;
  });
  const settings = settingsStore.load();
  const chromeTheme = resolveWindowChromeTheme(settings.themeBackground);
  if (!isOnboardingCompletedFor(settings, octopHomePath)) {
    // After the Dashboard has painted, not over the splash. The guide is a
    // separate window, so the main UI is already usable behind it.
    win.webContents.once("did-finish-load", () => showOnboarding());
  }
  const theme = chromeTheme.scheme ?? chromeTheme.mode;
  let entryUrl = entryUrlFor(appOrigin, theme);
  const chat = chatLocation(entryUrl, appOrigin);
  if (chat?.sessionId && !(await chatSessionExists(chat.agentId, chat.sessionId))) {
    // That conversation is not in this data root any more: reopen the agent
    // route instead of letting the page create an empty session.
    entryUrl = routeOnlyUrl(entryUrl, appOrigin, theme) ?? dashboardEntryUrl(theme, appOrigin);
    desktopLog().info(`restored session ${chat.sessionId} is gone; opening the ${chat.agentId} route`);
  }
  void win.loadURL(entryUrl);
}

/**
 * Windows will not raise a window that was hidden while another app was
 * active. Briefly pinning it forces the foreground, then releases it.
 */
function raiseHiddenWindows(windows: readonly BrowserWindow[]): void {
  if (process.platform !== "win32") return;
  for (const win of windows) {
    if (win.isDestroyed()) continue;
    win.setAlwaysOnTop(true);
    win.show();
    win.focus();
    win.setAlwaysOnTop(false);
  }
}

/** Dock click, tray click, and a second launch. Show what is already open, or open it. */
function revealAppWindow(): void {
  if (quitting) return;
  const windows = BrowserWindow.getAllWindows();
  if (presentWindows(windows) > 0) {
    // The click is the user asking for this app. Steal so a hidden window
    // comes forward even when another app was active.
    app.focus({ steal: true });
    raiseHiddenWindows(windows);
    const areas = screen.getAllDisplays().map((display) => display.workArea);
    if (areas.length === 0) return;
    for (const win of windows) {
      if (win.isDestroyed()) continue;
      if (!isWindowOnScreen(win.getBounds(), areas)) win.center();
    }
    return;
  }
  if (dashboardOrigin) openDashboardWindow(dashboardOrigin);
}

function showAboutDialog(version: string): void {
  const locale = app.getLocale();
  const stamp = resolveGitStamp(readGitStamp, {
    commit: process.env.OCTOP_GIT_COMMIT,
    date: process.env.OCTOP_GIT_DATE,
  });
  void dialog.showMessageBox({
    type: "info",
    title: locale.toLowerCase().startsWith("zh") ? "关于 HappyClaw" : "About HappyClaw",
    message: "HappyClaw",
    detail: formatAboutDetail({
      version,
      setup: windowsInstallScope(process.execPath),
      commit: stamp.commit,
      date: stamp.date,
      electron: process.versions.electron ?? "",
      chromium: process.versions.chrome ?? "",
      node: process.versions.node ?? "",
      v8: process.versions.v8 ?? "",
      os: formatAboutOs(osType(), process.arch, osRelease()),
    }),
  });
}

/** Run one caption-menu command. Roles stay on the native menu for accelerators. */
function runWindowsMenuCommand(win: BrowserWindow, command: WindowsMenuCommandId): void {
  const contents = win.webContents;
  switch (command) {
    case "close":
      win.close();
      return;
    case "quit":
      app.quit();
      return;
    case "undo":
      contents.undo();
      return;
    case "redo":
      contents.redo();
      return;
    case "cut":
      contents.cut();
      return;
    case "copy":
      contents.copy();
      return;
    case "paste":
      contents.paste();
      return;
    case "delete":
      contents.delete();
      return;
    case "selectAll":
      contents.selectAll();
      return;
    case "reload":
      contents.reload();
      return;
    case "forceReload":
      contents.reloadIgnoringCache();
      return;
    case "toggleDevTools":
      contents.toggleDevTools();
      return;
    case "resetZoom":
      contents.setZoomLevel(0);
      return;
    case "zoomIn":
      contents.setZoomLevel(contents.getZoomLevel() + 1);
      return;
    case "zoomOut":
      contents.setZoomLevel(contents.getZoomLevel() - 1);
      return;
    case "togglefullscreen":
      win.setFullScreen(!win.isFullScreen());
      return;
    case "onboarding":
      showOnboarding();
      return;
    case "openDataDirectory":
      void openDataDirectory();
      return;
    case "openLogFile":
      void openLogFile();
      return;
    case "about":
      showAboutDialog(appVersion);
      return;
  }
}

/** Caption menu on Windows and Linux. macOS keeps the system menu bar. */
function installWindowsAppMenu(version: string): void {
  if (!usesCaptionOverlay()) return;
  Menu.setApplicationMenu(
    Menu.buildFromTemplate(
      windowsApplicationMenu(app.getLocale(), {
        onAbout: () => showAboutDialog(version),
        onOnboarding: () => showOnboarding(),
        onOpenDataDirectory: () => void openDataDirectory(),
        onOpenLogFile: () => void openLogFile(),
      }),
    ),
  );
}

function readGitStamp(args: readonly string[]): string | null {
  const root = repoRootWithGit(app.getAppPath());
  if (!root) return null;
  try {
    const out = execFileSync("git", [...args], {
      cwd: root,
      encoding: "utf8",
      timeout: 2000,
      windowsHide: true,
    }).trim();
    return out || null;
  } catch {
    return null;
  }
}

function repoRootWithGit(start: string): string | null {
  let dir = start;
  for (let i = 0; i < 8; i += 1) {
    if (existsSync(join(dir, ".git"))) return dir;
    const parent = dirname(dir);
    if (parent === dir) return null;
    dir = parent;
  }
  return null;
}

/** Notification-area icon. Left click and "show" open the window; "quit" exits. */
async function installSystemTray(): Promise<void> {
  if (tray || !shouldInstallSystemTray(process.platform)) return;
  const candidates = trayIconCandidates({
    platform: process.platform,
    isPackaged: app.isPackaged,
    resourcesDir: resourcesRoot(),
    execPath: process.execPath,
  });
  const icon = await loadTrayIcon(candidates);
  if (!icon) {
    desktopLog().warn(`tray icon missing: ${candidates.join(", ")}`);
    return;
  }
  // Pass the Windows ico through unchanged. Resizing it to one 32px bitmap is
  // what Windows removes from the notification area when the window is hidden.
  // The Linux panel wants a small PNG; a full app icon is dropped or drawn huge.
  trayIcon = process.platform === "linux" ? icon.resize({ width: 24, height: 24 }) : icon;
  const created = new Tray(trayIcon);
  created.setToolTip("HappyClaw");
  const labels = trayMenuLabels(app.getLocale());
  const menu = Menu.buildFromTemplate([
    { label: labels.open, click: () => revealAppWindow() },
    { label: labels.backup, click: () => void runTrayBackup() },
    { type: "separator" },
    { label: labels.quit, click: () => app.quit() },
  ]);
  // Left click opens the window. The menu stays on right click so a left
  // click is not swallowed by the context menu on Windows. Linux panels open
  // the menu from the icon, so the same menu has to be the context menu.
  created.on("click", () => revealAppWindow());
  created.on("double-click", () => revealAppWindow());
  if (process.platform === "linux") created.setContextMenu(menu);
  else created.on("right-click", () => created.popUpContextMenu(menu));
  tray = created;
  desktopLog().info("tray icon ready");
}

/**
 * The bundled ico first. `createFromPath` cannot read an icon out of an exe,
 * so a packaged build with no loose ico uses the Shell icon instead.
 */
async function loadTrayIcon(candidates: readonly string[]): Promise<NativeImage | null> {
  const imagePath = trayIconImagePath(candidates, existsSync);
  if (imagePath) {
    const loaded = nativeImage.createFromPath(imagePath);
    if (!loaded.isEmpty()) return loaded;
    desktopLog().warn(`tray icon unreadable: ${imagePath}`);
  }
  const executable = trayExecutableFallback(candidates);
  if (!executable) return null;
  try {
    const icon = await app.getFileIcon(executable, { size: "small" });
    return icon.isEmpty() ? null : icon;
  } catch (err) {
    desktopLog().warn(
      `tray icon from executable failed: ${err instanceof Error ? err.message : String(err)}`,
    );
    return null;
  }
}

function destroySystemTray(): void {
  tray?.destroy();
  tray = null;
  trayIcon = null;
}

async function boot(): Promise<void> {
  const gotLock = app.requestSingleInstanceLock();
  if (!gotLock) {
    app.quit();
    return;
  }

  if (process.platform === "win32") {
    app.setAppUserModelId(WINDOWS_APP_USER_MODEL_ID);
  }

  appVersion = await resolveProductVersion();
  installWindowsAppMenu(appVersion);

  const userDataDir = app.getPath("userData");
  settingsStore = new ClientSettingsStore(defaultClientSettingsPath(userDataDir));
  const settings = settingsStore.load();
  closeBehavior = settings.closeBehavior;

  // Geometry, crash recovery and "open at login" are shell-owned. All three
  // converge to the saved preference at boot, so a manual OS change is undone.
  windowStatePath = join(userDataDir, "desktop-window.json");
  sessionSnapshotPath = join(userDataDir, "desktop-session.json");
  applyAutoLaunchSetting(settings.launchAtLogin);
  registerGlobalShortcuts();
  installMacHelpMenu();

  const previousSession = readSessionSnapshot(sessionSnapshotPath);
  lastDashboardUrl = previousSession.url;
  pendingRecovery = previousSession;
  // This launch is now "in progress"; a clean quit flips the flag back.
  writeSessionSnapshot(sessionSnapshotPath, {
    url: previousSession.url,
    cleanExit: false,
    sessionId: previousSession.sessionId,
  });
  // Apply the source before resolving, so a stored "system" reads the OS
  // preference rather than whatever an earlier explicit source left behind.
  applyNativeTheme({
    mode: settings.themeBackground === "dark" ? "dark" : "light",
    scheme: settings.themeBackground,
  });
  const chromeTheme = resolveWindowChromeTheme(settings.themeBackground);

  const early = createEarlyWindow({
    splashFile: SPLASH_PATH,
    errorFile: ERROR_PATH,
    version: appVersion,
    // Same preload as the Dashboard: this window loads that page next, and a
    // BrowserWindow cannot swap its preload.
    preload: PRELOAD_PATH,
    theme: chromeTheme,
    ...windowStateOptions(),
  });
  watchLinuxCaptionState(early.browserWindow);
  // macOS has a menu bar as soon as a window exists; add the Help entries now.
  installMacHelpMenu();

  // Resolve OCTOP_HOME, reading the login shell on macOS/Linux (GUI apps don't
  // inherit it). The extraction dir and the child env must agree on one root.
  const loginShellEnv =
    process.platform === "win32" ? {} : await readLoginShellEnv(process.env.SHELL);
  const octopHome = resolveOctopHome(process.env, loginShellEnv);
  octopHomePath = octopHome;
  installDesktopLog(octopHome);
  desktopLog().info(`desktop ${appVersion} home=${octopHome}`);
  // The guide used to be remembered only in Electron's userData. Stamp the data
  // root that finished it, so another OCTOP_HOME replays the guide.
  if (settings.onboardingCompleted && !settings.onboardingHome) {
    try {
      settingsStore.save({ onboardingHome: octopHome });
    } catch (err) {
      desktopLog().warn(`onboarding home migration failed: ${errorMessageOf(err)}`);
    }
  }
  await installSystemTray();

  // Local dev escape hatch: point at an already-extracted runtime (e.g. the one
  // `pnpm dev:runtime` writes to .dev-runtime) and skip bundling/extraction.
  // Packaged Windows (NSIS → resources/sidecar) and macOS (expanded before
  // signing → resources/portable) already contain the tree; do not unzip again.
  const devPortableDir = (process.env.OCTOP_PORTABLE_DIR ?? "").trim();
  let portableDir = devPortableDir;
  // Windows installer shape: one PyInstaller onedir backend under
  // resources/sidecar/backend. No Python, no extraction, nothing to compile.
  const onedirDir = portableDir
    ? null
    : installedOnedirBackendDir(resourcesRoot(), process.platform, existsSync);
  if (onedirDir) {
    desktopLog().info(`onedir backend installed at ${onedirDir}`);
  }
  if (!portableDir && !onedirDir) {
    const installed = installedRuntimeDir(resourcesRoot(), process.platform, existsSync);
    if (installed) {
      portableDir = installed;
      desktopLog().info(`runtime installed at ${installed}`);
    }
  }

  // A package that still ships only the zip (not the Win/mac/Linux installers):
  // version guard (§2.3) then atomic extract into OCTOP_HOME. Must run BEFORE spawning Python.
  if (!portableDir && !onedirDir) {
    portableDir = join(octopHome, "portable");
    try {
      const bundled = await readBundledPortable();
      const local = await readLocalRuntime(octopHome);
      const decision = classifyRuntime(bundled, local, compareVersions);

      desktopLog().info(
        `runtime ${decision.action} (${decision.reason}) bundled=${bundled.version} local=${local.version ?? "none"}`,
      );
      if (decision.action === "stop") {
        early.showError({
          message: `检测到本机运行时版本为 ${decision.localVersion}，当前安装的是 ${bundled.version}。这是手动覆盖安装的旧版，已停止启动，并保留了现有运行时。`,
          detail: errorDetail(`运行时目录: ${portableDir}`),
        });
        return;
      }

      if (decision.action === "extract" || decision.action === "replace") {
        const zip = portableZipPath();
        const digest = await sha256File(zip);
        if (digest !== bundled.sha256) {
          desktopLog().error(`portable zip sha256 mismatch file=${zip}`);
          early.showError({
            message: "随包运行时校验失败（SHA-256 不匹配），为避免执行被篡改的文件，已停止启动。",
            detail: errorDetail(`文件: ${zip}\n期望: ${bundled.sha256}\n实际: ${digest}`),
          });
          return;
        }
        extractPortableZip(zip, portableDir);
        await writeLocalVersion(octopHome, bundled.version);
      }
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err);
      desktopLog().error(`portable runtime preparation failed: ${detail}`);
      early.showError({
        message: "准备便携运行时（解压或校验）时出错，已停止启动。",
        detail: errorDetail(detail),
      });
      return;
    }
  }

  if (onedirDir) {
    backend = {
      kind: "onedir",
      executable: join(onedirDir, "octop.exe"),
      cwd: onedirDir,
      octopHome,
    };
  } else {
    const interpreter = join(
      portableDir,
      "runtime",
      process.platform === "win32" ? "python.exe" : "bin/python3",
    );
    backend = {
      kind: "python",
      interpreter,
      launchScript: join(portableDir, "launch.py"),
      cwd: portableDir,
      octopHome,
      portableDir,
    };
  }

  // §7 accounts: the device credential lives in the data root, next to the
  // database it unlocks, and only the main process ever sees it.
  const cipher = safeStorageCipher();
  await warnIfKeychainUnavailable(cipher);
  const credentialStore = new DeviceCredentialStore(octopHome, cipher);
  try {
    // v1 could leave a plaintext credential behind; this is the only place that
    // adopts it — re-encrypting when a keychain exists, deleting it otherwise.
    await credentialStore.migrate();
  } catch (err) {
    desktopLog().warn(`[desktop] device credential migration failed: ${String(err)}`);
  }
  deviceSession = new DeviceSessionClient({
    store: credentialStore,
    baseUrl: () => (apiAdmissionClosed || !backendPort ? null : `http://127.0.0.1:${backendPort}`),
    label: `${process.platform}-${process.arch}`,
  });

  registerProtocol(dashboardRoot(backend));
  registerIpcHandlers();

  // §5.2: the page learns only this relay's ephemeral port, never the sidecar's.
  // A bind failure must not abort the launch — the Dashboard then finds no
  // endpoint and falls back to its page-origin URLs, i.e. no live streams.
  const dashboardDev = app.isPackaged ? null : readDashboardDev(process.env);
  const windowOrigin = dashboardDev ? dashboardDevOrigin(dashboardDev.port) : WINDOW_ORIGIN;
  wsRelay = new WsRelay({
    backendPort: () => (apiAdmissionClosed || !backendPort ? 0 : backendPort),
    allowedOrigin: windowOrigin,
  });
  try {
    await wsRelay.start();
  } catch (err) {
    desktopLog().warn(`[desktop] websocket relay unavailable: ${errorMessageOf(err)}`);
    wsRelay = null;
  }

  const ready = await startBackend();
  if (!ready) {
    const command =
      backend.kind === "onedir"
        ? `后端: ${backend.executable}`
        : `启动器: ${backend.launchScript}`;
    early.showError({
      message: "本地服务未能就绪（健康检查超时或进程提前退出）。请查看日志后重试。",
      detail: errorDetail(`${command}\n端口: 127.0.0.1:${backendPort}`),
    });
    return;
  }

  if (dashboardDev) {
    try {
      desktopLog().info(`[dev] dashboard hot reload at ${windowOrigin}`);
      await startDashboardDevServer({
        sourceDir: dashboardDev.sourceDir,
        port: dashboardDev.port,
        apiPort: backendPort,
      });
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err);
      desktopLog().error(`dashboard dev server failed: ${detail}`);
      early.showError({
        message: "仪表盘开发服务器没有起来，页面无法热更新。",
        detail: errorDetail(detail),
      });
      return;
    }
  }

  // Stay in the splash window. Closing it and opening another one is the
  // flash the user sees when "正在准备本地服务" finishes.
  const appOrigin = dashboardDev ? windowOrigin : PACKAGED_APP_ORIGIN;
  await continueInEarlyWindow(early, appOrigin);
}

app.whenReady().then(boot).catch((err) => {
  desktopLog().error(`octop-desktop boot failed: ${err instanceof Error ? (err.stack ?? err.message) : String(err)}`);
  app.quit();
});

app.on("second-instance", () => {
  revealAppWindow();
});

// macOS emits this for a Dock click. With no listener the process stays in the
// Dock after the window is closed or hidden, and the click does nothing.
app.on("activate", () => {
  revealAppWindow();
});

/**
 * Ask once, before a user quit throws away running work or unsaved content.
 * Update installs and signals skip the guard; the shell must not stand between
 * the user and an exit.
 */
async function confirmQuitIfNeeded(): Promise<void> {
  const decision = await inspectBeforeQuit({
    reason: quitReason,
    backendPort: apiAdmissionClosed ? 0 : backendPort,
    unsaved: rendererUnsaved,
  });
  const prompt = quitPrompt(decision, app.getLocale());
  if (!prompt) {
    quitConfirmed = true;
    app.quit();
    return;
  }
  const zh = app.getLocale().toLowerCase().startsWith("zh");
  const options = {
    type: "question" as const,
    title: "退出 HappyClaw",
    message: prompt.message,
    detail: prompt.detail,
    buttons: zh ? ["再等等", "仍然退出"] : ["Keep running", "Quit anyway"],
    defaultId: 0,
    cancelId: 0,
    noLink: true,
  };
  const owner = BrowserWindow.getFocusedWindow() ?? dashboardWindow;
  const { response } =
    owner && !owner.isDestroyed()
      ? await dialog.showMessageBox(owner, options)
      : await dialog.showMessageBox(options);
  if (response !== 1) {
    quitGuardRunning = false;
    return;
  }
  quitConfirmed = true;
  quitGuardRunning = false;
  app.quit();
}

app.on("before-quit", (event) => {
  if (quitting) return;
  if (
    quitReason === "user" &&
    !quitConfirmed &&
    !quitGuardRunning &&
    (rendererUnsaved || supervisor !== null)
  ) {
    event.preventDefault();
    quitGuardRunning = true;
    void confirmQuitIfNeeded().catch((err) => {
      // A broken dialog must not trap the user in the app.
      desktopLog().warn(`quit guard failed: ${errorMessageOf(err)}`);
      quitGuardRunning = false;
      quitConfirmed = true;
      app.quit();
    });
    return;
  }

  // §3.4: the sidecar runs in its own process group, so quitting without
  // waiting would orphan Python. Give it the grace window, then really quit.
  event.preventDefault();
  destroySystemTray();
  if (quitReason !== "signal") markCleanExit();
  quitting = true;
  const sidecar = supervisor;
  const relay = wsRelay;
  // Close the relay first: nothing may attach to a sidecar that is shutting
  // down, and its listening socket would keep the process alive otherwise.
  void (async () => {
    stopDashboardDevServer();
    await relay?.stop();
    await sidecar?.stop();
  })()
    .catch((err) =>
      desktopLog().error(
        `octop-desktop quit failed: ${err instanceof Error ? (err.stack ?? err.message) : String(err)}`,
      ),
    )
    .finally(() => app.quit());
});

app.on("will-quit", () => {
  stopHealthWatch();
  globalShortcut.unregisterAll();
});

app.on("window-all-closed", () => {
  // darwin + tray keeps the process so the Dock icon can open the window again.
  // Windows and Linux hide the dashboard window instead of closing it, so this
  // does not fire for that button. A real close (the splash, or closeBehavior
  // quit) still exits.
  if (process.platform !== "darwin" || closeBehavior === "quit") app.quit();
});

/**
 * Terminal Ctrl+C, `kill`, an IDE stop button and a service manager all send a
 * signal rather than a quit event, and the default action kills the shell
 * outright — `before-quit` never runs, so the sidecar survives as an orphan.
 * Python is spawned detached (§3.1) precisely so it is not in the terminal's
 * process group, which means the shell is the only one who can reap it.
 */
let signalReceived = 0;

async function shutdownFromSignal(signal: NodeJS.Signals): Promise<void> {
  signalReceived += 1;
  if (signalReceived > 1) {
    // Second Ctrl+C: the user wants out now, do not wait for the grace window.
    app.exit(0);
    return;
  }
  desktopLog().warn(`[desktop] ${signal} received — stopping the Python sidecar…`);
  // Keep `before-quit` from preventDefault-ing into a second stop attempt; the
  // exit below is deliberate and must not be deferred again.
  quitting = true;
  destroySystemTray();
  try {
    stopDashboardDevServer();
    await wsRelay?.stop();
    await supervisor?.stop();
  } catch (err) {
    desktopLog().error(
      `octop-desktop shutdown failed: ${err instanceof Error ? (err.stack ?? err.message) : String(err)}`,
    );
  } finally {
    // `app.exit` skips `before-quit`/`will-quit`, so nothing can keep the
    // process alive after Python is gone.
    app.exit(0);
  }
}

for (const signal of ["SIGINT", "SIGTERM", "SIGHUP"] as const) {
  // Ctrl+C in a dev terminal is a normal way to stop the app, so exit 0 instead
  // of 130: pnpm prints "ELIFECYCLE Command failed" for non-zero exits.
  process.on(signal, () => void shutdownFromSignal(signal));
}
