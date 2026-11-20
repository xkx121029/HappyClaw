import { useEffect, type ReactNode } from "react";
import { useLocation } from "react-router-dom";

import { MobileTabBar } from "./components/MobileTabBar";
import { MobileToastHost } from "./components/MobileToast";
import { isMobileTabRoot } from "./mobileNav";
import { useMobileKeyboardOpen } from "./hooks/useVisualViewportInset";
import "./mobile.css";

/** App shell: fixed viewport, page outlet, bottom tabs, toast host. */
export function MobileAppShell({ children }: { children: ReactNode }) {
  const location = useLocation();
  const keyboardOpen = useMobileKeyboardOpen();
  // Chat detail pages are still part of the first-class 对话 tab, so the bar
  // stays visible (and keeps the active state) while a conversation is open.
  const inChatTab =
    isMobileTabRoot(location.pathname) ||
    location.pathname.startsWith("/m/chat/");
  const showTab = inChatTab && !keyboardOpen;

  useEffect(() => {
    const previous = document.documentElement.style.overscrollBehavior;
    document.documentElement.style.overscrollBehavior = "none";
    document.body.classList.add("m-body");
    return () => {
      document.documentElement.style.overscrollBehavior = previous;
      document.body.classList.remove("m-body");
    };
  }, []);

  return (
    <div className="m-app" data-testid="m-app">
      <div className="m-outlet">{children}</div>
      {showTab ? <MobileTabBar /> : null}
      <MobileToastHost />
    </div>
  );
}
