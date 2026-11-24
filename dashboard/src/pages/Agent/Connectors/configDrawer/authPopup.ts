import { tryOpenAuthPopup } from "../openAuthWindow";

/** Open sync under the click gesture so popup blockers don't swallow async opens. */
export function openAuthPopupPlaceholder(): Window | null {
  const popup = tryOpenAuthPopup(
    "about:blank",
    "octop-connector-auth",
    "width=720,height=800",
  );
  if (popup) {
    try {
      popup.document.title = "Feishu Auth";
      popup.document.body.innerHTML =
        '<p style="font:14px/1.5 system-ui;padding:24px;color:#666">Loading…</p>';
    } catch {
      // Cross-origin / closed — ignore.
    }
  }
  return popup;
};
