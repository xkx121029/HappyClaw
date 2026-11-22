import type { EarlyShellBridge } from "./preload/early";
import type { HappyclawDesktopBridge } from "./preload/index";

declare global {
  interface Window {
    octopDesktop?: HappyclawDesktopBridge;
    /**
     * Bridge for the shell's own pages (splash + fatal error). Those pages are
     * separate documents from the Dashboard and expose one method, not the
     * Dashboard's API.
     */
    octopShell?: EarlyShellBridge;
  }
}

export {};
