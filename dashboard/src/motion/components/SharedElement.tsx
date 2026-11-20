import { createElement, useEffect, useRef, type CSSProperties } from "react";
import cx from "classnames";
import { useMotionTokens } from "../MotionProvider";
import { takeSharedRect } from "../sharedElements";

interface SharedElementProps {
  /** 前后两处元素一致的标识，例如 job-123、agent-7。 */
  id: string;
  children: React.ReactNode;
  className?: string;
  style?: CSSProperties;
  as?: "span" | "div" | "strong" | "h2" | "h3";
  /** 变化时重试一次（例如详情抽屉打开后）。 */
  activeKey?: unknown;
  /** 等容器动画结束再起飞，避免和抽屉滑入打架。 */
  delayMs?: number;
  title?: string;
}

/**
 * 共享元素目标位。挂载（或 activeKey 变化）时如果存在来源位置记录，
 * 就从来源位置平移缩放到自己这里；没有记录则完全不动。
 */
export function SharedElement({
  id,
  children,
  className,
  style,
  as = "span",
  activeKey,
  delayMs = 0,
  title,
}: SharedElementProps) {
  const ref = useRef<HTMLElement | null>(null);
  const tokens = useMotionTokens();
  const slow = tokens.duration.slow;
  const reduced = tokens.reduced;

  useEffect(() => {
    const el = ref.current;
    if (!el || reduced) return;

    let animation: Animation | null = null;
    let retryTimer = 0;

    const play = (): boolean => {
      const from = takeSharedRect(id);
      if (!from) return false;
      const to = el.getBoundingClientRect();
      if (!to.width || !to.height) return false;

      const dx = from.left - to.left;
      const dy = from.top - to.top;
      const scaleX = from.width / to.width;
      const scaleY = from.height / to.height;
      if (
        Math.abs(dx) < 2 &&
        Math.abs(dy) < 2 &&
        Math.abs(scaleX - 1) < 0.02 &&
        Math.abs(scaleY - 1) < 0.02
      ) {
        return true;
      }

      el.style.transformOrigin = "top left";
      animation = el.animate(
        [
          {
            transform: `translate(${dx}px, ${dy}px) scale(${scaleX}, ${scaleY})`,
            opacity: 0.4,
          },
          { transform: "none", opacity: 1 },
        ],
        {
          duration: slow,
          delay: delayMs,
          easing: tokens.enterEase,
          fill: "backwards",
        },
      );
      return true;
    };

    // 目标页比来源页晚一拍挂载（懒加载、退出层还在场）时，再补一次。
    if (!play()) {
      retryTimer = window.setTimeout(play, 160);
    }

    return () => {
      window.clearTimeout(retryTimer);
      animation?.cancel();
      el.style.transformOrigin = "";
    };
  }, [id, activeKey, delayMs, reduced, slow, tokens.enterEase]);

  return createElement(
    as,
    {
      ref,
      className: cx(className),
      style,
      title,
      "data-shared-id": id,
    },
    children,
  );
}
