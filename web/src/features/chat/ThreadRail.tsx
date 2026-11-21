import { MessageSquarePlus, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { SkeletonList } from "@/components/ui/skeleton";
import { formatRelativeTime } from "@/lib/format";
import { cn } from "@/lib/cn";

import type { Thread } from "./types";

export function ThreadRail({
  threads,
  loading,
  selectedId,
  onSelect,
  onCreate,
  creating,
  timezone,
}: {
  threads: Thread[];
  loading: boolean;
  selectedId: string | undefined;
  onSelect: (threadId: string) => void;
  onCreate: () => void;
  creating: boolean;
  timezone: string | undefined;
}) {
  const { t } = useTranslation("chat");
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return threads;
    return threads.filter((thread) =>
      (thread.title ?? "").toLowerCase().includes(needle),
    );
  }, [threads, query]);

  return (
    <div className="flex h-full min-h-0 w-full flex-col border-r border-line-subtle bg-surface">
      <div className="grid gap-2 border-b border-line-subtle p-2.5">
        <div className="flex items-center justify-between">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-fg-subtle">
            {t("threads.label")}
          </h2>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={t("threads.new")}
            onClick={onCreate}
            loading={creating}
          >
            {creating ? null : <MessageSquarePlus />}
          </Button>
        </div>
        <Input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          leadingIcon={<Search />}
          placeholder={t("threads.searchPlaceholder")}
          className="[&_input]:h-8"
        />
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-1.5">
        {loading ? (
          <SkeletonList rows={5} />
        ) : filtered.length === 0 ? (
          <EmptyState
            size="sm"
            title={t("threads.empty")}
            description={t("threads.emptyDescription")}
          />
        ) : (
          <ul className="grid gap-0.5">
            {filtered.map((thread) => {
              const active = thread.thread_id === selectedId;
              return (
                <li key={thread.thread_id}>
                  <button
                    type="button"
                    onClick={() => onSelect(thread.thread_id)}
                    aria-current={active ? "true" : undefined}
                    className={cn(
                      "flex w-full flex-col gap-0.5 rounded-md px-2.5 py-2 text-left transition-colors",
                      active
                        ? "bg-selected"
                        : "hover:bg-hover focus-visible:bg-hover",
                    )}
                  >
                    <span className="flex items-center gap-2">
                      <span
                        className={cn(
                          "min-w-0 flex-1 truncate text-sm",
                          active ? "text-fg" : "text-fg-muted",
                        )}
                      >
                        {thread.title || t("threads.untitled")}
                      </span>
                      {thread.unread_count ? (
                        <Badge tone="accent">{thread.unread_count}</Badge>
                      ) : null}
                    </span>
                    <span className="flex items-center gap-2 text-2xs text-fg-subtle">
                      <span>{formatRelativeTime(thread.last_active, timezone)}</span>
                      {thread.model_ref ? (
                        <>
                          <span aria-hidden>·</span>
                          <span className="truncate font-mono">
                            {thread.model_ref}
                          </span>
                        </>
                      ) : null}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
