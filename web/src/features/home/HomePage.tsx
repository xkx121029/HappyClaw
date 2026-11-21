import { Link } from "@tanstack/react-router";
import {
  Activity,
  ArrowUpRight,
  Bot,
  MessageSquare,
  Palette,
  Radio,
  Settings,
  ShieldQuestion,
  TerminalSquare,
  Zap,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { PageBody, Topbar } from "@/components/layout/topbar";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader, Stat } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton, SkeletonText } from "@/components/ui/skeleton";
import { useUiStore } from "@/stores/ui";
import { formatRelativeTime } from "@/lib/format";

import { formatTokens } from "./format";
import { useActivity, useAgents, usePendingApprovals, useRecentThreads, useUsage } from "./queries";

export function HomePage() {
  const { t } = useTranslation("home");
  const { t: tCommon } = useTranslation();
  const locale = useUiStore((state) => state.locale);

  const activity = useActivity();
  const usage = useUsage();
  const agents = useAgents();
  const agentIds = (agents.data ?? []).map((agent) => agent.agent_id);
  const pending = usePendingApprovals(agentIds);
  const recent = useRecentThreads(agents.data ?? []);

  const runtime = activity.data;
  const backendDown = activity.isSuccess && activity.data === null;
  const usageData = usage.data ?? null;
  const tokens = usageData?.total_tokens ?? 0;

  return (
    <>
      <Topbar
        title={t("title")}
        subtitle={t("subtitle")}
        actions={
          runtime ? (
            <Badge tone={runtime.busy ? "accent" : "success"} dot>
              {runtime.busy ? t("activity.busy") : t("activity.idle")}
            </Badge>
          ) : null
        }
      />
      <PageBody>
        <div className="grid gap-4">
          {backendDown ? (
            <Alert tone="warning" title={tCommon("state.offline")}>
              {tCommon("state.offlineDescription")}
            </Alert>
          ) : null}

          <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {activity.isPending ? (
              Array.from({ length: 4 }, (_, index) => (
                <Card key={index} className="p-4">
                  <Skeleton className="h-3 w-24" />
                  <Skeleton className="mt-3 h-6 w-16" />
                </Card>
              ))
            ) : (
              <>
                <Stat
                  label={t("activity.runningAgents")}
                  value={runtime?.running_agents ?? 0}
                  icon={<Bot />}
                />
                <Stat
                  label={t("activity.activeTurns")}
                  value={runtime?.active_turns ?? 0}
                  icon={<Activity />}
                />
                <Stat
                  label={t("activity.terminalSessions")}
                  value={runtime?.terminal_sessions ?? 0}
                  icon={<TerminalSquare />}
                />
                <Stat
                  label={t("usage.tokens")}
                  value={formatTokens(tokens, locale)}
                  delta={
                    usageData
                      ? { value: `${usageData.turns} ${t("usage.turns")}`, tone: "flat" }
                      : undefined
                  }
                  icon={<Zap />}
                />
              </>
            )}
          </section>

          <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
            <div className="grid gap-4">
              <Card>
                <CardHeader
                  title={t("needsYou.title")}
                  description={
                    pending.items.length > 0
                      ? t("needsYou.count", { count: pending.items.length })
                      : undefined
                  }
                  actions={
                    pending.items.length > 0 ? (
                      <Badge tone="warning" dot>
                        {pending.items.length}
                      </Badge>
                    ) : null
                  }
                />
                <CardBody className="p-0">
                  {pending.isPending ? (
                    <div className="p-4">
                      <SkeletonText lines={2} />
                    </div>
                  ) : pending.items.length === 0 ? (
                    <EmptyState
                      size="sm"
                      icon={<ShieldQuestion />}
                      title={t("needsYou.empty")}
                      description={t("needsYou.emptyDescription")}
                    />
                  ) : (
                    <ul className="divide-y divide-line-subtle">
                      {pending.items.map((item) => (
                        <li key={item.pendingId} className="flex items-center gap-3 px-4 py-3">
                          <Badge tone={item.kind === "approval" ? "warning" : "info"} dot>
                            {item.kind === "approval" ? "approval" : "question"}
                          </Badge>
                          <span className="min-w-0 flex-1 truncate text-sm text-fg-muted">
                            {item.sessionTitle ?? item.threadId}
                          </span>
                          <Button variant="ghost" size="xs" asChild>
                            <Link to="/chat">{t("needsYou.open")}</Link>
                          </Button>
                        </li>
                      ))}
                    </ul>
                  )}
                </CardBody>
              </Card>

              <Card>
                <CardHeader
                  title={t("threads.title")}
                  actions={
                    <Button variant="ghost" size="xs" asChild>
                      <Link to="/chat">
                        {t("threads.open")} <ArrowUpRight />
                      </Link>
                    </Button>
                  }
                />
                <CardBody className="p-0">
                  {recent.isPending ? (
                    <div className="grid gap-2 p-4">
                      <Skeleton className="h-4 w-2/3" />
                      <Skeleton className="h-4 w-1/2" />
                    </div>
                  ) : recent.threads.length === 0 ? (
                    <EmptyState
                      size="sm"
                      icon={<MessageSquare />}
                      title={t("threads.empty")}
                      description={t("threads.emptyDescription")}
                    />
                  ) : (
                    <ul className="divide-y divide-line-subtle">
                      {recent.threads.map((thread) => (
                        <li key={thread.thread_id}>
                          <Link
                            to="/chat"
                            className="flex items-center gap-3 px-4 py-2.5 transition-colors hover:bg-hover"
                          >
                            <span className="min-w-0 flex-1">
                              <span className="block truncate text-sm text-fg">
                                {thread.title || t("threads.untitled")}
                              </span>
                              <span className="block truncate text-2xs text-fg-subtle">
                                {thread.agentName}
                              </span>
                            </span>
                            {thread.hasMessages ? null : (
                              <Badge tone="outline">{t("threads.noMessages")}</Badge>
                            )}
                            <span className="shrink-0 font-mono text-2xs text-fg-subtle">
                              {formatRelativeTime(thread.timestamp, undefined)}
                            </span>
                          </Link>
                        </li>
                      ))}
                    </ul>
                  )}
                </CardBody>
              </Card>
            </div>

            <div className="grid content-start gap-4">
              <Card>
                <CardHeader title={t("agents.title")} />
                <CardBody className="p-0">
                  {agents.isPending ? (
                    <div className="grid gap-2 p-4">
                      <Skeleton className="h-4 w-1/2" />
                      <Skeleton className="h-4 w-2/3" />
                    </div>
                  ) : (agents.data ?? []).length === 0 ? (
                    <EmptyState
                      size="sm"
                      icon={<Bot />}
                      title={t("agents.empty")}
                      description={t("agents.emptyDescription")}
                    />
                  ) : (
                    <ul className="divide-y divide-line-subtle">
                      {(agents.data ?? []).map((agent) => (
                        <li key={agent.agent_id} className="flex items-center gap-2 px-4 py-2.5">
                          <span className="min-w-0 flex-1 truncate text-sm text-fg">
                            {agent.name}
                          </span>
                          <Badge
                            tone={
                              agent.state === "running"
                                ? "success"
                                : agent.state === "failed"
                                  ? "danger"
                                  : "neutral"
                            }
                            dot
                          >
                            {t(
                              `agents.state.${
                                agent.state in STATE_KEYS ? agent.state : "created"
                              }` as "agents.state.running",
                            )}
                          </Badge>
                          <Button variant="ghost" size="xs" asChild>
                            <Link to="/chat">{t("agents.chat")}</Link>
                          </Button>
                        </li>
                      ))}
                    </ul>
                  )}
                </CardBody>
              </Card>

              <Card>
                <CardHeader title={t("activity.title")} />
                <CardBody className="grid gap-2">
                  <dl className="grid grid-cols-2 gap-2 text-xs">
                    <Metric
                      label={t("activity.connections")}
                      value={runtime?.dashboard_connections ?? 0}
                    />
                    <Metric
                      label={t("activity.terminalSessions")}
                      value={runtime?.terminal_sessions ?? 0}
                    />
                    <Metric
                      label={t("usage.modelCalls")}
                      value={usageData ? formatTokens(usageData.model_calls, locale) : "—"}
                    />
                    <Metric
                      label={t("usage.cacheHit")}
                      value={usageData ? `${usageData.cache_hit_percent.toFixed(0)}%` : "—"}
                    />
                  </dl>
                  <p className="flex items-center gap-1.5 text-2xs text-fg-subtle">
                    <Radio className="size-3" />
                    {t("activity.updated", {
                      time: runtime
                        ? formatRelativeTime(runtime.updated_at, undefined)
                        : "—",
                    })}
                  </p>
                </CardBody>
              </Card>

              <Card>
                <CardHeader title={t("quick.title")} />
                <CardBody className="grid gap-1.5">
                  <QuickLink to="/chat" icon={<MessageSquare />} label={t("quick.chat")} />
                  <QuickLink to="/settings" icon={<Settings />} label={t("quick.settings")} />
                  <QuickLink to="/design" icon={<Palette />} label={t("quick.design")} />
                </CardBody>
              </Card>
            </div>
          </div>
        </div>
      </PageBody>
    </>
  );
}

const STATE_KEYS = {
  running: true,
  stopped: true,
  starting: true,
  stopping: true,
  failed: true,
  created: true,
} as const;

function Metric({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-sm bg-sunken px-2.5 py-2">
      <dt className="text-2xs text-fg-subtle">{label}</dt>
      <dd className="mt-0.5 font-mono text-sm text-fg">{value}</dd>
    </div>
  );
}

function QuickLink({
  to,
  icon,
  label,
}: {
  to: "/chat" | "/settings" | "/design";
  icon: React.ReactNode;
  label: string;
}) {
  return (
    <Link
      to={to}
      className="flex items-center gap-2 rounded-sm px-2 py-1.5 text-sm text-fg-muted transition-colors hover:bg-hover hover:text-fg [&_svg]:size-3.5"
    >
      {icon}
      <span className="flex-1">{label}</span>
      <ArrowUpRight className="text-fg-subtle" />
    </Link>
  );
}
