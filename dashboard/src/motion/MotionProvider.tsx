import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  DEFAULT_MOTION_PREFS,
  applyMotionPrefs,
  normalizeBezier,
  prefersReducedMotion,
  readMotionPrefs,
  writeMotionPrefs,
  type MotionPrefs,
} from "./motionPrefs";
import {
  resolveMotionTokens,
  type Bezier,
  type MotionCurvePreset,
  type MotionSpeed,
  type ResolvedMotionTokens,
} from "./tokens";

interface MotionContextValue {
  prefs: MotionPrefs;
  tokens: ResolvedMotionTokens;
  /** 系统「减少动态效果」是否开启。开启后位移/缩放归零。 */
  reduced: boolean;
  setCurve: (curve: MotionCurvePreset) => void;
  setSpeed: (speed: MotionSpeed) => void;
  setCustomCurve: (curve: Bezier) => void;
  reset: () => void;
}

const fallbackTokens = resolveMotionTokens(DEFAULT_MOTION_PREFS, false);

const MotionContext = createContext<MotionContextValue>({
  prefs: DEFAULT_MOTION_PREFS,
  tokens: fallbackTokens,
  reduced: false,
  setCurve: () => {},
  setSpeed: () => {},
  setCustomCurve: () => {},
  reset: () => {},
});

export function MotionProvider({ children }: { children: ReactNode }) {
  const [prefs, setPrefs] = useState<MotionPrefs>(() => {
    const stored = readMotionPrefs();
    // 首帧前就落变量，避免先按默认曲线闪一下。
    applyMotionPrefs(stored, prefersReducedMotion());
    return stored;
  });
  const [reduced, setReduced] = useState<boolean>(() =>
    prefersReducedMotion(),
  );

  // 跟随系统偏好实时切换，不需要用户手动刷新。
  useEffect(() => {
    if (!window.matchMedia) return;
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const handler = () => setReduced(mq.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  useEffect(() => {
    applyMotionPrefs(prefs, reduced);
  }, [prefs, reduced]);

  const commit = useCallback((next: MotionPrefs) => {
    writeMotionPrefs(next);
    setPrefs(next);
  }, []);

  const setCurve = useCallback(
    (curve: MotionCurvePreset) => {
      setPrefs((prev) => {
        const next = { ...prev, curve };
        writeMotionPrefs(next);
        return next;
      });
    },
    [],
  );

  const setSpeed = useCallback((speed: MotionSpeed) => {
    setPrefs((prev) => {
      const next = { ...prev, speed };
      writeMotionPrefs(next);
      return next;
    });
  }, []);

  const setCustomCurve = useCallback((curve: Bezier) => {
    setPrefs((prev) => {
      const next = { ...prev, custom: normalizeBezier(curve) };
      writeMotionPrefs(next);
      return next;
    });
  }, []);

  const reset = useCallback(() => {
    commit({ ...DEFAULT_MOTION_PREFS });
  }, [commit]);

  const tokens = useMemo(
    () => resolveMotionTokens(prefs, reduced),
    [prefs, reduced],
  );

  const value = useMemo<MotionContextValue>(
    () => ({
      prefs,
      tokens,
      reduced,
      setCurve,
      setSpeed,
      setCustomCurve,
      reset,
    }),
    [prefs, tokens, reduced, setCurve, setSpeed, setCustomCurve, reset],
  );

  return (
    <MotionContext.Provider value={value}>{children}</MotionContext.Provider>
  );
}

export function useMotion(): MotionContextValue {
  return useContext(MotionContext);
}

/** 只关心数值的场景（图表、canvas、WAAPI）。 */
export function useMotionTokens(): ResolvedMotionTokens {
  return useContext(MotionContext).tokens;
}

export function useReducedMotion(): boolean {
  return useContext(MotionContext).reduced;
}
