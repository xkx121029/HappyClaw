import {
  Activity,
  Check,
  ChevronsUpDown,
  CornerDownLeft,
  FileCode2,
  Gauge,
  Moon,
  Play,
  Search,
  ShieldQuestion,
  Sun,
  Terminal,
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
import {
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
} from "@/components/ui/table";
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
  traceLog,
  turns,
  typeScale,
  type Trace,
} from "@/directions/data";
import { useDirectionScope, useThemeToggle, useTokenValue } from "@/directions/scope";
import { useToastStore } from "@/lib/toast";

/* ------------------------------------------------------------------ chrome */

function Rule({ className = "" }: { className?: string }) {
  return <div className={`da-hair ${className}`} aria-hidden />;
}

function TopBar() {
  const { theme, toggleTheme } = useThemeToggle();
  return (
    <header className="grid h-12 shrink-0 grid-cols-[1fr_auto] items-center border-b border-line bg-surface px-4">
      <div className="flex min-w-0 items-center gap-4">
        <div className="flex items-center gap-2">
          <span aria-hidden className="grid size-4 place-items-center bg-fg text-surface">
            <Terminal className="size-3" />
          </span>
          <span className="da-label !text-fg">HAPPYCLAW</span>
        </div>
        <span aria-hidden className="h-4 w-px bg-line" />
        <span className="da-num truncate text-2xs text-fg-muted">
          {agent.role}
        </span>
      </div>
      <div className="flex items-center gap-3">
        <span className="hidden items-center gap-1.5 sm:flex">
          <i className="da-live" aria-hidden />
          <span className="da-label">WS 已连接</span>
        </span>
        <span aria-hidden className="hidden h-4 w-px bg-line sm:block" />
        <button
          type="button"
          onClick={() => void toggleTheme()}
          className="da-label inline-flex items-center gap-1.5 px-1 py-1 hover:text-fg"
          aria-label="切换主题"
        >
          {theme === "dark" ? <Sun className="size-3.5" /> : <Moon className="size-3.5" />}
          {theme === "dark" ? "LIGHT" : "DARK"}
        </button>
      </div>
    </header>
  );
}

/* -------------------------------------------------------------- chat page A */

function IndexRail() {
  return (
    <aside className="hidden min-h-0 flex-col border-e border-line bg-surface lg:flex">
      <div className="flex items-center justify-between px-4 py-3">
        <span className="da-label">索引 / INDEX</span>
        <span className="da-num text-2xs text-fg-subtle">
          {threads.length.toString().padStart(2, "0")}
        </span>
      </div>
      <Rule />
      <nav className="min-h-0 flex-1 overflow-y-auto">
        {threads.map((thread, index) => {
          const active = index === 0;
          return (
            <a
              key={thread.id}
              href="#"
              aria-current={active ? "true" : undefined}
              className={`grid grid-cols-[28px_1fr] gap-2 border-b border-line-subtle px-4 py-3 transition-colors hover:bg-hover ${
                active ? "bg-selected" : ""
              }`}
            >
              <span className="relative">
                {active ? (
                  <span aria-hidden className="absolute -start-4 top-0 h-4 w-[2px] bg-fg" />
                ) : null}
                <span
                  className={`da-num text-2xs ${active ? "text-fg" : "text-fg-subtle"}`}
                >
                  {String(index + 1).padStart(2, "0")}
                </span>
              </span>
              <span className="min-w-0">
                <span
                  className={`block truncate text-xs ${active ? "font-semibold text-fg" : "text-fg-muted"}`}
                >
                  {thread.title}
                </span>
                <span className="da-num mt-1 flex items-center gap-2 text-2xs text-fg-subtle">
                  <span>{thread.stamp}</span>
                  <span aria-hidden>·</span>
                  <span>{thread.turns} 轮</span>
                  <span aria-hidden>·</span>
                  <span>{thread.tools} 工具</span>
                </span>
              </span>
            </a>
          );
        })}
      </nav>
      <Rule />
      <div className="grid gap-1 px-4 py-3">
        <span className="da-label">今日</span>
        <span className="da-num text-2xs text-fg-muted">
          12 次运行 · 4 个待批复
        </span>
      </div>
    </aside>
  );
}

function Meter({ value, total }: { value: number; total: number }) {
  const cells = 24;
  const on = Math.round((value / total) * cells);
  return (
    <div className="da-meter" aria-hidden>
      {Array.from({ length: cells }, (_, index) => (
        <i
          key={index}
          data-on={index < on ? "1" : "0"}
          data-live={index === on - 1 ? "1" : "0"}
          style={{ height: index % 4 === 0 ? "10px" : "6px" }}
        />
      ))}
    </div>
  );
}

function InstrumentPanel() {
  return (
    <aside className="hidden min-h-0 flex-col overflow-y-auto border-s border-line bg-surface lg:flex">
      <div className="flex items-center justify-between px-4 py-3">
        <span className="da-label">仪表 / INSTRUMENT</span>
        <Gauge className="size-3.5 text-fg-subtle" />
      </div>
      <Rule />
      <div className="grid gap-4 px-4 py-4">
        <div className="grid gap-1.5">
          <div className="flex items-baseline justify-between">
            <span className="da-label">上下文</span>
            <span className="da-num text-2xs text-fg">
              {instrument.contextUsed}k / {instrument.contextMax}k
            </span>
          </div>
          <Meter value={instrument.contextUsed} total={instrument.contextMax} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <span className="da-label">工具调用</span>
            <p className="da-num mt-1 text-xl leading-none">{instrument.toolCalls}</p>
          </div>
          <div>
            <span className="da-label">耗时</span>
            <p className="da-num mt-1 text-xl leading-none">{instrument.elapsed}</p>
          </div>
          <div>
            <span className="da-label">输入</span>
            <p className="da-num mt-1 text-2xs text-fg-muted">{instrument.tokensIn}</p>
          </div>
          <div>
            <span className="da-label">输出</span>
            <p className="da-num mt-1 text-2xs text-fg-muted">{instrument.tokensOut}</p>
          </div>
        </div>
      </div>
      <Rule />
      <div className="grid gap-2 px-4 py-4">
        <div className="flex items-center justify-between">
          <span className="da-label">运行轨迹</span>
          <Activity className="size-3 text-fg-subtle" />
        </div>
        <ol className="grid gap-1.5">
          {traceLog.map((entry) => (
            <li key={entry.time} className="flex items-baseline gap-2">
              <span className="da-num text-2xs text-fg-subtle">{entry.time}</span>
              <span className="da-num truncate text-2xs text-fg-muted">{entry.text}</span>
            </li>
          ))}
        </ol>
      </div>
      <Rule />
      <div className="grid gap-2 px-4 py-4">
        <div className="flex items-center justify-between">
          <span className="da-label">待批复</span>
          <Badge tone="outline" className="da-num">
            {instrument.approvals}
          </Badge>
        </div>
        <p className="text-xs leading-relaxed text-fg-muted">
          apply_patch 需要你确认后才能写入工作区。
        </p>
        <div className="flex gap-2">
          <Button size="xs" variant="primary">
            批准
          </Button>
          <Button size="xs" variant="secondary">
            查看差异
          </Button>
        </div>
      </div>
    </aside>
  );
}

function TraceRow({ trace }: { trace: Trace }) {
  const icon =
    trace.tool === "read_file" ? (
      <FileCode2 className="size-3" />
    ) : trace.tool === "grep" ? (
      <Search className="size-3" />
    ) : trace.tool === "pytest" ? (
      <Play className="size-3" />
    ) : (
      <ShieldQuestion className="size-3" />
    );
  return (
    <li className="flex items-baseline gap-2 py-1">
      <span className="mt-0.5 text-fg-subtle">{icon}</span>
      <span className="da-num text-2xs text-fg">{trace.tool}</span>
      <span className="da-num min-w-0 flex-1 truncate text-2xs text-fg-muted">
        {trace.target}
      </span>
      <span className="da-num hidden text-2xs text-fg-subtle sm:inline">{trace.meta}</span>
      {trace.state === "waiting" ? (
        <Badge tone="warning" className="da-num">
          待批准
        </Badge>
      ) : null}
    </li>
  );
}

function ThreadA() {
  return (
    <div className="min-h-0 flex-1 overflow-y-auto bg-canvas">
      <div className="border-b border-line px-5 py-3">
        <div className="flex items-center justify-between gap-4">
          <h1 className="truncate text-sm font-semibold tracking-tight text-fg">
            {threads[0]?.title ?? ""}
          </h1>
          <span className="da-num shrink-0 text-2xs text-fg-subtle">
            THREAD 01 · 08 TURNS
          </span>
        </div>
      </div>

      {turns.map((turn) => (
        <article
          key={turn.id}
          className="grid grid-cols-1 gap-2 border-b border-line-subtle px-5 py-4 sm:grid-cols-[88px_1fr] sm:gap-5"
        >
          <div className="flex items-baseline gap-2 sm:block">
            <span className="da-num text-2xs text-fg-muted">{turn.time}</span>
            <span className={`da-label sm:mt-1 sm:block ${turn.role === "user" ? "!text-fg" : ""}`}>
              {turn.role === "user" ? "USER" : "AGENT"}
            </span>
          </div>
          <div className="min-w-0">
            {turn.role === "user" ? (
              <div className="border border-line bg-surface px-3 py-2.5 text-[16px] leading-relaxed text-fg sm:text-[14px]">
                {turn.body[0] ?? ""}
              </div>
            ) : (
              <div className="grid gap-2.5">
                {turn.body.map((paragraph, index) =>
                  paragraph.startsWith("code:") ? (
                    <pre
                      key={index}
                      className="da-num overflow-x-auto border border-line bg-sunken px-3 py-2 text-2xs leading-relaxed text-fg-muted"
                    >
                      {paragraph.slice(5)}
                    </pre>
                  ) : (
                    <p key={index} className="text-[16px] leading-[1.8] text-fg sm:text-[14px]">
                      {paragraph.split("`").map((chunk, chunkIndex) =>
                        chunkIndex % 2 === 1 ? (
                          <code
                            key={chunkIndex}
                            className="da-num border border-line-subtle bg-sunken px-1 py-px text-2xs text-fg"
                          >
                            {chunk}
                          </code>
                        ) : (
                          <span key={chunkIndex}>{chunk}</span>
                        ),
                      )}
                      {turn.streaming && index === turn.body.length - 1 ? (
                        <i className="da-caret ms-0.5" aria-hidden />
                      ) : null}
                    </p>
                  ),
                )}
                {turn.traces ? (
                  <ul className="ms-1 border-s border-line ps-3">
                    {turn.traces.map((trace) => (
                      <TraceRow key={trace.tool + trace.target} trace={trace} />
                    ))}
                  </ul>
                ) : null}
                {turn.tokens ? (
                  <span className="da-num text-2xs text-fg-subtle">{turn.tokens}</span>
                ) : null}
              </div>
            )}
          </div>
        </article>
      ))}
      <div className="h-4" />
    </div>
  );
}

function Composer() {
  return (
    <div className="shrink-0 border-t border-line bg-surface">
      <div className="flex items-start gap-3 px-4 py-3">
        <span aria-hidden className="da-num mt-1 select-none text-fg-subtle">
          &gt;
        </span>
        <Textarea
          rows={2}
          aria-label="指令"
          placeholder="给 HappyClaw 发指令 — Enter 发送 · Shift+Enter 换行"
          className="min-h-11 resize-none border-0 bg-transparent px-0 py-0 shadow-none focus-visible:shadow-none"
        />
        <div className="flex shrink-0 flex-col items-end gap-2">
          <div className="hidden items-center gap-1.5 sm:flex">
            <Kbd>⌘</Kbd>
            <Kbd>↵</Kbd>
          </div>
          <Button size="sm" variant="primary" leadingIcon={<CornerDownLeft />}>
            发送
          </Button>
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line-subtle px-4 py-1.5">
        <div className="flex flex-wrap items-center gap-3">
          <span className="da-label">MODEL {agent.model}</span>
          <span className="da-label hidden sm:inline">WORKSPACE {agent.workspace}</span>
        </div>
        <span className="da-label">CTX 26% · 3 工具可用</span>
      </div>
    </div>
  );
}

function MobileStrip() {
  return (
    <div className="flex items-center gap-2 overflow-x-auto border-b border-line bg-surface px-4 py-2 lg:hidden">
      {threads.slice(0, 3).map((thread, index) => (
        <button
          key={thread.id}
          type="button"
          className={`da-num shrink-0 border px-2 py-1 text-2xs ${
            index === 0 ? "border-fg text-fg" : "border-line text-fg-muted"
          }`}
        >
          {String(index + 1).padStart(2, "0")} {thread.title}
        </button>
      ))}
      <span className="da-label ms-auto shrink-0">1 待批复</span>
    </div>
  );
}

export function ChatDirectionA() {
  useDirectionScope("a");
  return (
    <div className="flex h-dvh min-h-0 flex-col bg-canvas text-fg">
      <TopBar />
      <div className="flex min-h-0 flex-1 flex-col lg:grid lg:grid-cols-[236px_minmax(0,1fr)_272px]">
        <IndexRail />
        <div className="flex min-h-0 flex-1 flex-col">
          <MobileStrip />
          <ThreadA />
          <Composer />
        </div>
        <InstrumentPanel />
      </div>
    </div>
  );
}

/* ------------------------------------------------------------ design page A */

function Swatch({ token, label }: { token: string; label: string }) {
  const value = useTokenValue(token);
  return (
    <div className="grid gap-1.5 border border-line-subtle bg-surface p-2">
      <div
        className="h-10 border border-line-subtle"
        style={{ background: `var(${token})` }}
        aria-hidden
      />
      <span className="da-num text-2xs text-fg">{label}</span>
      <span className="da-num text-2xs text-fg-subtle">{value}</span>
    </div>
  );
}

function SpecBlock({
  code,
  title,
  children,
}: {
  code: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="grid gap-3 border-b border-line-subtle py-4">
      <div className="flex items-baseline gap-2">
        <span className="da-num text-2xs text-fg-subtle">{code}</span>
        <h3 className="da-label !text-fg">{title}</h3>
      </div>
      <div className="flex flex-wrap items-center gap-2">{children}</div>
    </section>
  );
}

export function DesignDirectionA() {
  useDirectionScope("a");
  const push = useToastStore((state) => state.push);
  const [tab, setTab] = useState("overview");
  const [segment, setSegment] = useState<"list" | "grid">("list");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [autoApprove, setAutoApprove] = useState(true);

  return (
    <div className="flex h-dvh min-h-0 flex-col bg-canvas text-fg">
      <TopBar />
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="border-b border-line bg-surface px-5 py-6">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <span className="da-label">SPEC · v0.1</span>
              <h1 className="mt-1 text-xl font-semibold tracking-tight">
                设计系统规格表 · 方向 A 仪器
              </h1>
            </div>
            <p className="da-num max-w-md text-2xs leading-relaxed text-fg-muted">
              无彩版式 + 单一状态色；半径为 2px；所有层次由 1px 线而非阴影建立。
              以下色值为运行时从样式表读回，不是手抄。
            </p>
          </div>
        </div>

        <div className="grid gap-8 px-5 py-6 lg:grid-cols-[minmax(0,1fr)_280px]">
          <div className="min-w-0">
            <section className="grid gap-3 pb-5">
              <div className="flex items-baseline gap-2">
                <span className="da-num text-2xs text-fg-subtle">01</span>
                <h2 className="da-label !text-fg">色彩 / 角色</h2>
              </div>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
                {palette.map((swatch) => (
                  <Swatch key={swatch.name} token={swatch.token} label={swatch.name} />
                ))}
              </div>
            </section>

            <section className="grid gap-2 border-t border-line py-5">
              <div className="flex items-baseline gap-2">
                <span className="da-num text-2xs text-fg-subtle">02</span>
                <h2 className="da-label !text-fg">字阶 / TYPE</h2>
              </div>
              {typeScale.map((row) => (
                <div
                  key={row.token}
                  className="grid grid-cols-[1fr_auto] items-baseline gap-4 border-b border-line-subtle py-2"
                >
                  <div className="flex items-baseline gap-3">
                    <span className="da-num w-8 shrink-0 text-2xs text-fg-subtle">
                      {row.size}
                    </span>
                    <span
                      className="truncate text-fg"
                      style={{ fontSize: `${Number(row.size) / 16}rem` }}
                    >
                      现在在跑的是 gateway 连接池
                    </span>
                  </div>
                  <span className="da-num text-2xs text-fg-subtle">{row.use}</span>
                </div>
              ))}
            </section>

            <section className="grid gap-4 border-t border-line py-5 sm:grid-cols-3">
              <div className="grid gap-2">
                <div className="flex items-baseline gap-2">
                  <span className="da-num text-2xs text-fg-subtle">03</span>
                  <h2 className="da-label !text-fg">间距</h2>
                </div>
                {spacingScale.map((row) => (
                  <div key={row.token} className="flex items-center gap-2">
                    <span className="da-num w-6 text-2xs text-fg-subtle">{row.px}</span>
                    <span
                      className="h-2 bg-fg"
                      style={{ width: `${row.px}px` }}
                      aria-hidden
                    />
                  </div>
                ))}
              </div>
              <div className="grid gap-2">
                <div className="flex items-baseline gap-2">
                  <span className="da-num text-2xs text-fg-subtle">04</span>
                  <h2 className="da-label !text-fg">圆角</h2>
                </div>
                {radii.map((row) => (
                  <div
                    key={row.token}
                    className="flex items-center gap-2 border border-line-subtle bg-surface px-2 py-1"
                    style={{ borderRadius: `var(${row.token})` }}
                  >
                    <span className="da-num text-2xs text-fg-muted">{row.use}</span>
                  </div>
                ))}
              </div>
              <div className="grid gap-2">
                <div className="flex items-baseline gap-2">
                  <span className="da-num text-2xs text-fg-subtle">05</span>
                  <h2 className="da-label !text-fg">层次</h2>
                </div>
                <div className="da-num grid gap-1 text-2xs text-fg-muted">
                  <span>shadow-xs → none</span>
                  <span>shadow-sm → 0 0 0 1px line</span>
                  <span>shadow-md → 0 0 0 1px line</span>
                  <span>shadow-overlay → 1px + 24px blur</span>
                  <span className="mt-1 text-fg-subtle">
                    规则：面板不浮起，只用线切分。
                  </span>
                </div>
              </div>
            </section>

            <section className="grid gap-0 border-t border-line">
              <div className="flex items-baseline gap-2 py-4">
                <span className="da-num text-2xs text-fg-subtle">06</span>
                <h2 className="da-label !text-fg">组件矩阵 / COMPONENTS</h2>
              </div>

              <SpecBlock code="BTN-01" title="Button">
                <Button variant="primary" size="sm">
                  主要
                </Button>
                <Button variant="secondary" size="sm">
                  次要
                </Button>
                <Button variant="ghost" size="sm">
                  幽灵
                </Button>
                <Button variant="subtle" size="sm">
                  弱化
                </Button>
                <Button variant="danger" size="sm">
                  危险
                </Button>
                <Button variant="link" size="sm">
                  链接
                </Button>
                <Button size="sm" loading>
                  载入
                </Button>
                <Button size="icon-sm" aria-label="播放">
                  <Play />
                </Button>
              </SpecBlock>

              <SpecBlock code="INP-02" title="Input · Textarea · Select">
                <Input placeholder="搜索线程" leadingIcon={<Search />} className="max-w-52" />
                <Input placeholder="无效状态" invalid className="max-w-40" />
                <Select
                  defaultValue="fable"
                  options={[
                    { value: "fable", label: "claude-fable-5-2" },
                    { value: "sol", label: "gpt-6.2-sol" },
                  ]}
                  className="max-w-44"
                />
              </SpecBlock>

              <SpecBlock code="FRM-03" title="Field · Checkbox · Switch">
                <div className="w-56">
                  <Field label="时区" hint="取自服务端设置">
                    <Input defaultValue="Asia/Shanghai" />
                  </Field>
                </div>
                <Checkbox label="记住选择" defaultChecked />
                <Switch
                  label="自动批准读取类工具"
                  checked={autoApprove}
                  onCheckedChange={setAutoApprove}
                />
              </SpecBlock>

              <SpecBlock code="BDG-04" title="Badge · Avatar">
                <Badge tone="neutral">默认</Badge>
                <Badge tone="accent">强调</Badge>
                <Badge tone="success" dot>
                  运行中
                </Badge>
                <Badge tone="warning">待批准</Badge>
                <Badge tone="danger">失败</Badge>
                <Badge tone="outline">outline</Badge>
                <span className="flex items-center gap-1.5">
                  <Avatar name="HappyClaw" size="xs" />
                  <Avatar name="开心爸爸" size="sm" />
                  <Avatar name="xkx121029" size="md" />
                </span>
              </SpecBlock>

              <SpecBlock code="CRD-05" title="Card · Stat">
                <div className="grid w-full gap-2 sm:grid-cols-3">
                  <Stat label="今日运行" value="12" delta={{ value: "+3 较昨日", tone: "up" }} />
                  <Card className="p-3">
                    <CardHeader title="上下文" description="8.4k / 32k" className="border-b-0 px-0 pt-0" />
                    <Progress value={26} label="上下文占用" />
                  </Card>
                  <Card className="grid gap-2 p-3">
                    <CardBody className="p-0 text-xs text-fg-muted">
                      卡片只做容器，不加阴影。
                    </CardBody>
                    <CardFooter className="justify-start border-t-0 px-0 pb-0 pt-2">
                      <Button size="xs" variant="secondary">
                        查看
                      </Button>
                    </CardFooter>
                  </Card>
                </div>
              </SpecBlock>

              <SpecBlock code="ALT-06" title="Alert">
                <div className="grid w-full gap-2">
                  <Alert tone="info" title="提示">
                    取消异常会绕过 release()，这是本次泄漏的根因。
                  </Alert>
                  <Alert tone="warning" title="需要确认" action={<Button size="xs">批准</Button>}>
                    apply_patch 有 3 处改动待写入。
                  </Alert>
                </div>
              </SpecBlock>

              <SpecBlock code="EMP-07" title="EmptyState">
                <div className="w-full border border-dashed border-line">
                  <EmptyState
                    size="sm"
                    icon={<FileCode2 />}
                    title="还没有线程"
                    description="从侧栏开始一个会话，或让它自己跑一个定时任务。"
                    action={
                      <Button size="xs" variant="secondary">
                        新建
                      </Button>
                    }
                  />
                </div>
              </SpecBlock>

              <SpecBlock code="LOD-08" title="Spinner · Skeleton">
                <Spinner size="sm" />
                <div className="w-40">
                  <SkeletonText lines={2} />
                </div>
                <div className="w-40">
                  <Skeleton className="h-4 w-full" />
                </div>
                <div className="w-52">
                  <SkeletonList rows={2} />
                </div>
                <div className="w-32">
                  <LoadingBlock label="载入中" />
                </div>
              </SpecBlock>

              <SpecBlock code="PRG-09" title="Progress">
                <div className="grid w-full gap-2">
                  <Progress value={26} label="上下文" />
                  <Progress value={64} tone="success" label="任务" />
                  <Progress value={88} tone="warning" label="配额" />
                </div>
              </SpecBlock>

              <SpecBlock code="TAB-10" title="Tabs · Segmented">
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
              </SpecBlock>

              <SpecBlock code="OVL-11" title="Dialog · DropdownMenu · Tooltip">
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
              </SpecBlock>

              <SpecBlock code="TBL-12" title="Table">
                <div className="w-full border border-line">
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
                          <TD className="da-num">{row.key}</TD>
                          <TD>{row.scope}</TD>
                          <TD className="da-num">{row.cost}</TD>
                          <TD>{row.state}</TD>
                        </TR>
                      ))}
                    </TBody>
                  </Table>
                </div>
              </SpecBlock>

              <SpecBlock code="DEL-13" title="Separator · Kbd · Toaster">
                <div className="flex w-full items-center gap-3">
                  <span className="da-label">上方</span>
                  <Separator />
                  <span className="da-label">下方</span>
                </div>
                <Kbd>⌘</Kbd>
                <Kbd>K</Kbd>
                <Button
                  size="sm"
                  onClick={() =>
                    push({ tone: "success", title: "已复制", description: "线程 ID 写入剪贴板" })
                  }
                >
                  触发 Toast
                </Button>
              </SpecBlock>
            </section>
          </div>

          <aside className="grid content-start gap-4 border-s border-line ps-5">
            <div className="grid gap-1.5">
              <span className="da-label">规格摘要</span>
              <p className="da-num text-2xs leading-relaxed text-fg-muted">
                底 13.5px / 行高 1.8
                <br />
                标题 20px / 字距 −0.01em
                <br />
                分隔 1px / 圆角 2px
                <br />
                彩色仅用于状态与焦点
              </p>
            </div>
            <Rule />
            <div className="grid gap-1.5">
              <span className="da-label">校验</span>
              <p className="text-2xs leading-relaxed text-fg-muted">
                正文对比度 ≥ 4.5:1；手机断点 390×844 下索引栏与仪表栏折叠为顶部条与抽屉。
              </p>
            </div>
            <Rule />
            <div className="grid gap-1.5">
              <span className="da-label">代价</span>
              <p className="text-2xs leading-relaxed text-fg-muted">
                空态显得空；没有装饰替内容兜底，密度必须靠真实数据撑起来。
              </p>
            </div>
          </aside>
        </div>
      </div>

      <Dialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        title="删除线程"
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
        <p className="da-num text-2xs text-fg-muted">THREAD 01 · 08 TURNS · 12 TOOLS</p>
      </Dialog>
      <Toaster />
    </div>
  );
}
