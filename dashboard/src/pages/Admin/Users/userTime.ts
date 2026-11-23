/**
 * Time helpers for the Admin → Users screen: the ticking clock behind the
 * login-lock countdown, the remaining lock time for a row, and the formatted
 * timestamps shown in the card and table views.
 */

import { useEffect, useState } from "react";

import { formatServerDateTime } from "../../../utils/formatMessageTime";
import type { UserRow } from "./usersListTypes";

export function useNowSeconds(active: boolean): number {
  const [now, setNow] = useState(() => Math.floor(Date.now() / 1000));
  useEffect(() => {
    if (!active) return;
    const id = window.setInterval(
      () => setNow(Math.floor(Date.now() / 1000)),
      1000,
    );
    return () => window.clearInterval(id);
  }, [active]);
  return now;
}

export function lockRemainingSeconds(row: UserRow, nowSec: number): number {
  if (!row.login_locked || !row.login_locked_until) return 0;
  return Math.max(0, row.login_locked_until - nowSec);
}

export function formatUserTs(ts: number | undefined, timeZone: string): string {
  if (!ts) return "—";
  return formatServerDateTime(ts, timeZone);
}
