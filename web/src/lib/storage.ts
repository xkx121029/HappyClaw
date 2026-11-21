/**
 * localStorage that never throws — Safari private mode and some embedded
 * webviews reject even reads. UI preferences are best-effort by design.
 */
export function readStored(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writeStored(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* preference is not worth failing a render over */
  }
}

export const storageKeys = {
  theme: "happyclaw.theme",
  locale: "happyclaw.locale",
  sidebarCollapsed: "happyclaw.sidebar-collapsed",
  chatDraft: "happyclaw.chat-draft",
} as const;
