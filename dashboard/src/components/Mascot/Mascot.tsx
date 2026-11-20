import cx from "classnames";
import { useEffect, useRef, useState } from "react";

import styles from "./Mascot.module.less";
import { useMascotAppearance } from "./appearance";
import { readRootHex, readableOn, resolveColorHex } from "./color";
import {
  GrokCharacter,
  type MascotCharacter,
  type MascotInk,
  type MascotShape,
  type MascotState,
} from "./engine";

export interface MascotProps {
  /** Square edge in px. The SVG fills it and keeps its aspect ratio. */
  size?: number;
  /** Body silhouette from the engine (defaults to the user's saved Bao look). */
  shape?: MascotShape;
  /** Ink palette from the engine (defaults to the user's saved Bao look). */
  color?: MascotInk;
  /**
   * Arbitrary body colour (hex). Wins over ``color``; auto-lightened on dark
   * surfaces and auto-darkened on light ones so it never disappears. Defaults
   * to the user's saved Bao look.
   */
  bodyColor?: string | null;
  /** Arbitrary eye colour (hex). Defaults to the user's saved Bao look. */
  eyeColor?: string | null;
  /** Paint the body with the live ``--fn-color-brand`` token. */
  followTheme?: boolean;
  /** Animation state (default ``idle``). */
  state?: MascotState;
  /** Eyes follow the pointer. Off by default so small marks stay calm. */
  followPointer?: boolean;
  /**
   * Colour behind the eye cut-outs. Defaults to the base surface token so the
   * eyes disappear into the page in both themes.
   */
  surface?: string;
  /** Freeze the animation without unmounting (also auto when off-screen). */
  paused?: boolean;
  /** Accessible label. Omit for decorative usage. */
  label?: string;
  className?: string;
}

/**
 * The product reads the theme from ``html[data-theme]``. We observe that
 * attribute instead of a React context so the mascot also works in layers
 * that render outside the theme provider (boot, crash fallback, tests).
 */
function useDocumentTheme() {
  const read = () =>
    typeof document !== "undefined" &&
    document.documentElement.dataset.theme === "dark";
  const [dark, setDark] = useState(read);
  const [palette, setPalette] = useState(
    () =>
      (typeof document !== "undefined" &&
        document.documentElement.dataset.palette) ||
      "",
  );

  useEffect(() => {
    const el = document.documentElement;
    const sync = () => {
      setDark(el.dataset.theme === "dark");
      setPalette(el.dataset.palette || "");
    };
    const observer = new MutationObserver(sync);
    observer.observe(el, {
      attributes: true,
      attributeFilter: ["data-theme", "data-palette"],
    });
    sync();
    return () => observer.disconnect();
  }, []);

  // ``palette`` is read only to re-run colour resolution when the accent moves.
  return { dark, palette };
}

/**
 * Live mascot rendered by the bundled character engine.
 *
 * The engine paints into a plain inline ``<svg>``: no iframe, no external
 * requests. ``--fg`` is driven by the ``color-scheme`` we set from the app
 * theme, and the eye cut-outs inherit a ``--fn-*`` surface token, so neither
 * the engine's own background nor its light/dark defaults can override the
 * product theme.
 */
export function Mascot({
  size = 32,
  shape: shapeProp,
  color: colorProp,
  bodyColor: bodyColorProp,
  eyeColor: eyeColorProp,
  followTheme: followThemeProp,
  state = "idle",
  followPointer = false,
  surface = "var(--fn-bg-base)",
  paused = false,
  label,
  className,
}: MascotProps) {
  // Every placement shares one appearance record: the user's saved look. A
  // caller may still pass explicit props (personalisation preview, status ink).
  const appearance = useMascotAppearance();
  const shape = shapeProp ?? appearance.shape;
  const color = colorProp ?? appearance.color;
  const bodyColor =
    bodyColorProp !== undefined ? bodyColorProp : appearance.bodyColor;
  const eyeColor =
    eyeColorProp !== undefined ? eyeColorProp : appearance.eyeColor;
  const followTheme = followThemeProp ?? appearance.followTheme;
  const { dark: isDark, palette } = useDocumentTheme();
  const hostRef = useRef<HTMLSpanElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const botRef = useRef<MascotCharacter | null>(null);

  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    const scheme = isDark ? "dark" : "light";
    el.style.colorScheme = scheme;
    const bot = new GrokCharacter(el, {
      shape,
      color,
      state,
      scheme,
      mode: "hold",
      loginWrap: true,
      followPointer,
      eyeColor: surface,
    });
    botRef.current = bot;
    return () => {
      bot.destroy();
      botRef.current = null;
    };
    // Initial props only; later changes are synced by the effects below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    botRef.current?.setShape(shape);
  }, [shape]);

  useEffect(() => {
    const bot = botRef.current;
    if (!bot) return;
    const scheme = isDark ? "dark" : "light";
    bot.svg.style.colorScheme = scheme;
    bot.setColor(color, scheme);

    // ``setColor`` just reset --fg/--bg, so the user's picks are applied after.
    const surfaceHex = readRootHex(
      "--fn-bg-base",
      isDark ? "#0f1117" : "#ffffff",
    );
    const brandHex = readRootHex(
      "--fn-color-brand",
      isDark ? "#f08b9a" : "#c9435c",
    );
    if (followTheme) {
      bot.setInk("var(--fn-color-brand)");
    } else if (bodyColor) {
      bot.setInk(readableOn(bodyColor, surfaceHex));
    }
    if (eyeColor) {
      // Eyes sit on the body, so contrast must be measured against what the
      // body actually renders as — the engine ink when nothing is customised.
      const bodyHex = followTheme
        ? brandHex
        : bodyColor
          ? readableOn(bodyColor, surfaceHex)
          : resolveColorHex(
              getComputedStyle(bot.svg).getPropertyValue("--fg"),
              isDark,
            ) ?? (isDark ? "#c2c2c2" : "#000000");
      bot.setEyeColor(readableOn(eyeColor, bodyHex));
    } else {
      bot.setEyeColor(surface);
    }
  }, [color, isDark, palette, bodyColor, eyeColor, followTheme, surface]);

  useEffect(() => {
    botRef.current?.setState(state, { resetEyes: true });
  }, [state]);

  useEffect(() => {
    botRef.current?.setFollowPointer(followPointer);
  }, [followPointer]);

  // Stop animating when the mascot is off-screen or the tab is hidden.
  useEffect(() => {
    const host = hostRef.current;
    const bot = botRef.current;
    if (!host || !bot) return;
    let onScreen = true;
    const sync = () => {
      bot.setPaused(paused || !onScreen || document.hidden);
    };
    const observer = new IntersectionObserver(
      (entries) => {
        onScreen = entries.some((entry) => entry.isIntersecting);
        sync();
      },
      { threshold: 0 },
    );
    observer.observe(host);
    document.addEventListener("visibilitychange", sync);
    bot.setPaused(paused || document.hidden);
    return () => {
      observer.disconnect();
      document.removeEventListener("visibilitychange", sync);
    };
  }, [paused]);

  return (
    <span
      ref={hostRef}
      className={cx(styles.host, className)}
      style={{ width: size, height: size }}
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    >
      <svg ref={svgRef} className={styles.svg} focusable="false" />
    </span>
  );
}

export default Mascot;
