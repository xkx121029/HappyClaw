/**
 * `antd`'s `message` API, backed by the app's own toast queue.
 *
 * The ported chat logic raises a handful of user-facing notices from plain
 * modules (a send that needs an agent, a failed session create). Those call
 * sites already speak `message.success(text)` / `message.error(text)`, so this
 * keeps that shape and routes it to `@/lib/toast` instead of pulling antd into
 * the logic layer.
 */
import { toast } from "@/lib/toast";

type NoticeText = string | { content?: unknown };

function text(value: NoticeText): string {
  if (typeof value === "string") return value;
  return typeof value.content === "string" ? value.content : String(value.content ?? "");
}

export const message = {
  success: (value: NoticeText) => toast.success(text(value)),
  error: (value: NoticeText) => toast.error(text(value)),
  warning: (value: NoticeText) => toast.info(text(value)),
  info: (value: NoticeText) => toast.info(text(value)),
  /** antd returns a closer for a "stays until closed" notice; mirror that. */
  loading: (value: NoticeText) => {
    toast.info(text(value));
    return () => {};
  },
};
