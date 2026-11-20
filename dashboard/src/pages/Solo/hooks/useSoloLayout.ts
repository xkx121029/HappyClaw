import { useCallback, useEffect, useState, type RefObject } from "react";

/**
 * SOLO 页面三栏布局（会话列表 / 对话 / 编辑器 + 右侧文件树）。
 *
 * 宽度只存"用户想要的尺寸"，渲染时按容器宽度收敛（``fitWidths``），
 * 因此窄屏不会把编辑器挤到不可用，也不会改写用户在大屏下调好的偏好。
 * 度量对齐参照稿 ``solo-ide_(4).html``：分栏条视觉 5px、两侧 -2px，布局占位 1px。
 */

export interface SoloLayout {
  /** 左侧会话列表栏，参照稿 215。 */
  side: number;
  /** 对话栏，参照稿 660。 */
  agent: number;
  /** 右侧文件树，参照稿 230。 */
  tree: number;
  /** AI 动作时间线占中间列高度的比例（0-1）。 */
  timeline: number;
  /** 终端占编辑器列高度的比例（0-1）。 */
  terminal: number;
}

const STORAGE_KEY = "octop-solo-layout-v3";

export const SIDE_MIN_WIDTH = 150;
export const SIDE_MAX_WIDTH = 420;
export const AGENT_MIN_WIDTH = 400;
export const AGENT_MAX_WIDTH = 1000;
/** 极端窄屏下的最后底线，低于此值对话区不可用。 */
export const AGENT_ABSOLUTE_MIN = 340;
export const TREE_MIN_WIDTH = 160;
export const TREE_MAX_WIDTH = 520;
export const EDITOR_MIN_WIDTH = 320;

/** 分栏条视觉宽度（参照稿 .rz / .treesplit）。 */
export const SPLITTER_WIDTH = 5;
/** 分栏条两侧负外边距（参照稿 margin: 0 -2px）。 */
export const SPLITTER_INSET = 2;
/** 分栏条在布局中实际占位：5 - 2*2 = 1。 */
export const SPLITTER_GAP = SPLITTER_WIDTH - SPLITTER_INSET * 2;

export const TERMINAL_MIN_RATIO = 0.16;
export const TERMINAL_MAX_RATIO = 0.7;
export const TIMELINE_MIN_RATIO = 0.18;
export const TIMELINE_MAX_RATIO = 0.6;

/**
 * 低于该宽度时文件树让位，改用浮层打开。
 * 取值正好是「三栏最小宽 + 编辑器最小 + 三条分栏条占位」。
 */
export const TREE_AUTO_COLLAPSE_WIDTH =
  SIDE_MIN_WIDTH +
  AGENT_MIN_WIDTH +
  TREE_MIN_WIDTH +
  EDITOR_MIN_WIDTH +
  SPLITTER_GAP * 3;

export const DEFAULT_LAYOUT: SoloLayout = {
  side: 215,
  agent: 660,
  tree: 230,
  timeline: 0.34,
  terminal: 0.28,
};

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function positive(value: unknown, fallback: number): number {
  const num = Number(value);
  return Number.isFinite(num) && num > 0 ? num : fallback;
}

function loadLayout(): SoloLayout {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_LAYOUT;
    const parsed = JSON.parse(raw) as Partial<SoloLayout>;
    return {
      side: clamp(
        positive(parsed.side, DEFAULT_LAYOUT.side),
        SIDE_MIN_WIDTH,
        SIDE_MAX_WIDTH,
      ),
      agent: clamp(
        positive(parsed.agent, DEFAULT_LAYOUT.agent),
        AGENT_MIN_WIDTH,
        AGENT_MAX_WIDTH,
      ),
      tree: clamp(
        positive(parsed.tree, DEFAULT_LAYOUT.tree),
        TREE_MIN_WIDTH,
        TREE_MAX_WIDTH,
      ),
      timeline: clamp(
        positive(parsed.timeline, DEFAULT_LAYOUT.timeline),
        TIMELINE_MIN_RATIO,
        TIMELINE_MAX_RATIO,
      ),
      terminal: clamp(
        positive(parsed.terminal, DEFAULT_LAYOUT.terminal),
        TERMINAL_MIN_RATIO,
        TERMINAL_MAX_RATIO,
      ),
    };
  } catch {
    return DEFAULT_LAYOUT;
  }
}

export interface FittedWidths {
  side: number;
  agent: number;
  tree: number;
  /** 容器太窄时文件树让位，由调用方决定以浮层方式打开。 */
  treeFitted: boolean;
}

/**
 * 把偏好宽度压进容器，始终保证编辑器至少 ``EDITOR_MIN_WIDTH``：
 * 依次扣减 agent → tree → side；仍不够时文件树让位并重算；最后把 agent 压到底线。
 */
export function fitWidths(
  available: number,
  side: number,
  agent: number,
  tree: number,
): FittedWidths {
  let nextSide = side;
  let nextAgent = agent;
  let nextTree = available < TREE_AUTO_COLLAPSE_WIDTH ? 0 : tree;

  const budget = () =>
    available -
    EDITOR_MIN_WIDTH -
    SPLITTER_GAP * (nextTree > 0 ? 3 : 2);

  let overflow = nextSide + nextAgent + nextTree - budget();
  if (overflow > 0) {
    const take = Math.min(overflow, Math.max(0, nextAgent - AGENT_MIN_WIDTH));
    nextAgent -= take;
    overflow -= take;
  }
  if (overflow > 0) {
    const take = Math.min(overflow, Math.max(0, nextTree - TREE_MIN_WIDTH));
    nextTree -= take;
    overflow -= take;
  }
  if (overflow > 0) {
    const take = Math.min(overflow, Math.max(0, nextSide - SIDE_MIN_WIDTH));
    nextSide -= take;
    overflow -= take;
  }
  if (overflow > 0 && nextTree > 0) {
    nextTree = 0;
    overflow = nextSide + nextAgent - budget();
  }
  if (overflow > 0) {
    const take = Math.min(
      overflow,
      Math.max(0, nextAgent - AGENT_ABSOLUTE_MIN),
    );
    nextAgent -= take;
  }

  return {
    side: Math.round(nextSide),
    agent: Math.round(nextAgent),
    tree: Math.round(nextTree),
    treeFitted: nextTree > 0,
  };
}

/** 监听元素自身宽度（布局容器），返回像素值。 */
export function useElementWidth(
  ref: RefObject<HTMLElement | null>,
  fallback = 1280,
): number {
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const update = () => setWidth(node.getBoundingClientRect().width || fallback);
    update();
    const observer = new ResizeObserver(update);
    observer.observe(node);
    return () => observer.disconnect();
  }, [ref, fallback]);
  return width;
}

export function useSoloLayout() {
  const [layout, setLayout] = useState<SoloLayout>(loadLayout);

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(layout));
    } catch {
      // 隐私模式下写失败不影响使用
    }
  }, [layout]);

  const setPaneWidth = useCallback(
    (key: "side" | "agent" | "tree", width: number) => {
      setLayout((prev) => ({ ...prev, [key]: Math.round(width) }));
    },
    [],
  );

  const setTerminalRatio = useCallback((ratio: number) => {
    setLayout((prev) => ({
      ...prev,
      terminal: clamp(ratio, TERMINAL_MIN_RATIO, TERMINAL_MAX_RATIO),
    }));
  }, []);

  const setTimelineRatio = useCallback((ratio: number) => {
    setLayout((prev) => ({
      ...prev,
      timeline: clamp(ratio, TIMELINE_MIN_RATIO, TIMELINE_MAX_RATIO),
    }));
  }, []);

  return { layout, setPaneWidth, setTerminalRatio, setTimelineRatio };
}
