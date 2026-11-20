import { useEffect, useRef } from "react";
import {
  HOME_ARC_START,
  HOME_ARC_SWEEP,
  segmentIndexAt,
  type HomeLink,
  type HomeTick,
  type HomeTone,
  type RingSegment,
} from "./homeActivityModel";

/** Localised strings drawn inside the canvas. */
export interface ActivityCoreLabels {
  running: string;
  awaiting: string;
  idle: string;
  overflow: (count: number) => string;
  actions: Record<"think" | "text" | "done" | "error", string>;
  link: Record<"relay" | "summary" | "handoff", string>;
}

interface ActivityCoreProps {
  /** One arc per running conversation, in stable thread-id order. */
  sessions: readonly RingSegment[];
  /** Throttled real-event pulses, each tagged with its thread + operation. */
  ticks: readonly HomeTick[];
  /** Real team-room collaborator signals. */
  links: readonly HomeLink[];
  ratePerMinute: number;
  /** Most recently active thread; the ring rotates it to the emission slot. */
  frontThreadId?: string | null;
  labels: ActivityCoreLabels;
  enabled: boolean;
  /** Right click on an arc: report the model segment, not a screen trick. */
  onSegmentContextMenu: (
    segment: RingSegment,
    x: number,
    y: number,
  ) => void;
}

interface Beam {
  threadId: string;
  tone: HomeTone;
  label: string;
  born: number;
  /** 0..1 slot inside the owning arc. */
  slot: number;
}

interface Visual {
  segment: RingSegment;
  alpha: number;
  leaving: boolean;
  /** Frozen arc while fading out. */
  exitFrom: number;
  exitTo: number;
}

interface Geometry {
  cx: number;
  cy: number;
  radius: number;
  band: number;
}

/**
 * Half ring: the visible arc spans π/2 → 3π/2 and bulges left, while the
 * opening faces the viewport's right edge. Segments tile this window and wrap
 * at the two open ends, so the ring still rotates as one dial.
 */
const ARC_START = HOME_ARC_START;
const ARC_SWEEP = HOME_ARC_SWEEP;
const ARC_END = ARC_START + ARC_SWEEP;
/** The fixed emission slot, at the half ring's leftmost point. */
const FRONT_ANGLE = ARC_START + ARC_SWEEP / 2;
const ROTATE_MS = 780;
/** Outward beams: one per real operation, merged inside 150 ms. */
const BEAM_MERGE_MS = 150;
const BEAM_GAP_MS = 140;
const BEAM_LIFE_MS = 1_500;
const BEAM_LABEL_MS = 1_000;
const MAX_BEAMS = 24;
const MAX_BEAM_LABELS = 10;
const MAX_QUEUE = 24;
const LINK_LIFE_MS = 1_700;
const MAX_LINKS = 3;
const FRAME_MIN_MS = 15;
const IDLE_AFTER_MS = 6_000;

const DONE_STOPS = ["#60a5fa", "#a78bfa", "#f472b6", "#fbbf24", "#34d399"];

const TONE_WEIGHT: Record<HomeTone, number> = {
  think: 0.7,
  tool: 1.2,
  text: 0.9,
  done: 1.8,
  error: 1.5,
};

type ArcTone = HomeTone | "idle";

function cssColor(el: HTMLElement, token: string, fallback: string): string {
  const raw = getComputedStyle(el).getPropertyValue(token).trim();
  return raw || fallback;
}

function easeInOutCubic(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2;
}

function mod(value: number, base: number): number {
  return ((value % base) + base) % base;
}

/** Shortest signed delta between two angles on the half ring. */
function halfDelta(from: number, to: number): number {
  return mod(to - from + ARC_SWEEP / 2, ARC_SWEEP) - ARC_SWEEP / 2;
}

/**
 * Background activity half ring.
 *
 * One arc per **running** conversation, tiled across the visible semicircle
 * (π/2 → 3π/2, centre parked at the right edge). The newest active
 * conversation is rotated to the fixed emission slot — the leftmost point of
 * the arc — with an eased 780 ms tween that settles on the slot grid, so no
 * conversation is ever left split across the two open ends. Every outward
 * beam is one real operation (tool call / output / reasoning / turn end) and
 * carries its name at the tip. Cross-arc links are drawn only when a stamped
 * team-room frame names a speaking agent (`agent_id`) that differs from the
 * room's own agent.
 *
 * The layer never receives pointer events. Hover painting and the right-click
 * menu both hit-test the **model** layout (angle → index), so a rotating ring
 * still resolves the correct conversation. No code or assets are shared with
 * HALOFLUX; the visual language is original.
 */
export default function ActivityCore({
  sessions,
  ticks,
  links,
  ratePerMinute,
  frontThreadId = null,
  labels,
  enabled,
  onSegmentContextMenu,
}: ActivityCoreProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const kickRef = useRef<() => void>(() => {});
  const segmentsRef = useRef<readonly RingSegment[]>(sessions);
  const labelsRef = useRef(labels);
  const rateRef = useRef(ratePerMinute);
  const menuRef = useRef(onSegmentContextMenu);
  const frontRef = useRef<string | null>(frontThreadId);
  const indexRef = useRef<Map<string, number>>(new Map());
  const toneRef = useRef<Map<string, { tone: HomeTone; at: number }>>(new Map());

  const beamsRef = useRef<Beam[]>([]);
  const queueRef = useRef<Beam[]>([]);
  const lastMergeRef = useRef<Map<string, number>>(new Map());
  const lastTickIdRef = useRef(0);
  const visualsRef = useRef<Map<string, Visual>>(new Map());
  const linksRef = useRef<Array<HomeLink & { born: number }>>([]);
  const lastLinkIdRef = useRef(0);
  /** Last time a real signal arrived; drives the idle-drift threshold. */
  const liveAtRef = useRef(0);

  segmentsRef.current = sessions;
  labelsRef.current = labels;
  rateRef.current = ratePerMinute;
  menuRef.current = onSegmentContextMenu;
  frontRef.current = frontThreadId;

  useEffect(() => {
    const map = new Map<string, number>();
    sessions.forEach((segment, index) => {
      for (const threadId of segment.threadIds) map.set(threadId, index);
    });
    indexRef.current = map;

    const visuals = visualsRef.current;
    const live = new Set(sessions.map((segment) => segment.key));
    for (const segment of sessions) {
      const existing = visuals.get(segment.key);
      if (existing) {
        existing.segment = segment;
        existing.leaving = false;
      } else {
        visuals.set(segment.key, {
          segment,
          alpha: 0,
          leaving: false,
          exitFrom: 0,
          exitTo: 0,
        });
      }
    }
    for (const [key, visual] of visuals) {
      if (!live.has(key)) visual.leaving = true;
    }

    liveAtRef.current = performance.now();
    beamsRef.current = beamsRef.current.filter((beam) => map.has(beam.threadId));
    queueRef.current = queueRef.current.filter((beam) => map.has(beam.threadId));
    kickRef.current();
  }, [sessions]);

  // Real frames → queued beams. Same operation inside 150 ms merges into one.
  useEffect(() => {
    if (!enabled) return;
    const incoming = ticks.filter((tick) => tick.id > lastTickIdRef.current);
    if (incoming.length === 0) return;
    lastTickIdRef.current = incoming[incoming.length - 1].id;
    const params = labelsRef.current;
    const queue = queueRef.current;
    for (const tick of incoming) {
      toneRef.current.set(tick.threadId, { tone: tick.tone, at: Date.now() });
      const mergeKey = `${tick.threadId}:${tick.opKey}`;
      const now = performance.now();
      const last = lastMergeRef.current.get(mergeKey) ?? 0;
      if (now - last < BEAM_MERGE_MS) continue;
      lastMergeRef.current.set(mergeKey, now);
      const label =
        tick.label ||
        (tick.tone === "think"
          ? params.actions.think
          : tick.tone === "text"
            ? params.actions.text
            : tick.tone === "done"
              ? params.actions.done
              : params.actions.error);
      queue.push({
        threadId: tick.threadId,
        tone: tick.tone,
        label,
        born: now,
        slot: 0.16 + Math.random() * 0.68,
      });
    }
    if (queue.length > MAX_QUEUE) {
      queue.splice(0, queue.length - MAX_QUEUE);
    }
    liveAtRef.current = performance.now();
    kickRef.current();
  }, [ticks, enabled]);

  // Real collaborator signals → short-lived links.
  useEffect(() => {
    if (!enabled) return;
    const fresh = links.filter((link) => link.id > lastLinkIdRef.current);
    if (fresh.length === 0) return;
    lastLinkIdRef.current = links[links.length - 1].id;
    const now = performance.now();
    const current = linksRef.current;
    for (const link of fresh) current.push({ ...link, born: now });
    if (current.length > 12) current.splice(0, current.length - 12);
    liveAtRef.current = now;
    kickRef.current();
  }, [links, enabled]);

  useEffect(() => {
    if (!enabled) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const reduced = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    let width = 0;
    let height = 0;
    let raf = 0;
    let running = true;
    let lastFrame = 0;
    let lastDraw = performance.now();

    // --- rotation (model space, never an animation artefact) --------------
    let rotation = 0;
    let rotationTarget = 0;
    const tween = { active: false, delta: 0, start: 0 };

    const readColors = () => ({
      think: cssColor(canvas, "--fn-color-info", "#60a5fa"),
      tool: "#ffffff",
      text: cssColor(canvas, "--fn-color-success", "#34d399"),
      error: cssColor(canvas, "--fn-color-danger", "#f87171"),
      awaiting: cssColor(canvas, "--fn-color-warning", "#f59e0b"),
      accent: cssColor(canvas, "--fn-color-brand", "#c9435c"),
      border: cssColor(canvas, "--fn-border-primary", "#e5e7eb"),
      ink: cssColor(canvas, "--fn-text-primary", "#0f172a"),
      muted: cssColor(canvas, "--fn-text-tertiary", "#64748b"),
      surface: cssColor(canvas, "--fn-bg-elevated", "#ffffff"),
    });
    let colors = readColors();

    const geometry = (): Geometry => {
      // Half ring: the centre sits against the right edge, so the arc owns the
      // left-hand sweep and the opening stays off-screen. Leave a margin at the
      // top and bottom so both arc ends stay visible and beams have somewhere
      // to travel.
      const radius = Math.min(width * 0.36, height * 0.38);
      const band = Math.min(52, Math.max(20, Math.min(width, height) * 0.044));
      return {
        cx: width - radius * 0.06,
        cy: height * 0.5,
        radius,
        band,
      };
    };

    const toneColor = (tone: ArcTone): string => {
      switch (tone) {
        case "think":
          return colors.think;
        case "tool":
          return colors.tool;
        case "text":
          return colors.text;
        case "error":
          return colors.error;
        case "done":
          return colors.accent;
        default:
          return colors.border;
      }
    };

    const segmentTone = (segment: RingSegment): ArcTone => {
      let at = 0;
      let tone: HomeTone | null = null;
      for (const threadId of segment.threadIds) {
        const entry = toneRef.current.get(threadId);
        if (!entry || entry.at <= at) continue;
        tone = entry.tone;
        at = entry.at;
      }
      if (tone) return tone;
      return segment.turnActive ? "think" : "idle";
    };

    const drawLabel = (
      x: number,
      y: number,
      text: string,
      color: string,
      alpha: number,
      font: string,
    ) => {
      if (alpha <= 0.02 || !text) return;
      ctx.font = font;
      ctx.globalAlpha = alpha;
      ctx.textBaseline = "middle";
      // A soft dark edge keeps thin labels readable on light themes.
      ctx.lineWidth = 3;
      ctx.strokeStyle = "rgba(2, 6, 23, 0.5)";
      ctx.strokeText(text, x, y);
      ctx.fillStyle = color;
      ctx.fillText(text, x, y);
      ctx.globalAlpha = 1;
      ctx.textBaseline = "alphabetic";
    };

    const fitText = (text: string, max: number): string => {
      if (!text) return "";
      if (ctx.measureText(text).width <= max) return text;
      let cut = text;
      while (cut.length > 1 && ctx.measureText(`${cut}…`).width > max) {
        cut = cut.slice(0, -1);
      }
      return `${cut}…`;
    };

    const roundRect = (
      x: number,
      y: number,
      w: number,
      h: number,
      r: number,
    ) => {
      ctx.beginPath();
      ctx.moveTo(x + r, y);
      ctx.lineTo(x + w - r, y);
      ctx.quadraticCurveTo(x + w, y, x + w, y + r);
      ctx.lineTo(x + w, y + h - r);
      ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
      ctx.lineTo(x + r, y + h);
      ctx.quadraticCurveTo(x, y + h, x, y + h - r);
      ctx.lineTo(x, y + r);
      ctx.quadraticCurveTo(x, y, x + r, y);
      ctx.closePath();
    };

    // Current rotation = the tween's eased value.
    const currentRotation = (now: number): number => {
      if (!tween.active) return rotation;
      const t = Math.min(1, (now - tween.start) / ROTATE_MS);
      const value = rotation + tween.delta * easeInOutCubic(t);
      if (t >= 1) {
        rotation = rotationTarget;
        tween.active = false;
        return rotation;
      }
      return value;
    };

    const draw = (now: number) => {
      if (!width || !height) return;
      const dt = Math.max(0, now - lastDraw);
      lastDraw = now;
      const geo = geometry();
      const { cx, cy, radius, band } = geo;
      const segments = segmentsRef.current;
      const count = segments.length;
      const span = count > 0 ? ARC_SWEEP / count : ARC_SWEEP;
      const visuals = visualsRef.current;

      // ``view`` is the eased angle used for painting; ``rotation`` stays the
      // tween base so repeated reads cannot compound the ease.
      let view = rotation;
      if (reduced) {
        rotation = rotationTarget;
        tween.active = false;
        view = rotation;
      } else {
        view = currentRotation(now);
      }
      // Slots tile [ARC_START, ARC_END); the phase is normalised so painting
      // stays stable no matter how many turns the tween has accumulated.
      const phase = mod(view, ARC_SWEEP);

      interface Piece {
        from: number;
        to: number;
        /** Partial slots dissolve at the open end instead of popping in. */
        fadeIn: boolean;
        fadeOut: boolean;
      }

      /**
       * One slot, split at an open end when the dial carries it off-screen.
       * A slot wholly behind the open side is drawn whole at the top edge, so
       * the settled layout still shows exactly `count` arcs.
       */
      const arcPieces = (from: number, to: number): Piece[] => {
        const length = to - from;
        const start = ARC_START + mod(from - ARC_START, ARC_SWEEP);
        const end = start + length;
        if (end <= ARC_END + 1e-6) {
          return [{ from: start, to: end, fadeIn: false, fadeOut: false }];
        }
        const head = ARC_END - start;
        const tail = end - ARC_END;
        const pieces: Piece[] = [];
        const split = head > 1e-6 && tail > 1e-6;
        if (head > 1e-6) {
          pieces.push({ from: start, to: ARC_END, fadeIn: false, fadeOut: split });
        }
        if (tail > 1e-6) {
          pieces.push({
            from: ARC_START,
            to: ARC_START + tail,
            fadeIn: split,
            fadeOut: false,
          });
        }
        return pieces;
      };
      const strokePieces = (
        pieces: readonly Piece[],
        r: number,
        lineWidth: number,
        stroke: string,
        alpha: number,
      ) => {
        ctx.strokeStyle = stroke;
        ctx.lineWidth = lineWidth;
        const drawArc = (a0: number, a1: number, a: number) => {
          ctx.globalAlpha = a;
          ctx.beginPath();
          ctx.arc(cx, cy, r, a0, a1);
          ctx.stroke();
        };
        for (const piece of pieces) {
          if (!piece.fadeIn && !piece.fadeOut) {
            drawArc(piece.from, piece.to, alpha);
            continue;
          }
          // Only the last few degrees dissolve, so a wrapped slot reads as
          // sliding through the opening instead of popping in.
          const fade = Math.min(0.16, (piece.to - piece.from) / 2);
          const solidFrom = piece.fadeIn ? piece.from + fade : piece.from;
          const solidTo = piece.fadeOut ? piece.to - fade : piece.to;
          if (solidTo > solidFrom) drawArc(solidFrom, solidTo, alpha);
          const steps = 5;
          for (let s = 0; s < steps; s += 1) {
            if (piece.fadeIn) {
              drawArc(
                piece.from + (fade * s) / steps,
                piece.from + (fade * (s + 1)) / steps,
                alpha * ((s + 0.5) / steps),
              );
            }
            if (piece.fadeOut) {
              drawArc(
                piece.to - fade + (fade * s) / steps,
                piece.to - fade + (fade * (s + 1)) / steps,
                alpha * (1 - (s + 0.5) / steps),
              );
            }
          }
        }
      };

      ctx.clearRect(0, 0, width, height);

      // --- ambient halo -------------------------------------------------
      const halo = ctx.createRadialGradient(
        cx,
        cy,
        radius * 0.5,
        cx,
        cy,
        radius * 1.5,
      );
      halo.addColorStop(
        0,
        `${count > 0 ? toneColor(segmentTone(segments[0])) : colors.accent}14`,
      );
      halo.addColorStop(1, "transparent");
      ctx.fillStyle = halo;
      ctx.fillRect(0, 0, width, height);

      // --- arcs ---------------------------------------------------------
      // A visible slit between arcs: wide enough to count at 2–4 sessions,
      // clamped so 24 arcs still keep their own body.
      const gap = count > 1 ? Math.min(0.085, span * 0.2) : 0;
      const frontId = frontRef.current;

      for (let i = 0; i < count; i += 1) {
        const segment = segments[i];
        const from = ARC_START + phase + i * span + gap / 2;
        const to = ARC_START + phase + (i + 1) * span - gap / 2;
        const visual = visuals.get(segment.key);
        let alpha = 1;
        if (visual) {
          // Enter transition: a new running conversation fades in.
          visual.alpha += (1 - visual.alpha) * (1 - Math.exp(-dt / 130));
          visual.leaving = false;
          visual.exitFrom = from;
          visual.exitTo = to;
          alpha = Math.max(0.06, visual.alpha);
        }
        // Ownership cue: the arc parked at the emission slot is the brightest.
        const onFront =
          frontId !== null &&
          (segment.threadId === frontId ||
            segment.threadIds.includes(frontId));
        const tone = segmentTone(segment);
        const color = toneColor(tone);
        const pulse = 0.72 + 0.28 * Math.sin(now / 620 + i * 1.7);
        const pieces = arcPieces(from, to);

        strokePieces(
          pieces,
          radius,
          band,
          colors.border,
          alpha * (onFront ? 0.34 : 0.2),
        );
        strokePieces(pieces, radius - band / 2, 1, colors.border, alpha * 0.55);
        strokePieces(pieces, radius + band / 2, 1, colors.border, alpha * 0.55);

        // Live arc: wide glow + bright core. Pure white has no contrast on a
        // light surface, so the "tool" tone gets a soft shadow to stay legible.
        if (tone === "tool") {
          ctx.shadowColor = "rgba(15, 23, 42, 0.32)";
          ctx.shadowBlur = 12;
        }
        strokePieces(
          pieces,
          radius,
          band * 1.7,
          color,
          alpha * (onFront ? 0.32 : 0.2) * pulse,
        );
        strokePieces(
          pieces,
          radius,
          band * 0.6,
          color,
          alpha * (onFront ? 0.6 : 0.44),
        );
        ctx.shadowBlur = 0;
        ctx.shadowColor = "transparent";
        strokePieces(pieces, radius, Math.max(2, band * 0.18), color, alpha * 0.95);

        if (segment.overflow > 0) {
          for (let d = 1; d <= 3; d += 1) {
            const raw = from + ((to - from) * d) / 4;
            const angle = ARC_START + mod(raw - ARC_START, ARC_SWEEP);
            ctx.globalAlpha = 0.6;
            ctx.strokeStyle = colors.border;
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(
              cx + Math.cos(angle) * (radius - band / 2),
              cy + Math.sin(angle) * (radius - band / 2),
            );
            ctx.lineTo(
              cx + Math.cos(angle) * (radius + band / 2),
              cy + Math.sin(angle) * (radius + band / 2),
            );
            ctx.stroke();
          }
        }
      }
      ctx.globalAlpha = 1;

      // Fading arcs of conversations that just stopped.
      for (const [key, visual] of visuals) {
        if (!visual.leaving) continue;
        visual.alpha += (0 - visual.alpha) * (1 - Math.exp(-dt / 120));
        if (visual.alpha < 0.02) {
          visuals.delete(key);
          continue;
        }
        strokePieces(
          arcPieces(visual.exitFrom, visual.exitTo),
          radius,
          band * 0.32,
          toneColor(segmentTone(visual.segment)),
          visual.alpha * 0.6,
        );
        ctx.globalAlpha = 1;
      }

      if (count === 0) {
        // Empty instrument: the half ring stays on screen as a dormant gauge,
        // never a blank background.
        const idle: Piece[] = [
          { from: ARC_START, to: ARC_END, fadeIn: false, fadeOut: false },
        ];
        // ``ink`` flips with the theme (dark text on light, light on dark), so
        // the dormant gauge stays visible in both.
        strokePieces(idle, radius, band, colors.ink, 0.07);
        strokePieces(idle, radius - band / 2, 1, colors.ink, 0.3);
        strokePieces(idle, radius + band / 2, 1, colors.ink, 0.3);
        ctx.setLineDash([2, 10]);
        ctx.globalAlpha = 0.34;
        ctx.strokeStyle = colors.ink;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.arc(cx, cy, radius, ARC_START, ARC_END);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.globalAlpha = 1;
      }

      // --- fixed emission slot ------------------------------------------
      if (count > 0) {
        const slotR = radius + band * 0.9;
        ctx.strokeStyle = colors.accent;
        ctx.globalAlpha = 0.55;
        ctx.lineWidth = 1.5;
        for (const offset of [-0.055, 0.055]) {
          const angle = FRONT_ANGLE + offset;
          ctx.beginPath();
          ctx.moveTo(
            cx + Math.cos(angle) * (radius + band * 0.5),
            cy + Math.sin(angle) * (radius + band * 0.5),
          );
          ctx.lineTo(
            cx + Math.cos(angle) * slotR,
            cy + Math.sin(angle) * slotR,
          );
          ctx.stroke();
        }
        ctx.globalAlpha = 1;
      }

      // --- beams --------------------------------------------------------
      const beams = beamsRef.current;
      const labelsCopy = labelsRef.current;
      const visibleLabels: Array<{ x: number; y: number; text: string; color: string; alpha: number }> = [];

      let write = 0;
      for (let i = 0; i < beams.length; i += 1) {
        const beam = beams[i];
        const index = indexRef.current.get(beam.threadId);
        const age = now - beam.born;
        if (index === undefined || age > BEAM_LIFE_MS) continue;
        beams[write] = beam;
        write += 1;
        if (reduced || count === 0) continue;

        const angle =
          ARC_START + mod(view + index * span + span * beam.slot, ARC_SWEEP);
        const progress = age / BEAM_LIFE_MS;
        const inner = radius + band * 0.55;
        const length = radius * 0.55 * (0.45 + progress * 0.7);
        const outer = inner + length;
        const x1 = cx + Math.cos(angle) * inner;
        const y1 = cy + Math.sin(angle) * inner;
        const x2 = cx + Math.cos(angle) * outer;
        const y2 = cy + Math.sin(angle) * outer;
        const alpha = (1 - progress) ** 1.4 * 0.85;

        const gradient = ctx.createLinearGradient(x1, y1, x2, y2);
        if (beam.tone === "done") {
          DONE_STOPS.forEach((stop, stopIndex) => {
            gradient.addColorStop(
              (stopIndex / (DONE_STOPS.length - 1)) * 0.75,
              stop,
            );
          });
          gradient.addColorStop(1, "transparent");
        } else {
          gradient.addColorStop(0, toneColor(beam.tone));
          gradient.addColorStop(1, "transparent");
        }

        // Soft glow shadow for depth.
        ctx.globalAlpha = alpha * 0.28;
        ctx.strokeStyle = toneColor(beam.tone);
        ctx.lineWidth = 9 + TONE_WEIGHT[beam.tone] * 4;
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.stroke();

        if (beam.tone === "tool") {
          ctx.globalAlpha = alpha * 0.7;
          ctx.strokeStyle = "rgba(15, 23, 42, 0.35)";
          ctx.lineWidth = 4 + TONE_WEIGHT[beam.tone];
          ctx.beginPath();
          ctx.moveTo(x1, y1);
          ctx.lineTo(x2, y2);
          ctx.stroke();
        }

        ctx.globalAlpha = alpha;
        ctx.strokeStyle = gradient;
        ctx.lineWidth = 1.4 + TONE_WEIGHT[beam.tone];
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.stroke();

        // Bright head + two trailing sparks.
        ctx.globalAlpha = Math.min(1, alpha * 1.4);
        ctx.fillStyle = toneColor(beam.tone);
        ctx.beginPath();
        ctx.arc(x2, y2, 2 + TONE_WEIGHT[beam.tone], 0, Math.PI * 2);
        ctx.fill();
        for (let spark = 1; spark <= 2; spark += 1) {
          const t = Math.min(1, progress + spark * 0.06);
          const sx = cx + Math.cos(angle) * (inner + length * (1 - t));
          const sy = cy + Math.sin(angle) * (inner + length * (1 - t));
          ctx.globalAlpha = alpha * (0.5 - spark * 0.15);
          ctx.beginPath();
          ctx.arc(sx, sy, 1.4 + TONE_WEIGHT[beam.tone] * 0.4, 0, Math.PI * 2);
          ctx.fill();
        }
        ctx.globalAlpha = 1;

        if (age < BEAM_LABEL_MS) {
          visibleLabels.push({
            x: x2,
            y: y2,
            text: beam.label,
            color: toneColor(beam.tone),
            alpha: 1 - age / BEAM_LABEL_MS,
          });
        }
      }
      beams.length = write;

      // Newest labels win; the rest are dropped, never stacked.
      visibleLabels.sort((a, b) => b.alpha - a.alpha);
      for (const label of visibleLabels.slice(0, MAX_BEAM_LABELS)) {
        const maxWidth = Math.min(140, width * 0.18);
        ctx.font = `11px system-ui, -apple-system, "Segoe UI", sans-serif`;
        drawLabel(
          Math.min(width - 12, label.x + 6),
          Math.max(12, Math.min(height - 12, label.y - 8)),
          fitText(label.text, maxWidth),
          label.color,
          label.alpha,
          `11px system-ui, -apple-system, "Segoe UI", sans-serif`,
        );
      }

      // --- real collaborator links --------------------------------------
      if (!reduced && count > 0) {
        const agentIndex = new Map<string, number>();
        segments.forEach((segment, index) => {
          if (segment.agentId && !agentIndex.has(segment.agentId)) {
            agentIndex.set(segment.agentId, index);
          }
        });
        const nowMs = Date.now();
        const live = linksRef.current.filter(
          (link) => nowMs - link.at < LINK_LIFE_MS,
        );
        linksRef.current = live;
        const rendered = live.slice(-MAX_LINKS);
        for (const link of rendered) {
          const targetIndex = indexRef.current.get(link.toThreadId);
          const sourceIndex = agentIndex.get(link.fromAgentId);
          if (targetIndex === undefined || sourceIndex === undefined) continue;
          if (targetIndex === sourceIndex) continue;
          const progress = (nowMs - link.at) / LINK_LIFE_MS;
          const alpha = Math.sin(Math.min(1, progress) * Math.PI) * 0.7;
          if (alpha <= 0.02) continue;
          const a1 =
            ARC_START + mod(view + sourceIndex * span + span / 2, ARC_SWEEP);
          const a2 =
            ARC_START + mod(view + targetIndex * span + span / 2, ARC_SWEEP);
          const r = radius * 0.62;
          const p0 = {
            x: cx + Math.cos(a1) * r,
            y: cy + Math.sin(a1) * r,
          };
          const p2 = {
            x: cx + Math.cos(a2) * r,
            y: cy + Math.sin(a2) * r,
          };
          const mid = (a1 + a2) / 2;
          const control = {
            x: cx + Math.cos(mid) * r * 0.42,
            y: cy + Math.sin(mid) * r * 0.42,
          };
          ctx.globalAlpha = alpha;
          ctx.strokeStyle = colors.accent;
          ctx.lineWidth = 1.4;
          ctx.setLineDash([3, 6]);
          ctx.lineDashOffset = -now / 45;
          ctx.beginPath();
          ctx.moveTo(p0.x, p0.y);
          ctx.quadraticCurveTo(control.x, control.y, p2.x, p2.y);
          ctx.stroke();
          ctx.setLineDash([]);
          ctx.lineDashOffset = 0;

          // Travelling packet.
          const t = mod(now / 900, 1);
          const ix = (1 - t) ** 2 * p0.x + 2 * (1 - t) * t * control.x + t * t * p2.x;
          const iy = (1 - t) ** 2 * p0.y + 2 * (1 - t) * t * control.y + t * t * p2.y;
          ctx.globalAlpha = alpha * 0.95;
          ctx.fillStyle = colors.accent;
          ctx.beginPath();
          ctx.arc(ix, iy, 2.4, 0, Math.PI * 2);
          ctx.fill();
          ctx.globalAlpha = 1;

          drawLabel(
            (p0.x + control.x + p2.x) / 3,
            (p0.y + control.y + p2.y) / 3,
            labelsCopy.link[link.kind],
            colors.accent,
            alpha,
            `11px system-ui, -apple-system, "Segoe UI", sans-serif`,
          );
        }
      }

      // --- hover card (attribution) --------------------------------------
      if (hoverIndex >= 0 && hoverIndex < count) {
        const segment = segments[hoverIndex];
        const mid =
          ARC_START + mod(view + hoverIndex * span + span / 2, ARC_SWEEP);
        const anchorX = cx + Math.cos(mid) * (radius - band / 2 - 16);
        const anchorY = cy + Math.sin(mid) * (radius - band / 2 - 16);
        const copy = labelsRef.current;
        const title =
          segment.overflow > 0 ? copy.overflow(segment.overflow) : segment.title;
        const status = segment.awaitingUser
          ? copy.awaiting
          : segment.turnActive
            ? copy.running
            : copy.idle;
        const meta =
          segment.overflow > 0 ? status : `${segment.agentName} · ${status}`;

        ctx.font = `600 12px system-ui, -apple-system, "Segoe UI", sans-serif`;
        const maxText = Math.min(220, width - 44);
        const titleText = fitText(title, maxText);
        const titleWidth = ctx.measureText(titleText).width;
        ctx.font = `11px system-ui, -apple-system, "Segoe UI", sans-serif`;
        const metaText = fitText(meta, maxText);
        const metaWidth = ctx.measureText(metaText).width;

        const padX = 10;
        const boxW = Math.max(titleWidth, metaWidth) + padX * 2 + 14;
        const boxH = 44;
        const x = Math.max(12, Math.min(width - boxW - 12, anchorX + 10));
        const y = Math.max(12, Math.min(height - boxH - 12, anchorY - boxH / 2));

        ctx.globalAlpha = 0.96;
        ctx.fillStyle = colors.surface;
        roundRect(x, y, boxW, boxH, 8);
        ctx.fill();
        ctx.globalAlpha = 1;
        ctx.strokeStyle = colors.border;
        ctx.lineWidth = 1;
        roundRect(x, y, boxW, boxH, 8);
        ctx.stroke();

        ctx.fillStyle = toneColor(segmentTone(segment));
        ctx.beginPath();
        ctx.arc(x + padX + 3, y + 14, 3, 0, Math.PI * 2);
        ctx.fill();

        ctx.textBaseline = "middle";
        ctx.font = `600 12px system-ui, -apple-system, "Segoe UI", sans-serif`;
        ctx.fillStyle = colors.ink;
        ctx.fillText(titleText, x + padX + 12, y + 14);
        ctx.font = `11px system-ui, -apple-system, "Segoe UI", sans-serif`;
        ctx.fillStyle = colors.muted;
        ctx.fillText(metaText, x + padX + 12, y + 31);
        ctx.textBaseline = "alphabetic";
      }

      ctx.globalAlpha = 1;
    };

    // --- model-space hit test (no animation intermediates) ---------------
    let hoverIndex = -1;

    const hitTest = (x: number, y: number): number => {
      const segments = segmentsRef.current;
      if (segments.length === 0) return -1;
      const { cx, cy, radius, band } = geometry();
      const dx = x - cx;
      const dy = y - cy;
      if (Math.abs(Math.hypot(dx, dy) - radius) > band / 2 + 16) return -1;
      const angle = Math.atan2(dy, dx);
      // The open side is empty: only the visible semicircle is interactive.
      if (Math.abs(angle) < ARC_SWEEP / 2) return -1;
      // Segment identity comes from the angle model, never from a per-arc
      // animated position: one global rotation maps any pointer to an index.
      return segmentIndexAt(
        angle,
        currentRotation(performance.now()),
        segments.length,
        ARC_START,
        ARC_SWEEP,
      );
    };

    /** True while anything moves: live arcs, beams, links. */
    const active = (now: number): boolean => {
      if (beamsRef.current.length > 0 || queueRef.current.length > 0) {
        return true;
      }
      if (linksRef.current.some((link) => Date.now() - link.at < LINK_LIFE_MS)) {
        return true;
      }
      if (tween.active) return true;
      if (segmentsRef.current.length > 0) {
        return now - liveAtRef.current < IDLE_AFTER_MS;
      }
      return false;
    };

    let lastEmitAt = 0;
    const emitQueued = (now: number) => {
      const queue = queueRef.current;
      if (queue.length === 0) return;
      if (now - lastEmitAt < BEAM_GAP_MS) return;
      lastEmitAt = now;
      const beam = queue.shift();
      if (!beam) return;
      // Old operations are stale; keep labels meaningful.
      if (now - beam.born > 1_200) return;
      const beams = beamsRef.current;
      beams.push(beam);
      if (beams.length > MAX_BEAMS) beams.splice(0, beams.length - MAX_BEAMS);
      liveAtRef.current = now;
    };

    const frame = (now: number) => {
      raf = 0;
      if (!running) return;
      const hasSegments = segmentsRef.current.length > 0;
      const busy = active(now);
      const step = busy ? FRAME_MIN_MS : 66;
      if (width && lastFrame && now - lastFrame < step) {
        raf = window.requestAnimationFrame(frame);
        return;
      }
      lastFrame = now;
      if (reduced) {
        draw(now);
        return;
      }
      if (!busy && hasSegments) {
        // A half window cannot spin without splitting a slot at the open ends,
        // so idle keeps the dial still and only the glow breathes.
        rotationTarget = rotation;
      }
      emitQueued(now);
      draw(now);
      if (busy || hasSegments) {
        raf = window.requestAnimationFrame(frame);
      }
    };

    const kick = () => {
      if (!running) return;
      if (reduced) {
        draw(performance.now());
        return;
      }
      if (!raf) {
        lastFrame = 0;
        raf = window.requestAnimationFrame(frame);
      }
    };
    kickRef.current = kick;

    let aimKey = "";
    const aimFront = () => {
      const segments = segmentsRef.current;
      const threadId = frontRef.current;
      if (!threadId || segments.length === 0) {
        aimKey = "";
        return;
      }
      const index = segments.findIndex(
        (segment) =>
          segment.threadId === threadId ||
          segment.threadIds.includes(threadId),
      );
      if (index < 0) return;
      const span = ARC_SWEEP / segments.length;
      // Settle on the slot grid: an arbitrary phase would leave one
      // conversation split across both open ends. Odd counts centre a slot on
      // the emission point, even counts start a slot there.
      const desired =
        FRONT_ANGLE - (segments.length % 2 === 0 ? 0 : span / 2);
      const target = mod(desired - ARC_START - index * span, ARC_SWEEP);
      // Re-aim on a new front conversation or ring change. While idle the ring
      // is allowed to drift; the next real signal pulls it back.
      const key = `${threadId}|${segments.map((segment) => segment.key).join(",")}`;
      const busy = performance.now() - liveAtRef.current < IDLE_AFTER_MS;
      if (key === aimKey) {
        if (!busy) return;
        if (Math.abs(halfDelta(rotationTarget, target)) < 1e-3) return;
      }
      aimKey = key;
      rotation = mod(currentRotation(performance.now()), ARC_SWEEP);
      tween.active = true;
      tween.delta = halfDelta(rotation, target);
      tween.start = performance.now();
      rotationTarget = target;
      kickRef.current();
    };

    // Re-aim whenever the newest active thread (or the arc set) changes.
    const aimObserver = window.setInterval(aimFront, 400);

    const onMove = (event: MouseEvent) => {
      const next = hitTest(event.clientX, event.clientY);
      if (next === hoverIndex) return;
      hoverIndex = next;
      kick();
    };

    const onMouseLeave = () => {
      if (hoverIndex === -1) return;
      hoverIndex = -1;
      kick();
    };

    const onContextMenu = (event: MouseEvent) => {
      if (
        event.target instanceof Element &&
        event.target.closest("[data-home-menu]")
      ) {
        return;
      }
      const index = hitTest(event.clientX, event.clientY);
      const segments = segmentsRef.current;
      if (index < 0 || index >= segments.length) return;
      event.preventDefault();
      menuRef.current(segments[index], event.clientX, event.clientY);
    };

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      width = window.innerWidth;
      height = window.innerHeight;
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      aimFront();
      kick();
    };

    const onVisibility = () => {
      if (document.hidden) {
        running = false;
        if (raf) window.cancelAnimationFrame(raf);
        raf = 0;
      } else {
        running = true;
        kick();
      }
    };

    const observer = new ResizeObserver(resize);
    observer.observe(document.documentElement);
    const themeObserver = new MutationObserver(() => {
      colors = readColors();
      kick();
    });
    themeObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme", "data-palette"],
    });

    window.addEventListener("resize", resize);
    window.addEventListener("mousemove", onMove, { passive: true });
    window.addEventListener("contextmenu", onContextMenu);
    document.addEventListener("mouseleave", onMouseLeave);
    document.addEventListener("visibilitychange", onVisibility);
    resize();

    return () => {
      running = false;
      window.clearInterval(aimObserver);
      observer.disconnect();
      themeObserver.disconnect();
      if (raf) window.cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("contextmenu", onContextMenu);
      document.removeEventListener("mouseleave", onMouseLeave);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [enabled]);

  if (!enabled) return null;

  return (
    <div className="home-core-layer" aria-hidden="true">
      <canvas ref={canvasRef} className="home-core-canvas" />
    </div>
  );
}
