import { useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Topbar } from "@/components/layout/topbar";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Select } from "@/components/ui/select";
import { LoadingBlock } from "@/components/ui/spinner";
import { getTimezone } from "@/features/settings/api";
import { useQuery } from "@tanstack/react-query";

import { Composer } from "./Composer";
import { MessageList } from "./MessageList";
import { ThreadRail } from "./ThreadRail";
import { chatKeys, useAgents, useCreateThread, useHistory, useThreads } from "./queries";
import { useChatSocket } from "./useChatSocket";

export function ChatPage() {
  const { t } = useTranslation("chat");
  const { t: tCommon } = useTranslation();
  const queryClient = useQueryClient();

  const agentsQuery = useAgents();
  const agents = useMemo(() => agentsQuery.data?.data ?? [], [agentsQuery.data]);

  // Selection is derived, never synced through an effect: the first agent and
  // the first thread are simply the fallback whenever nothing is picked yet (or
  // the picked id disappeared after a refetch).
  const [pickedAgentId, setPickedAgentId] = useState<string | undefined>();
  const activeAgentId = pickedAgentId ?? agents[0]?.agent_id;

  const threadsQuery = useThreads(activeAgentId);
  const threads = useMemo(() => threadsQuery.data?.data ?? [], [threadsQuery.data]);

  const [pickedThreadId, setPickedThreadId] = useState<string | undefined>();
  const threadId = useMemo(
    () =>
      threads.some((thread) => thread.thread_id === pickedThreadId)
        ? pickedThreadId
        : threads[0]?.thread_id,
    [threads, pickedThreadId],
  );

  const historyQuery = useHistory(activeAgentId, threadId);
  const history = historyQuery.data?.data;
  const selectedThread = threads.find((thread) => thread.thread_id === threadId);

  const timezoneQuery = useQuery({
    queryKey: ["settings", "timezone"],
    queryFn: getTimezone,
    staleTime: Infinity,
  });

  const createThread = useCreateThread(activeAgentId);

  // `sending` stays true until the server reports the turn done, so the
  // composer cannot queue a second turn behind a running one.
  const [sending, setSending] = useState(false);

  const socket = useChatSocket(activeAgentId, threadId, () => {
    setSending(false);
    void queryClient.invalidateQueries({
      queryKey: chatKeys.history(activeAgentId ?? "", threadId ?? ""),
    });
    void queryClient.invalidateQueries({
      queryKey: chatKeys.threads(activeAgentId ?? ""),
    });
  });

  const source = agentsQuery.data?.source ?? threadsQuery.data?.source ?? "live";
  const socketReady = socket.status === "open" && Boolean(threadId);
  const canSend = source === "live" && socketReady && !sending;

  const agentName = useMemo(
    () => agents.find((agent) => agent.agent_id === activeAgentId)?.name ?? "Agent",
    [agents, activeAgentId],
  );

  if (agentsQuery.isPending) {
    return (
      <>
        <Topbar title={t("title")} subtitle={t("subtitle")} />
        <LoadingBlock label={tCommon("state.loading")} className="flex-1" />
      </>
    );
  }

  if (agents.length === 0) {
    return (
      <>
        <Topbar title={t("title")} subtitle={t("subtitle")} />
        <div className="flex flex-1 items-center justify-center">
          <EmptyState
            size="lg"
            title={t("agent.empty")}
            description={t("agent.emptyDescription")}
          />
        </div>
      </>
    );
  }

  return (
    <>
      <Topbar
        title={selectedThread?.title || t("threads.untitled")}
        subtitle={agentName}
        actions={
          <Badge tone={source === "live" ? "success" : "warning"} dot>
            {source === "live" ? t("status.live") : t("status.mock")}
          </Badge>
        }
      >
        <div className="ml-2 hidden items-center gap-2 md:flex">
          <Select
            aria-label={t("agent.label")}
            value={activeAgentId ?? ""}
            onChange={(event) => {
              setPickedAgentId(event.target.value);
              setPickedThreadId(undefined);
            }}
            options={agents.map((agent) => ({
              value: agent.agent_id,
              label: `${agent.name} · ${agent.state}`,
            }))}
            className="w-52"
          />
        </div>
      </Topbar>

      {source === "mock" ? (
        <div className="px-3 pt-3 md:px-6">
          <Alert tone="warning" title={tCommon("state.offline")}>
            {tCommon("state.offlineDescription")}
          </Alert>
        </div>
      ) : null}

      <div className="flex min-h-0 flex-1">
        <div className="hidden w-60 shrink-0 md:block">
          <ThreadRail
            threads={threads}
            loading={threadsQuery.isPending}
            selectedId={threadId}
            onSelect={setPickedThreadId}
            onCreate={() =>
              createThread.mutate(undefined, {
                onSuccess: (result) => setPickedThreadId(result.thread_id),
              })
            }
            creating={createThread.isPending}
            timezone={timezoneQuery.data}
          />
        </div>

        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex items-center gap-2 border-b border-line-subtle px-3 py-2 md:hidden">
            <Select
              aria-label={t("threads.label")}
              value={threadId ?? ""}
              onChange={(event) => setPickedThreadId(event.target.value)}
              options={threads.map((thread) => ({
                value: thread.thread_id,
                label: thread.title || t("threads.untitled"),
              }))}
              className="flex-1"
            />
            <Button
              variant="secondary"
              size="icon-sm"
              aria-label={t("threads.new")}
              loading={createThread.isPending}
              onClick={() =>
                createThread.mutate(undefined, {
                  onSuccess: (result) => setPickedThreadId(result.thread_id),
                })
              }
            >
              <Plus />
            </Button>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto">
            <MessageList
              messages={history?.messages ?? []}
              loading={historyQuery.isPending}
              agentName={agentName}
              timezone={timezoneQuery.data}
            />
          </div>

          <Composer
            disabled={!canSend}
            sending={sending}
            disabledReason={
              source === "mock"
                ? t("composer.disabled")
                : socket.status !== "open"
                  ? t("composer.disabled")
                  : undefined
            }
            onSend={(text) => {
              const sent = socket.send(text);
              setSending(sent);
              if (sent) {
                window.setTimeout(
                  () => void queryClient.invalidateQueries({
                    queryKey: chatKeys.history(activeAgentId ?? "", threadId ?? ""),
                  }),
                  1200,
                );
              }
            }}
          />
        </div>
      </div>
    </>
  );
}
