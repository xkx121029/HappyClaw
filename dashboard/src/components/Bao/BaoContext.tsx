import {
  createContext,
  lazy,
  Suspense,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";

import type { BaoSettings } from "../../api/modules/bao";
import {
  DEFAULT_MASCOT_APPEARANCE,
  syncMascotAppearance,
  type MascotAppearance,
} from "../Mascot/appearance";
import type { MascotInk, MascotShape } from "../Mascot";
import type { BaoTaskRecord } from "./baoTaskStore";
import { useBaoSettings, useBaoTasks } from "./useBaoData";

// Both dialogs are only mounted once the user opens them, but a static import
// put their markup and styles in the shell bundle for every page.
const BaoNamingDialog = lazy(() => import("./BaoNamingDialog"));
const BaoOnboarding = lazy(() => import("./BaoOnboarding"));

const NAME_KEY = "octop.bao.name.v1";

function readStoredName(): string | null {
  try {
    return window.localStorage.getItem(NAME_KEY);
  } catch {
    return null;
  }
}

function writeStoredName(name: string) {
  try {
    window.localStorage.setItem(NAME_KEY, name);
  } catch {
    // Private mode / storage denied: the server copy is still authoritative.
  }
}

/** Everything the mascot needs to draw Bao; spread straight onto ``Mascot``. */
export type BaoAppearance = MascotAppearance;

export const DEFAULT_BAO_APPEARANCE = DEFAULT_MASCOT_APPEARANCE;

interface BaoContextValue {
  tasks: BaoTaskRecord[];
  refreshTasks: () => Promise<void>;
  /** Display name for the mascot. Falls back to the localized default. */
  name: string;
  /** Silhouette, ink and custom colours, saved in the user's preferences. */
  appearance: BaoAppearance;
  /** Persist a new appearance and update every surface that draws Bao. */
  setAppearance: (
    patch: Partial<Pick<BaoSettings, "shape" | "color" | "body_color" | "eye_color" | "follow_theme">>,
  ) => Promise<void>;
  /** ``false`` until the user has named Bao (or skipped the prompt). */
  named: boolean;
  setName: (next: string) => Promise<void>;
  /** Naming / rename dialog visibility. */
  namingOpen: boolean;
  openNaming: () => void;
  closeNaming: () => void;
  settings: BaoSettings | null;
  muted: boolean;
  setMuted: (muted: boolean) => Promise<void>;
  onboardingOpen: boolean;
  finishOnboarding: () => Promise<void>;
  /** Re-open the first-run guide (e.g. from Settings after skipping it). */
  openOnboarding: () => void;
}

/**
 * Default value keeps standalone renders (unit tests, embedded sidebar) safe:
 * the list is empty, refresh is inert, and the mascot keeps its default name.
 */
const BaoContext = createContext<BaoContextValue>({
  tasks: [],
  refreshTasks: async () => {},
  name: "宝",
  appearance: DEFAULT_BAO_APPEARANCE,
  setAppearance: async () => {},
  named: true,
  setName: async () => {},
  namingOpen: false,
  openNaming: () => {},
  closeNaming: () => {},
  settings: null,
  muted: false,
  setMuted: async () => {},
  onboardingOpen: false,
  finishOnboarding: async () => {},
  openOnboarding: () => {},
});

export function useBao(): BaoContextValue {
  return useContext(BaoContext);
}

const BAO_PATH = "/bao";

/**
 * Shell-level Bao state.
 *
 * The name and mute switch live in the user's server-side preferences, so they
 * survive a restart and follow the user to every surface (sidebar, project row,
 * page title, proactive notifications). The dispatch ledger is server-backed;
 * results arrive through the Worker turn-completion writeback.
 */
export function BaoProvider({ children }: { children: ReactNode }) {
  const location = useLocation();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const onBaoPage = location.pathname === BAO_PATH;
  const { tasks, refreshTasks } = useBaoTasks(onBaoPage);
  const { settings, update } = useBaoSettings(true);
  const [storedName, setStoredName] = useState<string | null>(readStoredName);
  const [namingOpen, setNamingOpen] = useState(false);
  const [onboardingOpen, setOnboardingOpen] = useState(false);

  const name = settings?.name || storedName || t("bao.identity.defaultName", "宝");
  const named = settings ? settings.identity_set : storedName !== null;
  // Older servers omit these fields; the engine defaults keep rendering stable.
  const appearance = useMemo<BaoAppearance>(
    () => ({
      shape: (settings?.shape ?? DEFAULT_BAO_APPEARANCE.shape) as MascotShape,
      color: (settings?.color ?? DEFAULT_BAO_APPEARANCE.color) as MascotInk,
      bodyColor: settings?.body_color ?? null,
      eyeColor: settings?.eye_color ?? null,
      followTheme: settings?.follow_theme ?? false,
    }),
    [settings],
  );

  // Publish the saved look so every mascot surface — including ones rendered
  // outside this provider — paints the same Bao.
  useEffect(() => {
    if (!settings) return;
    syncMascotAppearance(appearance);
  }, [appearance, settings]);

  // Steps that send the user to Settings close the dialog without marking the
  // guide as done. Coming back to the conversation resumes it with fresh status.
  const onChatPage = location.pathname.startsWith("/chat");
  useEffect(() => {
    if (!settings) return;
    if (!settings.identity_set) {
      setNamingOpen(true);
      return;
    }
    // The guide lives on the conversation page. It must never sit on top of the
    // settings page the user was just sent to.
    setOnboardingOpen(!settings.onboarding_done && onChatPage);
  }, [settings, onChatPage]);

  const openOnboarding = useCallback(() => setOnboardingOpen(true), []);

  // "Rename" inside the guide closes it and opens the naming dialog. When that
  // dialog is dismissed the guide must come back instead of leaving the user
  // stranded on the chat page.
  const resumeGuideRef = useRef(false);
  const openNaming = useCallback(() => {
    resumeGuideRef.current =
      location.pathname.startsWith("/chat") && Boolean(settings && !settings.onboarding_done);
    setNamingOpen(true);
  }, [location.pathname, settings]);
  const resumeGuideIfNeeded = useCallback(() => {
    if (!resumeGuideRef.current) return;
    resumeGuideRef.current = false;
    setOnboardingOpen(true);
  }, []);

  const setName = useCallback(
    async (raw: string) => {
      const next = raw.trim().slice(0, 12);
      if (!next) return;
      writeStoredName(next);
      setStoredName(next);
      setNamingOpen(false);
      try {
        await update({ name: next });
      } catch {
        // Keep the local name this session; the next settings load reconciles.
      }
      resumeGuideIfNeeded();
    },
    [resumeGuideIfNeeded, update],
  );

  const setMuted = useCallback(
    async (muted: boolean) => {
      await update({ proactive_muted: muted });
    },
    [update],
  );

  const setAppearance = useCallback(
    async (
      patch: Partial<
        Pick<BaoSettings, "shape" | "color" | "body_color" | "eye_color" | "follow_theme">
      >,
    ) => {
      await update(patch);
    },
    [update],
  );

  const closeNaming = useCallback(() => {
    setNamingOpen(false);
    // An explicit skip still counts as the first-run introduction; it must not
    // pop up again on every page load.
    if (settings && !settings.identity_set) {
      void update({ identity_set: true });
    }
    resumeGuideIfNeeded();
  }, [resumeGuideIfNeeded, settings, update]);

  const finishOnboarding = useCallback(async () => {
    setOnboardingOpen(false);
    try {
      await update({ onboarding_done: true });
    } catch {
      // Closing the dialog is enough for this session.
    }
  }, [update]);

  const focusComposer = useCallback(() => {
    window.dispatchEvent(new CustomEvent("octop:bao:focus-composer"));
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (!event.altKey || event.ctrlKey || event.metaKey) return;
      if (event.key.toLowerCase() !== "b") return;
      event.preventDefault();
      if (onBaoPage) focusComposer();
      else navigate(BAO_PATH);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [focusComposer, navigate, onBaoPage]);

  const value = useMemo<BaoContextValue>(
    () => ({
      tasks,
      refreshTasks,
      name,
      appearance,
      setAppearance,
      named,
      setName,
      namingOpen,
      openNaming,
      closeNaming,
      settings,
      muted: Boolean(settings?.proactive_muted),
      setMuted,
      onboardingOpen,
      finishOnboarding,
      openOnboarding,
    }),
    [
      refreshTasks,
      tasks,
      name,
      appearance,
      setAppearance,
      named,
      setName,
      namingOpen,
      openNaming,
      closeNaming,
      settings,
      setMuted,
      onboardingOpen,
      finishOnboarding,
      openOnboarding,
    ],
  );

  return (
    <BaoContext.Provider value={value}>
      {children}
      {(namingOpen || onboardingOpen) && (
        <Suspense fallback={null}>
          {namingOpen && (
            <BaoNamingDialog
              open
              initialName={settings?.name ?? storedName ?? ""}
              firstRun={!named}
              onCancel={closeNaming}
              onSubmit={setName}
            />
          )}
          {onboardingOpen && (
            <BaoOnboarding
              open
              name={name}
              onNavigate={() => setOnboardingOpen(false)}
              onSkip={finishOnboarding}
              onDone={finishOnboarding}
            />
          )}
        </Suspense>
      )}
    </BaoContext.Provider>
  );
}
