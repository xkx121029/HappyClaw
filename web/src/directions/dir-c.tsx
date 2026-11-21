import {
  Activity,
  ArrowUpRight,
  BookOpen,
  Check,
  ChevronsUpDown,
  CircleDot,
  FileCode2,
  Files,
  Globe,
  Gauge,
  MessageSquare,
  Moon,
  Play,
  Search,
  Settings2,
  ShieldQuestion,
  Sun,
  Terminal,
  Workflow,
} from "lucide-react";
import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Avatar } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardFooter, CardHeader, Stat } from "@/components/ui/card";
import { Checkbox, Switch } from "@/components/ui/checkbox";
import { Dialog } from "@/components/ui/dialog";
import { DropdownMenu } from "@/components/ui/dropdown-menu";
import { EmptyState } from "@/components/ui/empty-state";
import { Field } from "@/components/ui/field";
import { Input, Textarea } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Select } from "@/components/ui/select";
import { Kbd, Separator } from "@/components/ui/separator";
import { Skeleton, SkeletonList, SkeletonText } from "@/components/ui/skeleton";
import { LoadingBlock, Spinner } from "@/components/ui/spinner";
import { TBody, TD, TH, THead, TR, Table } from "@/components/ui/table";
import { Segmented, Tabs } from "@/components/ui/tabs";
import { Toaster } from "@/components/ui/toaster";
import { Tooltip } from "@/components/ui/tooltip";
import {
  agent,
  instrument,
  palette,
  radii,
  spacingScale,
  tableRows,
  threads,
  turns,
  typeScale,
  type Trace,
} from "@/directions/data";
import { useDirectionScope, useThemeToggle, useTokenValue } from "@/directions/scope";
import { useToastStore } from "@/lib/toast";

/* ------------------------------------------------------------------ chrome */

function Rail() {
  const items = [
    { icon: MessageSquare, label: "对话", active: true },
    { icon: Workflow, label: "任务" },
    { icon: Files, label: "文件" },
    { icon: Globe, label: "工作台" },
    { icon: BookOpen, label: "知识库" },
  ];
  return (
    <aside className="hidden w-16 shrink-0 flex-col items-center gap-1 border-e border-line bg-surface py-3 sm:flex">
      <span aria-hidden className="mb-2 grid size-9 place-items-center rounded-xs bg-accent text-fg-onaccent">
        <Terminal className="size-4" />
      </span>
      {items.map((item) => (
        <Tooltip key={item.label} content={item.label} side="right">
          <button
            type="button"
            aria-label={item.label}
            className="dc-rail-item"
            data-active={item.active ? "1" : "0"}
          >
            <item.icon className="size-[18px]" />
          </button>
        </Tooltip>
      ))}
      <div className="mt-auto grid gap-1">
        <button type="button" aria-label="设置" className="dc-rail-item">
          <Settings2 className="size-[18px]" />
        </button>
      </div>
    </aside>
  );
}

function ThreadList() {
  return (
    <aside className="hidden w-72 shrink-0 flex-col border-e border-line bg-canvas lg:flex">
      <div className="flex items-center justify-between px-4 pb-3 pt-4">
        <span className="text-sm font-semibold text-fg">会话</span>
        <Button size="xs" variant="secondary">
          新建
        </Button>
      </div>
      <div className="px-3 pb-3">
        <Input placeholder="搜索会话" leadingIcon={<Search />} className="h-8 bg-surface text-xs" />
      </div>
      <nav className="min-h-0 flex-1 overflow-y-auto px-2">
        {threads.map((thread, index) => {
          const active = index === 0;
          return (
            <a
              key={thread.id}
              href="#"
              aria-current={active ? "true" : undefined}
              className={`mb-1 block rounded-lg px-3 py-2.5 transition-colors ${
                active
                  ? "bg-surface shadow-xs ring-1 ring-line-subtle"
                  : "hover:bg-hover"
              }`}
            >
              <span className="flex items-center justify-between gap-2">
                <span className={`truncate text-xs ${active ? "font-semibold text-fg" : "text-fg-muted"}`}>
                  {thread.title}
                </span>
                <span className="shrink-0 text-2xs text-fg-subtle">{thread.stamp}</span>
              </span>
              <span className="mt-1 flex items-center gap-1.5 text-2xs text-fg-subtle">
                <span>{thread.turns} 轮</span>
                <span aria-hidden>·</span>
                <span>{thread.tools} 次工具</span>
                {thread.state === "running" ? (
                  <span className="ms-auto inline-flex items-center gap-1 text-accent-fg">
                    <i className="dc-live-dot" aria-hidden />
                    运行中
                  </span>
                ) : null}
                {thread.state === "review" ? (
                  <span className="ms-auto text-warning">待复核</span>
                ) : null}
              </span>
            </a>
          );
        })}
      </nav>
      <div className="border-t border-line-subtle px-4 py-3">
        <div className="flex items-center gap-2">
          <Avatar name="开心爸爸" size="xs" />
          <span className="truncate text-2xs text-fg-muted">本机 · xkx121029</span>
        </div>
      </div>
    </aside>
  );
}

function Header() {
  const { theme, toggleTheme } = useThemeToggle();
  return (
    <header className="flex shrink-0 items-center justify-between gap-3 border-b border-line bg-surface px-4 py-2.5 sm:px-5">
      <div className="flex min-w-0 items-center gap-3">
        <Avatar name="HappyClaw" size="md" />
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="truncate text-sm font-semibold text-fg">{agent.name}</span>
            <span className="inline-flex items-center gap-1 rounded-full bg-accent-soft px-2 py-0.5 text-2xs text-accent-fg">
              <i className="dc-live-dot" aria-hidden />
              运行中
            </span>
          </div>
          <span className="truncate text-2xs text-fg-subtle">
            {agent.role} · {agent.model}
          </span>
        </div>
      </div>
      <div className="flex items-center gap-1">
        <span className="hidden items-center gap-1.5 rounded-full bg-inset px-2.5 py-1 text-2xs text-fg-muted md:flex">
          <Gauge className="size-3" />
          {Math.round((instrument.contextUsed / instrument.contextMax) * 100)}% 上下文
        </span>
        <button
          type="button"
          onClick={() => void toggleTheme()}
          aria-label="切换主题"
          className="dc-rail-item !size-9"
        >
          {theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
        </button>
        <DropdownMenu
          trigger={
            <button type="button" aria-label="会话选项" className="dc-rail-item !size-9">
              <ChevronsUpDown className="size-4" />
            </button>
          }
          items={[
            { key: "rename", label: "重命名会话", onSelect: () => undefined },
            { key: "export", label: "导出记录", onSelect: () => undefined },
            { key: "del", label: "删除会话", danger: true, separated: true, onSelect: () => undefined },
          ]}
        />
      </div>
    </header>
  );
}

function TraceCard({ trace }: { trace: Trace }) {
  const icon =
    trace.tool === "read_file" ? (
      <FileCode2 className="size-3.5" />
    ) : trace.tool === "grep" ? (
      <Search className="size-3.5" />
    ) : trace.tool === "pytest" ? (
      <Play className="size-3.5" />
    ) : (
      <ShieldQuestion className="size-3.5" />
    );
  return (
    <div className="flex items-center gap-3 rounded-lg border border-line-subtle bg-surface px-3 py-2">
      <span className="grid size-7 shrink-0 place-items-center rounded-md bg-inset text-fg-subtle">
        {icon}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-xs text-fg">
          <span className="font-medium">{trace.tool}</span>{" "}
          <span className="text-fg-muted">{trace.target}</span>
        </span>
        <span className="block text-2xs text-fg-subtle">{trace.meta}</span>
      </span>
      {trace.state === "waiting" ? (
        <span className="flex shrink-0 items-center gap-1.5">
          <Badge tone="warning" dot>
            待批准
          </Badge>
          <Button size="xs" variant="primary">
            批准
          </Button>
        </span>
      ) : (
        <Check className="size-3.5 shrink-0 text-success" />
      )}
    </div>
  );
}

function ThreadC() {
  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto w-full max-w-[720px] px-4 py-6 sm:px-6">
        <div className="mb-5 flex flex-wrap items-center gap-2">
          <Badge tone="neutral" icon={<CircleDot className="size-3" />}>
            本机主机
          </Badge>
          <Badge tone="outline">worktree</Badge>
          <Badge tone="accent">WebSocket 已连接</Badge>
          <span className="ms-auto text-2xs text-fg-subtle">共 8 轮</span>
        </div>

        <div className="grid gap-5">
          {turns.map((turn) =>
            turn.role === "user" ? (
              <div key={turn.id} className="flex flex-col items-end gap-1.5">
                <div className="dc-bubble-user max-w-[86%] px-4 py-2.5 text-[16px] leading-relaxed text-fg sm:text-[14px]">
                  {turn.body[0]}
                </div>
                <span className="me-1 text-2xs text-fg-subtle">
                  我 · {turn.time}
                </span>
              </div>
            ) : (
              <div key={turn.id} className="flex gap-2.5">
                <Avatar name="HappyClaw" size="sm" className="mt-0.5" />
                <div className="min-w-0 flex-1">
                  <div className="dc-bubble-agent px-4 py-3">
                    <div className="grid gap-2.5">
                      {turn.body.map((paragraph, index) =>
                        paragraph.startsWith("code:") ? (
                          <pre
                            key={index}
                            className="overflow-x-auto rounded-md border border-line-subtle bg-surface px-3 py-2 font-mono text-2xs leading-relaxed text-fg-muted"
                          >
                            {paragraph.slice(5)}
                          </pre>
                        ) : (
                          <p key={index} className="text-[16px] leading-[1.72] text-fg sm:text-[14px]">
                            {paragraph.split("`").map((chunk, chunkIndex) =>
                              chunkIndex % 2 === 1 ? (
                                <code
                                  key={chunkIndex}
                                  className="rounded-xs bg-surface px-1 py-px font-mono text-2xs text-accent-fg"
                                >
                                  {chunk}
                                </code>
                              ) : (
                                <span key={chunkIndex}>{chunk}</span>
                              ),
                            )}
                            {turn.streaming && index === turn.body.length - 1 ? (
                              <span className="ms-0.5 inline-flex gap-0.5 align-baseline" aria-hidden>
                                <i className="size-1 rounded-full bg-accent" />
                                <i className="size-1 rounded-full bg-accent/60" />
                                <i className="size-1 rounded-full bg-accent/30" />
                              </span>
                            ) : null}
                          </p>
                        ),
                      )}
                    </div>
                    {turn.traces ? (
                      <div className="mt-3 grid gap-1.5">
                        {turn.traces.map((trace) => (
                          <TraceCard key={trace.tool + trace.target} trace={trace} />
                        ))}
                      </div>
                    ) : null}
                  </div>
                  <div className="mt-1.5 flex items-center gap-3 ps-1 text-2xs text-fg-subtle">
                    <span>{turn.time}</span>
                    {turn.tokens ? <span>{turn.tokens}</span> : null}
                    <button type="button" className="ms-auto inline-flex items-center gap-1 hover:text-fg">
                      复制
                    </button>
                  </div>
                </div>
              </div>
            ),
          )}
        </div>
        <div className="h-6" />
      </div>
    </div>
  );
}

function SidePanels() {
  const pct = Math.round((instrument.contextUsed / instrument.contextMax) * 100);
  return (
    <aside className="hidden w-80 shrink-0 overflow-y-auto border-s border-line bg-canvas p-4 lg:block">
      <div className="grid gap-3">
        <section className="dc-panel p-4">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-fg">运行</span>
            <Badge tone="accent" dot>
              进行中
            </Badge>
          </div>
          <div className="mt-3 flex items-center gap-4">
            <div
              className="dc-meter-ring size-14"
              style={{ ["--pct" as string]: pct }}
              aria-hidden
            >
              <span className="grid size-10 place-items-center rounded-full bg-surface text-xs font-semibold text-fg">
                {pct}%
              </span>
            </div>
            <div className="grid gap-1">
              <span className="text-2xs text-fg-subtle">上下文</span>
              <span className="text-sm font-medium text-fg">
                {instrument.contextUsed}k / {instrument.contextMax}k
              </span>
              <span className="text-2xs text-fg-subtle">用时 {instrument.elapsed}</span>
            </div>
          </div>
          <div className="mt-3 grid grid-cols-3 gap-2 border-t border-line-subtle pt-3 text-center">
            <div>
              <p className="text-sm font-semibold text-fg">{instrument.toolCalls}</p>
              <p className="text-2xs text-fg-subtle">工具</p>
            </div>
            <div>
              <p className="text-sm font-semibold text-fg">{instrument.approvals}</p>
              <p className="text-2xs text-fg-subtle">待批</p>
            </div>
            <div>
              <p className="text-sm font-semibold text-fg">3</p>
              <p className="text-2xs text-fg-subtle">文件</p>
            </div>
          </div>
        </section>

        <section className="dc-panel p-4">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-fg">需要你确认</span>
            <ShieldQuestion className="size-3.5 text-warning" />
          </div>
          <p className="mt-2 text-xs leading-relaxed text-fg-muted">
            apply_patch 将改写 <span className="font-mono text-fg">pool.py</span> 三处，
            净增 11 行、删除 4 行。
          </p>
          <div className="mt-3 flex gap-2">
            <Button size="sm" variant="primary" className="flex-1">
              批准
            </Button>
            <Button size="sm" variant="secondary" className="flex-1">
              查看差异
            </Button>
          </div>
        </section>

        <section className="dc-panel p-4">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-fg">工具托盘</span>
            <Activity className="size-3.5 text-fg-subtle" />
          </div>
          <div className="mt-2.5 flex flex-wrap gap-1.5">
            <span className="dc-chip" data-on="1">
              <FileCode2 className="size-3" /> 读取
            </span>
            <span className="dc-chip" data-on="1">
              <Search className="size-3" /> 搜索
            </span>
            <span className="dc-chip">
              <Terminal className="size-3" /> 终端
            </span>
            <span className="dc-chip">
              <Globe className="size-3" /> 浏览器
            </span>
          </div>
          <div className="mt-3 grid gap-2">
            <div className="flex items-center justify-between text-2xs text-fg-subtle">
              <span>今日调用</span>
              <span>12 / 40</span>
            </div>
            <Progress value={30} label="今日调用" />
          </div>
        </section>

        <section className="dc-panel-flat p-4">
          <span className="text-2xs font-medium text-fg-subtle">提示</span>
          <p className="mt-1 text-xs leading-relaxed text-fg-muted">
            读取类工具可以自动批准，写入类永远等你点一次。这条规则在设置里改。
          </p>
          <button type="button" className="mt-2 inline-flex items-center gap-1 text-xs text-accent-fg">
            打开设置 <ArrowUpRight className="size-3" />
          </button>
        </section>
      </div>
    </aside>
  );
}

function ComposerC() {
  return (
    <div className="shrink-0 px-3 pb-3 pt-1 sm:px-5 sm:pb-4">
      <div className="dc-dock mx-auto w-full max-w-[760px] p-2.5">
        <div className="flex items-start gap-2">
          <Textarea
            rows={1}
            aria-label="输入"
            placeholder="问点什么，或者直接派活…"
            className="min-h-9 resize-none border-0 bg-transparent px-2 py-2 text-base shadow-none focus-visible:shadow-none"
          />
          <Button size="icon" variant="primary" aria-label="发送" className="rounded-full">
            <ArrowUpRight />
          </Button>
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-1.5 px-1">
          <span className="dc-chip">
            <Gauge className="size-3" /> {agent.model}
          </span>
          <span className="dc-chip" data-on="1">
            <ShieldQuestion className="size-3" /> 写入需批准
          </span>
          <span className="dc-chip">
            <Terminal className="size-3" /> 本机
          </span>
          <span className="ms-auto hidden items-center gap-1.5 text-2xs text-fg-subtle sm:flex">
            <Kbd>⌘</Kbd>
            <Kbd>↵</Kbd>
            发送
          </span>
        </div>
      </div>
    </div>
  );
}

export function ChatDirectionC() {
  useDirectionScope("c");
  return (
    <div className="flex h-dvh min-h-0 bg-canvas text-fg">
      <Rail />
      <ThreadList />
      <div className="flex min-w-0 flex-1 flex-col">
        <Header />
        <div className="flex min-h-0 flex-1">
          <div className="flex min-w-0 flex-1 flex-col">
            <ThreadC />
            <ComposerC />
          </div>
          <SidePanels />
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------ design page C */

function SwatchC({ token, label }: { token: string; label: string }) {
  const value = useTokenValue(token);
  return (
    <div className="grid gap-1">
      <span
        className="h-9 rounded-sm border border-line-subtle"
        style={{ background: `var(${token})` }}
        aria-hidden
      />
      <span className="text-2xs text-fg">{label}</span>
      <span className="font-mono text-[0.6rem] text-fg-subtle">{value}</span>
    </div>
  );
}

function Panel({
  title,
  code,
  span = 1,
  children,
}: {
  title: string;
  code: string;
  span?: 1 | 2;
  children: React.ReactNode;
}) {
  return (
    <section className={`dc-panel p-4 ${span === 2 ? "lg:col-span-2" : ""}`}>
      <div className="mb-3 flex items-center justify-between">
        <span className="text-xs font-semibold text-fg">{title}</span>
        <span className="font-mono text-[0.6rem] text-fg-subtle">{code}</span>
      </div>
      <div className="flex flex-wrap items-center gap-2">{children}</div>
    </section>
  );
}

export function DesignDirectionC() {
  useDirectionScope("c");
  const push = useToastStore((state) => state.push);
  const [tab, setTab] = useState("overview");
  const [segment, setSegment] = useState<"list" | "grid">("list");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [autoApprove, setAutoApprove] = useState(true);

  return (
    <div className="flex h-dvh min-h-0 bg-canvas text-fg">
      <Rail />
      <div className="flex min-w-0 flex-1 flex-col">
        <Header />
        <div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-5">
          <div className="mx-auto w-full max-w-[1080px]">
            <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
              <div>
                <span className="text-2xs font-medium text-accent-fg">方向 C · 工作台</span>
                <h1 className="mt-1 text-2xl font-semibold tracking-tight text-fg">
                  设计系统托盘
                </h1>
              </div>
              <p className="max-w-md text-xs leading-relaxed text-fg-muted">
                角色靠底色分层，不靠边框；青瓷色只用于「正在进行」和「点这里」。
                色值从样式表实时读回。
              </p>
            </div>

            <div className="grid gap-3 lg:grid-cols-3">
              <Panel title="颜色" code="COLOR" span={2}>
                <div className="grid w-full grid-cols-5 gap-2 sm:grid-cols-10">
                  {palette.map((swatch) => (
                    <SwatchC key={swatch.name} token={swatch.token} label={swatch.name} />
                  ))}
                </div>
              </Panel>
              <Panel title="运行" code="METER">
                <div className="w-full">
                  <div className="flex items-baseline justify-between text-2xs text-fg-subtle">
                    <span>上下文</span>
                    <span className="text-fg">8.4k / 32k</span>
                  </div>
                  <Progress value={26} className="mt-1.5" label="上下文" />
                  <div className="mt-2 flex items-baseline justify-between text-2xs text-fg-subtle">
                    <span>今日调用</span>
                    <span className="text-fg">12 / 40</span>
                  </div>
                  <Progress value={30} tone="success" className="mt-1.5" label="今日调用" />
                </div>
              </Panel>

              <Panel title="字阶" code="TYPE" span={2}>
                <div className="grid w-full gap-1">
                  {typeScale.slice(2, 7).map((row) => (
                    <div key={row.token} className="flex items-baseline justify-between gap-3">
                      <span
                        className="truncate text-fg"
                        style={{ fontSize: `${Number(row.size) / 16}rem` }}
                      >
                        现在在跑的是连接池
                      </span>
                      <span className="shrink-0 font-mono text-[0.6rem] text-fg-subtle">
                        {row.size}px
                      </span>
                    </div>
                  ))}
                </div>
              </Panel>
              <Panel title="间距与圆角" code="SPACE">
                <div className="grid w-full gap-2">
                  <div className="flex items-end gap-1.5">
                    {spacingScale.map((row) => (
                      <span
                        key={row.token}
                        className="rounded-xs bg-accent-soft"
                        style={{ width: `${Number(row.px) / 2}px`, height: `${Number(row.px) / 2}px` }}
                        aria-hidden
                      />
                    ))}
                  </div>
                  <div className="flex items-center gap-1.5">
                    {radii.map((row) => (
                      <span
                        key={row.token}
                        className="size-5 border border-line bg-inset"
                        style={{ borderRadius: `var(${row.token})` }}
                        aria-hidden
                      />
                    ))}
                  </div>
                  <p className="text-2xs leading-relaxed text-fg-subtle">
                    圆角 6 → 22px，阴影短而软，浮层才加深。
                  </p>
                </div>
              </Panel>

              <Panel title="按钮" code="BTN" span={2}>
                <Button size="sm" variant="primary">
                  主要
                </Button>
                <Button size="sm" variant="secondary">
                  次要
                </Button>
                <Button size="sm" variant="ghost">
                  幽灵
                </Button>
                <Button size="sm" variant="subtle">
                  弱化
                </Button>
                <Button size="sm" variant="danger">
                  危险
                </Button>
                <Button size="sm" variant="link">
                  链接
                </Button>
                <Button size="sm" loading>
                  载入
                </Button>
                <Button size="icon-sm" aria-label="播放">
                  <Play />
                </Button>
              </Panel>
              <Panel title="输入" code="INPUT">
                <Input placeholder="搜索" leadingIcon={<Search />} className="min-w-36" />
                <Input placeholder="无效" invalid className="min-w-24" />
                <Select
                  defaultValue="fable"
                  options={[
                    { value: "fable", label: "claude-fable-5-2" },
                    { value: "sol", label: "gpt-6.2-sol" },
                  ]}
                  className="min-w-40"
                />
              </Panel>

              <Panel title="表单行" code="FIELD">
                <div className="w-full">
                  <Field label="时区" hint="取自服务端设置">
                    <Input defaultValue="Asia/Shanghai" />
                  </Field>
                </div>
                <Checkbox label="记住选择" defaultChecked />
                <Switch label="自动批准读取类工具" checked={autoApprove} onCheckedChange={setAutoApprove} />
              </Panel>
              <Panel title="标记" code="MARK">
                <Badge tone="neutral">默认</Badge>
                <Badge tone="accent">强调</Badge>
                <Badge tone="success" dot>
                  运行中
                </Badge>
                <Badge tone="warning">待批准</Badge>
                <Badge tone="danger">失败</Badge>
                <Badge tone="outline">outline</Badge>
                <Avatar name="HappyClaw" size="xs" />
                <Avatar name="开心爸爸" size="sm" />
                <Avatar name="xkx121029" size="md" />
              </Panel>
              <Panel title="卡片与指标" code="CARD" span={2}>
                <div className="grid w-full gap-2 sm:grid-cols-3">
                  <Stat label="今日运行" value="12" delta={{ value: "+3 较昨日", tone: "up" }} />
                  <Card className="p-3">
                    <CardHeader title="上下文" description="8.4k / 32k" className="border-b-0 px-0 pt-0" />
                    <Progress value={26} label="上下文" />
                  </Card>
                  <Card className="grid gap-2 p-3">
                    <CardBody className="p-0 text-xs text-fg-muted">卡片是一块托盘。</CardBody>
                    <CardFooter className="justify-start border-t-0 px-0 pb-0 pt-1">
                      <Button size="xs" variant="secondary">
                        查看
                      </Button>
                    </CardFooter>
                  </Card>
                </div>
              </Panel>
              <Panel title="模态" code="DIALOG">
                <Button size="sm" onClick={() => setDialogOpen(true)}>
                  打开对话框
                </Button>
                <DropdownMenu
                  trigger={
                    <Button size="sm" variant="secondary" trailingIcon={<ChevronsUpDown />}>
                      更多
                    </Button>
                  }
                  items={[
                    { key: "copy", label: "复制线程 ID", onSelect: () => undefined },
                    { key: "export", label: "导出为 Markdown", onSelect: () => undefined },
                    { key: "del", label: "删除线程", danger: true, separated: true, onSelect: () => undefined },
                  ]}
                />
                <Tooltip content="复制到剪贴板">
                  <Button size="icon-sm" variant="secondary" aria-label="复制">
                    <Check />
                  </Button>
                </Tooltip>
              </Panel>

              <Panel title="提示与空态" code="NOTE" span={2}>
                <div className="grid w-full gap-2">
                  <Alert tone="info" title="提示">
                    取消异常会绕过 release()，这是本次泄漏的根因。
                  </Alert>
                  <Alert tone="warning" title="需要确认" action={<Button size="xs">批准</Button>}>
                    apply_patch 有 3 处改动待写入。
                  </Alert>
                </div>
                <div className="w-full rounded-lg border border-dashed border-line">
                  <EmptyState
                    size="sm"
                    icon={<BookOpen />}
                    title="还没有会话"
                    description="派一件事给它，或者让它自己跑一个定时任务。"
                    action={
                      <Button size="xs" variant="secondary">
                        新建
                      </Button>
                    }
                  />
                </div>
              </Panel>
              <Panel title="载入" code="LOAD">
                <Spinner size="sm" />
                <div className="w-32">
                  <SkeletonText lines={2} />
                </div>
                <div className="w-28">
                  <Skeleton className="h-4 w-full" />
                </div>
                <div className="w-40">
                  <SkeletonList rows={2} />
                </div>
              </Panel>
              <Panel title="进度" code="PROGRESS">
                <div className="grid w-full gap-2">
                  <Progress value={26} label="上下文" />
                  <Progress value={64} tone="success" label="任务" />
                  <Progress value={88} tone="warning" label="配额" />
                </div>
                <div className="w-32">
                  <LoadingBlock label="载入中" />
                </div>
              </Panel>
              <Panel title="切换" code="TAB" span={2}>
                <Tabs
                  items={[
                    { value: "overview", label: "概览" },
                    { value: "trace", label: "轨迹", badge: "12" },
                    { value: "files", label: "文件" },
                  ]}
                  value={tab}
                  onValueChange={setTab}
                />
                <Segmented
                  options={[
                    { value: "list", label: "列表" },
                    { value: "grid", label: "网格" },
                  ]}
                  value={segment}
                  onChange={setSegment}
                />
                <div className="flex w-full items-center gap-3 pt-1">
                  <span className="text-2xs text-fg-subtle">上</span>
                  <Separator />
                  <span className="text-2xs text-fg-subtle">下</span>
                </div>
              </Panel>
              <Panel title="表格与快捷键" code="TABLE" span={2}>
                <div className="w-full overflow-hidden rounded-md border border-line-subtle bg-surface">
                  <Table>
                    <THead>
                      <TR>
                        <TH>文件</TH>
                        <TH>范围</TH>
                        <TH>令牌</TH>
                        <TH>状态</TH>
                      </TR>
                    </THead>
                    <TBody>
                      {tableRows.map((row) => (
                        <TR key={row.key}>
                          <TD className="font-mono text-xs">{row.key}</TD>
                          <TD>{row.scope}</TD>
                          <TD className="tabular-nums">{row.cost}</TD>
                          <TD>
                            <Badge tone={row.state === "通过" ? "success" : "neutral"}>{row.state}</Badge>
                          </TD>
                        </TR>
                      ))}
                    </TBody>
                  </Table>
                </div>
                <div className="flex items-center gap-2">
                  <Kbd>⌘</Kbd>
                  <Kbd>K</Kbd>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => push({ tone: "success", title: "已复制", description: "线程 ID 写入剪贴板" })}
                  >
                    触发 Toast
                  </Button>
                </div>
              </Panel>
            </div>
          </div>
        </div>
      </div>

      <Dialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        title="删除会话"
        description="这个操作不可撤销，历史记录会一起删掉。"
        closeLabel="关闭"
        footer={
          <>
            <Button size="sm" variant="ghost" onClick={() => setDialogOpen(false)}>
              取消
            </Button>
            <Button size="sm" variant="danger" onClick={() => setDialogOpen(false)}>
              删除
            </Button>
          </>
        }
      >
        <p className="font-mono text-xs text-fg-muted">THREAD 01 · 08 TURNS · 12 TOOLS</p>
      </Dialog>
      <Toaster />
    </div>
  );
}
