import {
  useCallback,
  useEffect,
  useRef,
  type CSSProperties,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import cx from "classnames";
import { useMotionTokens } from "../MotionProvider";
import styles from "./BeamCardReveal.module.less";

export interface BeamOrigin {
  x: number;
  y: number;
}

interface BeamCardRevealProps {
  /** 打开时才播放光束；关闭由外层直接卸载。 */
  open: boolean;
  children: ReactNode;
  className?: string;
  /**
   * 光束起点（视口坐标）。缺省取主页活动核心的发射口：
   * 半圆圆心贴右边缘，发射点在圆心左侧一个半径处。
   */
  origin?: BeamOrigin | null;
  /** Esc 或内部打断时回调；外层负责把卡片收回去。 */
  onCancel?: () => void;
  style?: CSSProperties;
}

/** 主页活动核心的默认发射口，与 ActivityCore 的半圆几何保持一致。 */
export function defaultBeamOrigin(): BeamOrigin {
  if (typeof window === "undefined") return { x: 0, y: 0 };
  const width = window.innerWidth;
  const height = window.innerHeight;
  const radius = Math.min(width * 0.36, height * 0.38);
  return { x: Math.max(0, width - radius), y: height * 0.5 };
}

/**
 * 提问卡片的光束出场：一束光从活动核心射出 → 光斑放大铺开 → 收拢成卡片。
 *
 * 全部使用 Web Animations API 驱动 transform / opacity：
 * - 可中断：Esc 或组件卸载会 cancel 所有动画，并立即落到稳定状态；
 * - 不挡操作：光层 pointer-events: none，卡片本身从第一帧就可点击；
 * - 减少动态效果：直接显示卡片，不播放光束。
 */
export function BeamCardReveal({
  open,
  children,
  className,
  origin,
  onCancel,
  style,
}: BeamCardRevealProps) {
  const tokens = useMotionTokens();
  const cardRef = useRef<HTMLDivElement | null>(null);
  const layerRef = useRef<HTMLDivElement | null>(null);
  const rayRef = useRef<HTMLDivElement | null>(null);
  const bloomRef = useRef<HTMLDivElement | null>(null);
  const headRef = useRef<HTMLDivElement | null>(null);
  const animsRef = useRef<Animation[]>([]);
  const finishedRef = useRef(false);

  const stopAnimations = useCallback(() => {
    for (const anim of animsRef.current) {
      try {
        anim.cancel();
      } catch {
        // 动画可能已经结束并从合成器移除
      }
    }
    animsRef.current = [];
  }, []);

  const settle = useCallback(() => {
    stopAnimations();
    finishedRef.current = true;
    if (cardRef.current) {
      cardRef.current.style.opacity = "1";
      cardRef.current.style.transform = "none";
    }
    layerRef.current?.style.setProperty("display", "none");
  }, [stopAnimations]);

  useEffect(() => {
    if (!open) {
      stopAnimations();
      return;
    }
    if (tokens.reduced) {
      settle();
      return;
    }
    const card = cardRef.current;
    const layer = layerRef.current;
    const ray = rayRef.current;
    const bloom = bloomRef.current;
    const head = headRef.current;
    if (!card || !layer || !ray || !bloom || !head) return;

    // 先把上一次的收尾样式清掉，再按真实布局测量。
    card.style.opacity = "0";
    card.style.transform = "";
    layer.style.display = "block";
    finishedRef.current = false;

    const rect = card.getBoundingClientRect();
    const targetX = rect.left + rect.width / 2;
    const targetY = rect.top + rect.height / 2;
    const start = origin ?? defaultBeamOrigin();
    const dx = targetX - start.x;
    const dy = targetY - start.y;
    const length = Math.hypot(dx, dy);
    const angle = Math.atan2(dy, dx);

    ray.style.left = `${start.x}px`;
    ray.style.top = `${start.y}px`;
    ray.style.width = `${length}px`;
    ray.style.transform = `rotate(${angle}rad) scaleX(0)`;

    head.style.left = `${start.x}px`;
    head.style.top = `${start.y}px`;

    const rayMs = tokens.duration.fast * 1.6;
    const bloomMs = tokens.duration.slower;
    const cardMs = tokens.duration.slow;
    const enter = tokens.enterEase;

    const animations: Animation[] = [
      ray.animate(
        [
          { transform: `rotate(${angle}rad) scaleX(0)`, opacity: 0 },
          { opacity: 1, offset: 0.16 },
          {
            transform: `rotate(${angle}rad) scaleX(1)`,
            opacity: 1,
            offset: 0.62,
          },
          { transform: `rotate(${angle}rad) scaleX(1)`, opacity: 0 },
        ],
        { duration: rayMs * 1.5, easing: enter, fill: "both" },
      ),
      head.animate(
        [
          { transform: "translate(-50%, -50%) scale(0.4)", opacity: 0.9 },
          {
            transform: "translate(-50%, -50%) scale(1)",
            opacity: 1,
            offset: 0.7,
          },
          { transform: "translate(-50%, -50%) scale(0.2)", opacity: 0 },
        ],
        { duration: rayMs * 1.3, easing: "ease-out", fill: "both" },
      ),
      bloom.animate(
        [
          { transform: "translate(-50%, -50%) scale(0.18)", opacity: 0 },
          {
            transform: "translate(-50%, -50%) scale(0.9)",
            opacity: 0.85,
            offset: 0.42,
          },
          {
            transform: "translate(-50%, -50%) scale(1.35)",
            opacity: 0,
          },
        ],
        {
          duration: bloomMs * 1.5,
          delay: rayMs * 0.7,
          easing: enter,
          fill: "both",
        },
      ),
      card.animate(
        [
          {
            opacity: 0,
            transform: `scale(${tokens.scale.hero}) translateY(${tokens.shift.sm}px)`,
          },
          {
            opacity: 1,
            transform: "scale(1.015) translateY(0)",
            offset: 0.72,
          },
          { opacity: 1, transform: "scale(1) translateY(0)" },
        ],
        {
          duration: cardMs,
          delay: rayMs + bloomMs * 0.55,
          easing: enter,
          fill: "both",
        },
      ),
    ];
    bloom.style.left = `${targetX}px`;
    bloom.style.top = `${targetY}px`;
    bloom.style.width = `${Math.max(rect.width, rect.height) * 2.2}px`;
    bloom.style.height = `${Math.max(rect.width, rect.height) * 2.2}px`;
    animsRef.current = animations;

    const last = animations[animations.length - 1];
    const onFinish = () => {
      if (finishedRef.current) return;
      finishedRef.current = true;
      layer.style.display = "none";
      card.style.opacity = "1";
      card.style.transform = "none";
    };
    last.addEventListener("finish", onFinish);

    return () => {
      last.removeEventListener("finish", onFinish);
      stopAnimations();
    };
  }, [open, origin, settle, stopAnimations, tokens]);

  // Esc 打断：立即落到稳定状态并通知外层。
  useEffect(() => {
    if (!open || !onCancel) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      settle();
      onCancel();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onCancel, settle]);

  const overlay =
    typeof document === "undefined"
      ? null
      : createPortal(
          <div className={styles.layer} ref={layerRef} aria-hidden>
            <div className={styles.ray} ref={rayRef} />
            <div className={styles.head} ref={headRef} />
            <div className={styles.bloom} ref={bloomRef} />
          </div>,
          document.body,
        );

  return (
    <>
      <div
        ref={cardRef}
        className={cx(styles.card, className)}
        style={style}
      >
        {children}
      </div>
      {overlay}
    </>
  );
}
