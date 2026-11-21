import { Sparkles } from "lucide-react";
import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

import { Avatar } from "@/components/ui/avatar";
import { EmptyState } from "@/components/ui/empty-state";
import { LoadingBlock } from "@/components/ui/spinner";
import { formatTime } from "@/lib/format";
import { cn } from "@/lib/cn";

import { messageText } from "./message-text";
import type { HistoryMessage } from "./types";

export function MessageList({
  messages,
  loading,
  agentName,
  timezone,
}: {
  messages: HistoryMessage[];
  loading: boolean;
  agentName: string;
  timezone: string | undefined;
}) {
  const { t } = useTranslation("chat");
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [messages.length]);

  if (loading) {
    return <LoadingBlock label={t("messages.empty")} className="flex-1" />;
  }

  if (messages.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <EmptyState
          icon={<Sparkles />}
          title={t("messages.empty")}
          description={t("messages.emptyDescription")}
        />
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-reading flex-col gap-5 px-4 py-6 md:px-6">
      {messages.map((message, index) => {
        const mine = message.role === "user";
        const text = messageText(message.content);
        if (!text.trim()) return null;
        return (
          <article
            key={message.id ?? `${message.role}-${index}`}
            className={cn(
              "flex gap-3",
              mine && "flex-row-reverse",
            )}
          >
            <div className="pt-0.5">
              {mine ? (
                <Avatar name={t("messages.you")} size="sm" />
              ) : (
                <Avatar name={agentName} size="sm" />
              )}
            </div>
            <div className={cn("min-w-0 flex-1", mine && "flex flex-col items-end")}>
              <div className="mb-1 flex items-center gap-2 text-2xs text-fg-subtle">
                <span className="font-medium text-fg-muted">
                  {mine ? t("messages.you") : agentName}
                </span>
                <time>{formatTime(message.timestamp, timezone)}</time>
              </div>
              <div
                className={cn(
                  "w-fit max-w-full whitespace-pre-wrap break-words rounded-lg px-3.5 py-2.5 text-base leading-relaxed",
                  mine
                    ? "bg-accent-soft text-fg"
                    : "border border-line-subtle bg-surface text-fg",
                )}
              >
                {text}
              </div>
            </div>
          </article>
        );
      })}
      <div ref={endRef} />
    </div>
  );
}
