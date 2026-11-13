import { useCallback, useEffect, useState, type RefObject } from "react";

/**
 * SOLO 页面分栏布局。
 *
 * 宽度只存"用户想要的尺寸"，实际渲染时按容器宽度收敛（``fitWidths``），
 * 因此窄屏不会把某一栏挤到不可操作，也不会改写用户在大屏下调好的偏好。
 */

export interface SoloLayout {
  /** 会话选择器展开宽度。 */
  rail: number;
  /** agent 对话区宽度。 */
  chat: number;
  /** 文件树宽度。 */
  tree: number;
  /** 终端占编辑器列高度的比例（0-1）。 */
  terminal: number;
}

const STORAGE_KEY = "octop-solo-layout-v1";

export const RAIL_COLLAPSED_WIDTH = 48;
export const RAIL_MIN_WIDTH = 168;
export const RAIL_MAX_WIDTH = 300;
export const CHAT_MIN_WIDTH = 280;
/** 极端窄屏下的最后底线，低于此值对话区不可用。 */
const CHAT_ABSOLUTE_MIN = 220;
export const CHAT_MAX_WIDTH = 640;
export const TREE_MIN_WIDTH = 160;
export const TREE_MAX_WIDTH = 420;
export const SPLITTER_WIDTH = 6;
export const EDITOR_MIN_WIDTH = 280;
export const TERMINAL_MIN_RATIO = 0.16;
export const TERMINAL_MAX_RATIO = 0.7;

/** 低于该宽度时选择器自动收成图标栏。 */
export const RAIL_AUTO_COLLAPSE_WIDTH = 1120;

const DEFAULTS: SoloLayout = {
  rail: 208,
  chat: 360,
  tree: 220,
  terminal: 0.32,
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
    if (!raw) return DEFAULTS;
    const parsed = JSON.parse(raw) as Partial<SoloLayout>;
    return {
      rail: clamp(
        positive(parsed.rail, DEFAULTS.rail),
        RAIL_MIN_WIDTH,
        RAIL_MAX_WIDTH,
      ),
      chat: clamp(
        positive(parsed.chat, DEFAULTS.chat),
        CHAT_MIN_WIDTH,
        CHAT_MAX_WIDTH,
      ),
      tree: clamp(
        positive(parsed.tree, DEFAULTS.tree),
        TREE_MIN_WIDTH,
        TREE_MAX_WIDTH,
      ),
      terminal: clamp(
        positive(parsed.terminal, DEFAULTS.terminal),
        TERMINAL_MIN_RATIO,
        TERMINAL_MAX_RATIO,
      ),
    };
  } catch {
    return DEFAULTS;
  }
}

export interface FittedWidths {
  rail: number;
  chat: number;
  tree: number;
  /** 容器太窄时文件树让位，由调用方决定以浮层方式打开。 */
  treeFitted: boolean;
}

/**
 * 把偏好宽度压进容器：先压对话区、再压文件树、最后压选择器，
 * 始终保证编辑器至少 ``EDITOR_MIN_WIDTH``。
 */
export function fitWidths(
  available: number,
  rail: number,
  chat: number,
  tree: number,
): FittedWidths {
  let nextRail = rail;
  let nextChat = chat;
  let nextTree = tree;

  const panes = () => nextRail + nextChat + nextTree;
  const budget = () =>
    available - SPLITTER_WIDTH * 2 - EDITOR_MIN_WIDTH - (nextTree > 0 ? SPLITTER_WIDTH : 0);

  let overflow = panes() - budget();
  if (overflow > 0) {
    const take = Math.min(overflow, Math.max(0, nextChat - CHAT_MIN_WIDTH));
    nextChat -= take;
    overflow -= take;
  }
  if (overflow > 0) {
    const take = Math.min(overflow, Math.max(0, nextTree - TREE_MIN_WIDTH));
    nextTree -= take;
    overflow -= take;
  }
  if (overflow > 0 && nextTree >= TREE_MIN_WIDTH) {
    nextTree = 0;
    overflow = panes() - (available - SPLITTER_WIDTH * 2 - EDITOR_MIN_WIDTH);
  }
  if (overflow > 0) {
    const take = Math.min(
      overflow,
      Math.max(0, nextRail - RAIL_COLLAPSED_WIDTH),
    );
    nextRail -= take;
    overflow -= take;
  }
  if (overflow > 0) {
    // 极端窄屏（<700）时连图标栏 + 对话最小宽都放不下，最后才允许对话区
    // 压到 220，保证编辑器始终可用。
    const take = Math.min(overflow, Math.max(0, nextChat - CHAT_ABSOLUTE_MIN));
    nextChat -= take;
  }
  if (available < 720) {
    nextRail = RAIL_COLLAPSED_WIDTH;
  }
  return {
    rail: Math.round(nextRail),
    chat: Math.round(nextChat),
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
    (key: "rail" | "chat" | "tree", width: number) => {
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

  return { layout, setPaneWidth, setTerminalRatio };
}
