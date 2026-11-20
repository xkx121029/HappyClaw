import { useEffect, useRef, useState } from "react";
import { useMotionTokens } from "./MotionProvider";

/**
 * 让「消失」也有结束动作：关闭时保留子树一个出场时长，再真正卸载。
 * 出场一律短于进场，避免拖沓。
 */
export function usePresence(
  open: boolean,
  exitDurationMs?: number,
): { mounted: boolean; closing: boolean } {
  const tokens = useMotionTokens();
  const exitMs = exitDurationMs ?? tokens.duration.fast;
  const [mounted, setMounted] = useState(open);
  const [closing, setClosing] = useState(false);

  useEffect(() => {
    if (open) {
      setMounted(true);
      setClosing(false);
      return;
    }
    if (!mounted) return;
    setClosing(true);
    const timer = window.setTimeout(() => {
      setMounted(false);
      setClosing(false);
    }, exitMs);
    return () => window.clearTimeout(timer);
  }, [open, exitMs, mounted]);

  return { mounted: mounted || open, closing: open ? false : closing };
}

interface NewIdsState {
  key: string | undefined;
  initialized: boolean;
  known: Set<string>;
}

/**
 * 找出本次渲染新增的 id，只让「刚出现」的元素做入场。
 *
 * - 首次渲染（进入会话 / 打开页面）不播动画，避免历史列表集体跳动；
 * - resetKey 变化视为换了一批数据，同样不播；
 * - 一次新增超过 limit 条视为批量载入（历史翻页、重连刷新），整体不播。
 */
export function useNewIds(
  ids: readonly string[],
  resetKey?: string,
  limit = 3,
): ReadonlySet<string> {
  const stateRef = useRef<NewIdsState>({
    key: resetKey,
    initialized: false,
    known: new Set(),
  });

  if (stateRef.current.key !== resetKey) {
    stateRef.current = { key: resetKey, initialized: false, known: new Set() };
  }

  const state = stateRef.current;
  const fresh = new Set<string>();
  if (state.initialized) {
    for (const id of ids) {
      if (!state.known.has(id)) fresh.add(id);
    }
  }
  for (const id of ids) state.known.add(id);
  state.initialized = true;

  return fresh.size > limit ? new Set<string>() : fresh;
}

/**
 * 值变化时给一次「pop」脉冲，用于状态徽章 / 开关等就地变化。
 * 返回 true 的这段时间内给元素挂 octop-status-pop。
 */
export function useValuePulse<T>(value: T, durationMs?: number): boolean {
  const tokens = useMotionTokens();
  const ms = durationMs ?? tokens.duration.slow;
  const prevRef = useRef<T>(value);
  const [pulsing, setPulsing] = useState(false);

  useEffect(() => {
    if (Object.is(prevRef.current, value)) return;
    prevRef.current = value;
    setPulsing(true);
    const timer = window.setTimeout(() => setPulsing(false), ms);
    return () => window.clearTimeout(timer);
  }, [value, ms]);

  return pulsing;
}
