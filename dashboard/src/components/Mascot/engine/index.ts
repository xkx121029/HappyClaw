import "./geometry-data.js";
import "./math.js";
import "./tables.js";
import "./pose.js";
import "./tricks.js";
import "./fx.js";
import "./eyes.js";
import "./character.js";

export const MASCOT_SHAPES = [
  "pebble",
  "bean",
  "egg",
  "squircle",
  "tablet",
  "capsule",
  "cylinder",
  "hex",
  "gem",
  "crystal",
  "wedge",
  "shield",
  "dome",
  "arch",
  "cloud",
  "teardrop",
  "leaf",
] as const;

export const MASCOT_INKS = [
  "black",
  "brown",
  "red",
  "orange",
  "yellow",
  "green",
  "cyan",
  "blue",
  "violet",
  "magenta",
  "gray",
] as const;

export const MASCOT_STATES = [
  "sleeping",
  "waking",
  "idle",
  "listening",
  "thinking",
  "searching",
  "working",
  "excited",
  "surprised",
  "suspicious",
  "angry",
  "drowsy",
  "happy",
  "curious",
  "confused",
  "bored",
  "proud",
  "shy",
  "sad",
  "laughing",
  "scared",
  "playful",
  "celebrate",
  "orbit",
  "radar",
  "progress",
  "spawning",
  "humming",
  "loading",
  "dictating",
  "writing",
  "sending",
  "receiving",
  "uploading",
  "notifying",
  "alerting",
  "dragging",
  "bouncing",
  "powering-down",
] as const;

export type MascotShape = (typeof MASCOT_SHAPES)[number];
export type MascotInk = (typeof MASCOT_INKS)[number];
export type MascotState = (typeof MASCOT_STATES)[number];

export interface MascotCharacter {
  svg: SVGSVGElement;
  setShape(name: string): void;
  setColor(id: string, scheme?: "light" | "dark"): void;
  /** Paint the body with any CSS colour (hex, token); ``null`` restores ``setColor``. */
  setInk(flat: string | null): void;
  setState(name: string, opts?: { resetEyes?: boolean }): void;
  setEyeColor(color: string | null): void;
  setFollowPointer(value: boolean): void;
  setEmphasis(value: boolean): void;
  setPaused(value: boolean): void;
  destroy(): void;
}

export interface MascotCharacterOptions {
  shape?: string;
  color?: string;
  scheme?: "light" | "dark";
  mode?: string;
  state?: string;
  sizePx?: number | null;
  loginWrap?: boolean;
  followPointer?: boolean;
  emphasis?: boolean;
  paused?: boolean;
  reduceMotion?: boolean;
  eyeColor?: string | null;
  onChange?: (snapshot: unknown) => void;
}

/**
 * Character renderer from the mascot engine. It draws into the given <svg>
 * and animates with rAF; call ``destroy()`` on unmount.
 */
export const GrokCharacter = (
  window as unknown as {
    GrokCharacter: new (
      svg: SVGSVGElement,
      options: MascotCharacterOptions,
    ) => MascotCharacter;
  }
).GrokCharacter;
