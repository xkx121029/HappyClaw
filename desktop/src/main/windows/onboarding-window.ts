import { BrowserWindow } from "electron";

import {
  concealWindowsMenuBar,
  windowBackground,
  windowChrome,
  type WindowChromeTheme,
} from "./chrome";

/**
 * The two-step first-run guide, and the Help → "首次引导" entry that reopens it.
 *
 * It is a separate small window on purpose: the single-user launch goes
 * straight to the Dashboard, and a guide that blocks the first screen would be
 * exactly the initialisation detour this build removes.
 */

export const ONBOARDING_SIZE = { width: 560, height: 600 } as const;

export function createOnboardingWindow(options: {
  file: string;
  preload: string;
  theme: WindowChromeTheme;
  parent?: BrowserWindow | null;
}): BrowserWindow {
  const win = new BrowserWindow({
    title: "欢迎使用 HappyClaw",
    width: ONBOARDING_SIZE.width,
    height: ONBOARDING_SIZE.height,
    show: false,
    resizable: false,
    minimizable: false,
    maximizable: false,
    fullscreenable: false,
    ...(options.parent && !options.parent.isDestroyed()
      ? { parent: options.parent }
      : {}),
    ...windowChrome(options.theme.mode),
    backgroundColor: windowBackground(options.theme.mode),
    webPreferences: {
      preload: options.preload,
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  concealWindowsMenuBar(win);
  win.once("ready-to-show", () => {
    if (win.isDestroyed()) return;
    const parent = options.parent;
    if (parent && !parent.isDestroyed() && parent.isVisible()) {
      const bounds = parent.getBounds();
      win.setPosition(
        Math.round(bounds.x + (bounds.width - ONBOARDING_SIZE.width) / 2),
        Math.round(bounds.y + (bounds.height - ONBOARDING_SIZE.height) / 2),
      );
    } else {
      win.center();
    }
    win.show();
    win.focus();
  });
  void win.loadFile(options.file, { query: { theme: options.theme.mode } });
  return win;
}
