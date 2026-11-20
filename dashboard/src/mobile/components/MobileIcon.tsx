import type { SVGProps } from "react";

export type MobileIconName =
  | "home"
  | "chat"
  | "bao"
  | "experts"
  | "more"
  | "zap"
  | "back"
  | "chevron"
  | "plus"
  | "search"
  | "refresh"
  | "send"
  | "stop"
  | "close"
  | "spark"
  | "check"
  | "play"
  | "list"
  | "gear"
  | "shield"
  | "plug"
  | "book"
  | "chart"
  | "trash"
  | "edit"
  | "clock"
  | "user"
  | "bot"
  | "alert";

interface MobileIconProps extends Omit<SVGProps<SVGSVGElement>, "name"> {
  name: MobileIconName;
  size?: number;
}

const PATHS: Record<MobileIconName, JSX.Element> = {
  home: (
    <path d="M3.6 10.8 12 3.8l8.4 7v9.4a1 1 0 0 1-1 1h-4.6v-6.3H9.2v6.3H4.6a1 1 0 0 1-1-1z" />
  ),
  chat: (
    <path d="M20.5 11.6c0 4.1-3.8 7.4-8.5 7.4-1 0-2-.1-2.9-.4L4.4 20.4l1.2-3.4A7 7 0 0 1 3.5 11.6C3.5 7.5 7.3 4.2 12 4.2s8.5 3.3 8.5 7.4z" />
  ),
  bao: (
    <>
      <path d="M12 3.4c4.7 0 8.3 3.3 8.3 7.6 0 2.9-1.3 5-3.3 6.2 0 1.2.4 2.2 1.2 3.1-1.8.3-3.3-.2-4.5-1.1-1.5.3-3.2.3-4.7-.1C6.3 17.6 3.7 14.9 3.7 11c0-4.3 3.6-7.6 8.3-7.6z" />
      <circle cx="9.4" cy="11" r="1.25" fill="currentColor" stroke="none" />
      <circle cx="14.6" cy="11" r="1.25" fill="currentColor" stroke="none" />
    </>
  ),
  experts: (
    <>
      <circle cx="9" cy="8" r="3.2" />
      <path d="M3.6 19.4c0-2.9 2.4-4.9 5.4-4.9s5.4 2 5.4 4.9" />
      <path d="M16 5.4a3 3 0 0 1 0 5.6M17.2 14.9c2 .5 3.4 2.2 3.4 4.5" />
    </>
  ),
  more: (
    <>
      <circle cx="12" cy="8" r="3.4" />
      <path d="M5 20c0-3.3 3.1-5.6 7-5.6s7 2.3 7 5.6" />
    </>
  ),
  zap: <path d="M13.2 2.8 5.4 13.4h5.2l-1 7.8 7.9-10.7h-5.2z" />,
  back: <path d="M14.8 5.2 8 12l6.8 6.8" />,
  chevron: <path d="m9.4 5.6 6.4 6.4-6.4 6.4" />,
  plus: <path d="M12 5v14M5 12h14" />,
  search: (
    <>
      <circle cx="11" cy="11" r="6.4" />
      <path d="m16 16 4.2 4.2" />
    </>
  ),
  refresh: (
    <>
      <path d="M20 11.2A8 8 0 1 0 18.4 17" />
      <path d="M20 4.8v6h-6" />
    </>
  ),
  send: <path d="M12 19.4V5.2M6.2 11 12 5.2l5.8 5.8" />,
  stop: (
    <rect
      x="7.4"
      y="7.4"
      width="9.2"
      height="9.2"
      rx="2"
      fill="currentColor"
      stroke="none"
    />
  ),
  close: <path d="M6 6l12 12M18 6 6 18" />,
  spark: (
    <path d="M12 3.6l1.9 5.1 5.1 1.9-5.1 1.9-1.9 5.1-1.9-5.1L5 10.6l5.1-1.9z" />
  ),
  check: <path d="m5.4 12.6 4.2 4.2 9-9" />,
  play: <path d="M8 5.4v13.2L19 12z" />,
  list: (
    <path d="M8 6.4h11M8 12h11M8 17.6h11M4.4 6.4h.1M4.4 12h.1M4.4 17.6h.1" />
  ),
  gear: (
    <>
      <circle cx="12" cy="12" r="3.1" />
      <path d="M19.4 14.3a7.6 7.6 0 0 0 0-4.6l1.8-1.3-1.9-3.3-2.1.8a7.7 7.7 0 0 0-4-2.3L12.8 1.5h-3.6l-.4 2.1a7.7 7.7 0 0 0-4 2.3l-2.1-.8L.8 8.4l1.8 1.3a7.6 7.6 0 0 0 0 4.6l-1.8 1.3 1.9 3.3 2.1-.8a7.7 7.7 0 0 0 4 2.3l.4 2.1h3.6l.4-2.1a7.7 7.7 0 0 0 4-2.3l2.1.8 1.9-3.3z" />
    </>
  ),
  shield: (
    <path d="M12 3.2 4.8 6v5.5c0 4.5 3 7.7 7.2 9.3 4.2-1.6 7.2-4.8 7.2-9.3V6z" />
  ),
  plug: (
    <>
      <path d="M9 3.5v5M15 3.5v5" />
      <path d="M6.5 8.5h11v3.2a5.5 5.5 0 0 1-11 0z" />
      <path d="M12 17.2v3.3" />
    </>
  ),
  book: (
    <>
      <path d="M4.5 5.2c2.7-1 5.2-.6 7.5 1v13c-2.3-1.6-4.8-2-7.5-1z" />
      <path d="M19.5 5.2c-2.7-1-5.2-.6-7.5 1v13c2.3-1.6 4.8-2 7.5-1z" />
    </>
  ),
  chart: <path d="M4.5 19.5V12M9.8 19.5V6.5M15.1 19.5v-5.2M20.4 19.5V9" />,
  trash: (
    <>
      <path d="M4.8 6.6h14.4M9.4 6.6V4.4h5.2v2.2" />
      <path d="M6.6 6.6 7.6 20h8.8l1-13.4" />
    </>
  ),
  edit: <path d="M4.5 19.5h4l10-10a2.1 2.1 0 0 0-3-3l-10 10z" />,
  clock: (
    <>
      <circle cx="12" cy="12" r="8" />
      <path d="M12 7.6V12l3.2 2" />
    </>
  ),
  user: (
    <>
      <circle cx="12" cy="8.2" r="3.6" />
      <path d="M4.8 20c0-3.4 3.2-5.8 7.2-5.8s7.2 2.4 7.2 5.8" />
    </>
  ),
  bot: (
    <>
      <rect x="4.2" y="7.4" width="15.6" height="12" rx="4" />
      <circle cx="9.4" cy="12.6" r="1.2" fill="currentColor" stroke="none" />
      <circle cx="14.6" cy="12.6" r="1.2" fill="currentColor" stroke="none" />
      <path d="M12 3.4v4" />
    </>
  ),
  alert: (
    <>
      <circle cx="12" cy="12" r="8.2" />
      <path d="M12 7.8v5M12 16.2h.01" />
    </>
  ),
};

export function MobileIcon({ name, size = 22, ...rest }: MobileIconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...rest}
    >
      {PATHS[name]}
    </svg>
  );
}
