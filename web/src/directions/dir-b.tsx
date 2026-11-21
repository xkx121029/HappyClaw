import {
  BookOpen,
  Check,
  ChevronsUpDown,
  Feather,
  FileCode2,
  Moon,
  Play,
  Search,
  ShieldQuestion,
  Sun,
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

const CN_NUMERALS = ["一", "二", "三", "四", "五", "六", "七", "八"];

/* ------------------------------------------------------------------ chrome */

function Colophon({ label, value }: { label: string; value: string }) {
  return (
    <span className="db-note-label normal-case tracking-[0.08em]">
      {label} <span className="text-fg-muted">{value}</span>
    </span>
  );
}

function TopBar({ section }: { section: string }) {
  const { theme, toggleTheme } = useThemeToggle();
  return (
    <header className="flex h-[52px] shrink-0 items-center justify-between border-b border-line bg-surface px-5 sm:px-8">
      <div className="flex min-w-0 items-center gap-3">
        <span aria-hidden className="db-seal size-6 text-xs">
          爪
        </span>
        <span className="db-note-label !text-fg">HAPPYCLAW</span>
        <span aria-hidden className="h-3 w-px bg-line-strong" />
        <span className="db-serif truncate text-sm text-fg-muted">{section}</span>
      </div>
      <div className="flex items-center gap-4">
        <span className="hidden font-serif text-xs text-fg-subtle sm:inline">2026 年 11 月 21 日</span>
        <button
          type="button"
          onClick={() => void toggleTheme()}
          className="db-note-label inline-flex items-center gap-1.5 hover:text-fg"
        >
          {theme === "dark" ? <Sun className="size-3.5" /> : <Moon className="size-3.5" />}
          {theme === "dark" ? "日读" : "夜读"}
        </button>
      </div>
    </header>
  );
}

/* -------------------------------------------------------------- chat page B */

function Contents() {
  return (
    <aside className="hidden min-h-0 flex-col border-e border-line bg-surface lg:flex">
      <div className="flex items-baseline justify-between px-6 pb-3 pt-5">
        <span className="db-note-label">目 录</span>
        <span className="db-serif text-2xs text-fg-subtle">共五则</span>
      </div>
      <div className="db-rule mx-6" />
      <nav className="min-h-0 flex-1 overflow-y-auto">
        <ol>
          {threads.map((thread, index) => {
            const active = index === 0;
            return (
              <li key={thread.id} className="db-rule-dotted mx-6 first:border-t-0">
                <a href="#" aria-current={active ? "true" : undefined} className="grid grid-cols-[26px_1fr] gap-2 py-3">
                  <span
                    className={`db-serif text-sm ${active ? "text-accent-fg" : "text-fg-subtle"}`}
                  >
                    {CN_NUMERALS[index]}
                  </span>
                  <span className="min-w-0">
                    <span
                      className={`db-serif block text-[15px] leading-snug ${
                        active ? "font-semibold text-fg" : "text-fg-muted"
                      }`}
                    >
                      {thread.title}
                    </span>
                    <span className="db-note-label mt-1 flex items-center gap-1.5 normal-case">
                      <span>{thread.stamp}</span>
                      <span aria-hidden>·</span>
                      <span>{thread.turns} 轮</span>
                      {thread.state === "running" ? (
                        <span className="text-accent-fg">· 在写</span>
                      ) : null}
                    </span>
                  </span>
                </a>
              </li>
            );
          })}
        </ol>
      </nav>
      <div className="db-rule mx-6" />
      <div className="flex items-center gap-2.5 px-6 py-4">
        <span aria-hidden className="db-seal size-5 text-xs">
          稿
        </span>
        <span className="db-note-label normal-case">
          今日 {threads.length} 则 · {instrument.toolCalls} 次查证
        </span>
      </div>
    </aside>
  );
}

function TraceNote({ trace, index }: { trace: Trace; index: number }) {
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
    <div className="grid gap-1">
      <span className="db-note-label normal-case tracking-[0.1em]">
        注 {String(index + 1).padStart(2, "0")}
      </span>
      <span className="flex items-center gap-1.5 text-xs text-fg">
        <span className="text-fg-subtle">{icon}</span>
        <span className="font-medium">{trace.tool}</span>
        {trace.state === "waiting" ? (
          <span className="text-accent-fg">· 待批准</span>
        ) : null}
      </span>
      <span className="break-all text-2xs leading-relaxed text-fg-subtle">
        {trace.target}
      </span>
      <span className="text-2xs text-fg-subtle">{trace.meta}</span>
    </div>
  );
}

function ThreadB() {
  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <article className="db-paper mx-auto w-full max-w-[1010px] px-5 pb-10 pt-6 sm:px-10 sm:pt-8">
        <div className="flex items-baseline justify-between gap-4 border-b border-line pb-2">
          <Colophon label="本机主机" value={agent.role} />
          <Colophon label="会话" value="壹 · 进行中" />
        </div>

        <div className="mx-auto w-full max-w-[880px]">
        <h1 className="db-chapter mt-7 text-2xl leading-snug text-fg sm:text-[1.75rem]">
          {threads[0]?.title ?? ""}
        </h1>
        <div className="mt-3 h-[2px] w-9 bg-accent" aria-hidden />
        <p className="db-note-label mt-3 normal-case tracking-[0.1em]">
          八轮 · 十二次查证 · 用时 3 分 41 秒 · 模型 {agent.model}
        </p>

        <div className="mt-8 grid gap-9">
          {turns.map((turn, turnIndex) => (
            <section
              key={turn.id}
              className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_180px] lg:gap-10"
            >
              <div className="min-w-0">
                {turn.role === "user" ? (
                  <div className="border-s-2 border-accent bg-inset px-4 py-3">
                    <span className="db-note-label normal-case tracking-[0.12em] !text-accent-fg">
                      我 · {turn.time}
                    </span>
                    <p className="mt-1.5 text-[15px] leading-relaxed text-fg sm:text-[14px]">{turn.body[0] ?? ""}</p>
                  </div>
                ) : (
                  <div className="grid gap-3">
                    <span className="db-note-label normal-case tracking-[0.12em]">
                      HappyClaw 写道
                    </span>
                    {turn.body.map((paragraph, index) =>
                      paragraph.startsWith("code:") ? (
                        <pre
                          key={index}
                          className="overflow-x-auto border border-line bg-sunken px-4 py-3 font-mono text-2xs leading-relaxed text-fg-muted"
                        >
                          {paragraph.slice(5)}
                        </pre>
                      ) : (
                        <p
                          key={index}
                          className={`db-reading text-fg ${turnIndex === 1 && index === 0 ? "db-drop" : ""}`}
                        >
                          {paragraph.split("`").map((chunk, chunkIndex) =>
                            chunkIndex % 2 === 1 ? (
                              <code
                                key={chunkIndex}
                                className="border-b border-line-strong bg-transparent px-0.5 font-mono text-[0.82em] text-accent-fg"
                              >
                                {chunk}
                              </code>
                            ) : (
                              <span key={chunkIndex}>{chunk}</span>
                            ),
                          )}
                          {turn.streaming && index === turn.body.length - 1 ? (
                            <span className="db-serif text-accent" aria-hidden>
                              {" "}
                              ▍
                            </span>
                          ) : null}
                        </p>
                      ),
                    )}
                    {turn.tokens ? (
                      <span className="db-note-label normal-case">{turn.tokens}</span>
                    ) : null}
                  </div>
                )}
              </div>

              <aside className="min-w-0 border-t border-dotted border-line-strong pt-2 lg:border-t-0 lg:pt-1">
                {turn.traces ? (
                  <div className="grid gap-3">
                    {turn.traces.map((trace, index) => (
                      <TraceNote key={trace.tool + trace.target} trace={trace} index={index} />
                    ))}
                  </div>
                ) : turn.role === "user" ? (
                  <div className="grid gap-1">
                    <span className="db-note-label normal-case tracking-[0.1em]">旁注</span>
                    <span className="text-2xs leading-relaxed text-fg-subtle">
                      十六分钟前，同一个问题在旧前端上被问过一次。
                    </span>
                  </div>
                ) : null}
              </aside>
            </section>
          ))}
        </div>

        <div className="mt-10 flex items-center justify-between border-t border-line pt-3">
          <Colophon label="卷末" value="4 / 4 段" />
          <span className="db-note-label">— 待续 —</span>
        </div>
        </div>
      </article>
    </div>
  );
}

function ComposerB() {
  return (
    <div className="shrink-0 border-t border-line bg-surface">
      <div className="mx-auto w-full max-w-[1010px] px-5 py-3 sm:px-10">
        <div className="flex items-baseline justify-between">
          <span className="db-note-label normal-case tracking-[0.12em]">续写 · 第四段</span>
          <span className="db-note-label hidden normal-case sm:inline">ENTER 发送 · SHIFT + ENTER 换行</span>
        </div>
        <Textarea
          rows={2}
          aria-label="续写"
          placeholder="写下你要它做的事…"
          className="mt-1 min-h-10 resize-none border-0 bg-transparent px-0 py-1 font-serif text-md leading-relaxed shadow-none focus-visible:shadow-none"
        />
        <div className="mt-2 flex items-center justify-between border-t border-line-subtle pt-2">
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              className="db-note-label inline-flex items-center gap-1 normal-case hover:text-fg"
            >
              {agent.model}
              <ChevronsUpDown className="size-3" />
            </button>
            <span className="db-note-label normal-case">工具 3 项可用</span>
          </div>
          <div className="flex items-center gap-3">
            <Kbd>⌘</Kbd>
            <button type="button" className="db-seal size-9 text-base">
              发
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export function ChatDirectionB() {
  useDirectionScope("b");
  return (
    <div className="flex h-dvh min-h-0 flex-col bg-canvas text-fg">
      <TopBar section="对话 · 壹" />
      <div className="flex min-h-0 flex-1">
        <Contents />
        <div className="flex min-h-0 flex-1 flex-col">
          <div className="flex items-center gap-2 overflow-x-auto border-b border-line bg-surface px-5 py-2 lg:hidden">
            {threads.slice(0, 3).map((thread, index) => (
              <button
                key={thread.id}
                type="button"
                className={`db-serif shrink-0 border-b-2 px-1 pb-1 text-xs ${
                  index === 0
                    ? "border-accent text-fg"
                    : "border-transparent text-fg-subtle"
                }`}
              >
                {CN_NUMERALS[index]} {thread.title}
              </button>
            ))}
          </div>
          <ThreadB />
          <ComposerB />
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------ design page B */

function SpecRow({
  index,
  name,
  tokens,
  children,
}: {
  index: number;
  name: string;
  tokens: string;
  children: React.ReactNode;
}) {
  return (
    <section className="grid gap-3 border-t border-dotted border-line-strong py-4 lg:grid-cols-[168px_minmax(0,1fr)] lg:gap-8">
      <div className="grid content-start gap-1">
        <span className="db-note-label normal-case tracking-[0.1em]">
          {String(index).padStart(2, "0")} · {name}
        </span>
        <span className="font-mono text-[0.65rem] leading-relaxed text-fg-subtle">{tokens}</span>
      </div>
      <div className="flex flex-wrap items-center gap-2.5">{children}</div>
    </section>
  );
}

function Chapter({
  numeral,
  title,
  lead,
}: {
  numeral: string;
  title: string;
  lead: string;
}) {
  return (
    <div className="grid grid-cols-[auto_minmax(0,1fr)] items-start gap-4 pb-2 pt-8">
      <span className="db-serif text-3xl leading-none text-fg-subtle">{numeral}</span>
      <div>
        <h2 className="db-chapter text-xl text-fg">{title}</h2>
        <p className="mt-1 text-xs leading-relaxed text-fg-subtle">{lead}</p>
        <div className="mt-2 h-[2px] w-8 bg-accent" aria-hidden />
      </div>
    </div>
  );
}

function SwatchRow({ token, label }: { token: string; label: string }) {
  const value = useTokenValue(token);
  return (
    <div className="grid grid-cols-[28px_auto_1fr] items-center gap-2 border-b border-dotted border-line py-1.5">
      <span
        className="size-6 border border-line"
        style={{ background: `var(${token})` }}
        aria-hidden
      />
      <span className="db-serif text-xs text-fg">{label}</span>
      <span className="text-right font-mono text-[0.65rem] text-fg-subtle">{value}</span>
    </div>
  );
}

export function DesignDirectionB() {
  useDirectionScope("b");
  const push = useToastStore((state) => state.push);
  const [tab, setTab] = useState("overview");
  const [segment, setSegment] = useState<"list" | "grid">("list");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [autoApprove, setAutoApprove] = useState(true);

  return (
    <div className="flex h-dvh min-h-0 flex-col bg-canvas text-fg">
      <TopBar section="设计系统 · 版式样本" />
      <div className="min-h-0 flex-1 overflow-y-auto">
        <article className="db-paper mx-auto w-full max-w-[1010px] px-5 pb-16 pt-6 sm:px-10">
          <div className="flex items-baseline justify-between gap-4 border-b border-line pb-2">
            <Colophon label="样本" value="方向 B · 读本" />
            <Colophon label="版心" value="640 px / 行距 1.95" />
          </div>

          <h1 className="db-chapter mt-7 text-2xl leading-snug sm:text-[1.75rem]">
            一册设计系统：色、字、距、件
          </h1>
          <div className="mt-3 h-[2px] w-9 bg-accent" aria-hidden />
          <p className="db-reading db-drop mt-5 text-fg">
            这一版把界面当书排。目录在左，正文在中间一条六百四十像素的版心内，
            工具调用退到旁注栏里，像脚注一样只在需要时被读到，而不是每句话都配一张卡片。
            朱砂是唯一的有彩色，一屏只用一处：当前那一则、那一条线。
          </p>

          <Chapter
            numeral="壹"
            title="色"
            lead="暖纸底、墨色正文，朱砂一枚。以下色值从样式表实时读回。"
          />
          <div className="grid gap-x-10 sm:grid-cols-2">
            {palette.map((swatch) => (
              <SwatchRow key={swatch.name} token={swatch.token} label={swatch.name} />
            ))}
          </div>

          <Chapter numeral="贰" title="字" lead="正文思源宋体，界面部件留给无衬线；数字用宋体等宽对齐。" />
          <div className="grid gap-1.5">
            {typeScale.map((row) => (
              <div
                key={row.token}
                className="grid grid-cols-[44px_minmax(0,1fr)_auto] items-baseline gap-3 border-b border-dotted border-line py-1.5"
              >
                <span className="font-mono text-[0.65rem] text-fg-subtle">{row.size}</span>
                <span className="db-serif truncate" style={{ fontSize: `${Number(row.size) / 16}rem` }}>
                  现在在跑的是 gateway 连接池
                </span>
                <span className="hidden text-2xs text-fg-subtle sm:inline">{row.use}</span>
              </div>
            ))}
          </div>

          <Chapter numeral="叁" title="距" lead="留白是构图，不是内容缺席：天头小、地脚大，行距近两倍。" />
          <div className="grid gap-6 sm:grid-cols-3">
            <div className="grid gap-1.5">
              <span className="db-note-label">间距</span>
              {spacingScale.map((row) => (
                <div key={row.token} className="flex items-center gap-2">
                  <span className="w-6 font-mono text-[0.65rem] text-fg-subtle">{row.px}</span>
                  <span className="h-1.5 bg-fg" style={{ width: `${row.px}px` }} aria-hidden />
                </div>
              ))}
            </div>
            <div className="grid gap-1.5">
              <span className="db-note-label">圆角</span>
              {radii.map((row) => (
                <div
                  key={row.token}
                  className="border border-line bg-surface px-2 py-1 text-xs text-fg-muted"
                  style={{ borderRadius: `var(${row.token})` }}
                >
                  {row.use}
                </div>
              ))}
            </div>
            <div className="grid content-start gap-1.5">
              <span className="db-note-label">层次</span>
              <p className="text-xs leading-relaxed text-fg-muted">
                不用投影。封面的凸起交给纸色差与一条细线；浮层是唯一允许离开纸面的东西，
                它才带阴影。
              </p>
            </div>
          </div>

          <Chapter numeral="肆" title="件" lead="二十个组件落在版心与旁注里，同一套节奏。" />

          <SpecRow index={1} name="Btn" tokens="primary / secondary / ghost / danger">
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
          </SpecRow>

          <SpecRow index={2} name="Input" tokens="input / textarea / select / field">
            <Input placeholder="搜索" leadingIcon={<Search />} className="max-w-48" />
            <Input placeholder="无效" invalid className="max-w-32" />
            <Select
              defaultValue="fable"
              options={[
                { value: "fable", label: "claude-fable-5-2" },
                { value: "sol", label: "gpt-6.2-sol" },
              ]}
              className="max-w-44"
            />
            <div className="w-52">
              <Field label="时区" hint="取自服务端设置">
                <Input defaultValue="Asia/Shanghai" />
              </Field>
            </div>
          </SpecRow>

          <SpecRow index={3} name="Toggle" tokens="checkbox / switch">
            <Checkbox label="记住选择" defaultChecked />
            <Switch label="自动批准读取类工具" checked={autoApprove} onCheckedChange={setAutoApprove} />
          </SpecRow>

          <SpecRow index={4} name="Mark" tokens="badge / avatar">
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
          </SpecRow>

          <SpecRow index={5} name="Box" tokens="card / stat / progress">
            <Stat label="今日运行" value="12" delta={{ value: "+3 较昨日", tone: "up" }} />
            <Card className="w-52 p-3">
              <CardHeader title="上下文" description="8.4k / 32k" className="border-b-0 px-0 pt-0" />
              <Progress value={26} label="上下文" />
            </Card>
            <Card className="grid w-52 gap-2 p-3">
              <CardBody className="p-0 text-xs text-fg-muted">卡片是书页上的一小块专栏。</CardBody>
              <CardFooter className="justify-start border-t-0 px-0 pb-0 pt-1">
                <Button size="xs" variant="secondary">
                  查看
                </Button>
              </CardFooter>
            </Card>
          </SpecRow>

          <SpecRow index={6} name="Note" tokens="alert / empty-state">
            <div className="grid w-full gap-2">
              <Alert tone="info" title="提示">
                取消异常会绕过 release()，这是本次泄漏的根因。
              </Alert>
              <Alert tone="warning" title="需要确认" action={<Button size="xs">批准</Button>}>
                apply_patch 有 3 处改动待写入。
              </Alert>
              <div className="border border-dashed border-line">
                <EmptyState
                  size="sm"
                  icon={<BookOpen />}
                  title="这一则还没有内容"
                  description="写下第一段，或者让它先自己查一遍。"
                  action={
                    <Button size="xs" variant="secondary">
                      起稿
                    </Button>
                  }
                />
              </div>
            </div>
          </SpecRow>

          <SpecRow index={7} name="Wait" tokens="spinner / skeleton / loading-block">
            <Spinner size="sm" />
            <div className="w-40">
              <SkeletonText lines={2} />
            </div>
            <div className="w-40">
              <Skeleton className="h-4 w-full" />
            </div>
            <div className="w-48">
              <SkeletonList rows={2} />
            </div>
            <div className="w-28">
              <LoadingBlock label="载入中" />
            </div>
          </SpecRow>

          <SpecRow index={8} name="Tab" tokens="tabs / segmented">
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
          </SpecRow>

          <SpecRow index={9} name="Overlay" tokens="dialog / dropdown / tooltip">
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
          </SpecRow>

          <SpecRow index={10} name="Grid" tokens="table">
            <div className="w-full border-t border-line">
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
                      <TD>{row.state}</TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            </div>
          </SpecRow>

          <SpecRow index={11} name="Rule" tokens="separator / kbd / toaster">
            <div className="flex w-full items-center gap-3">
              <span className="db-note-label">上</span>
              <Separator />
              <span className="db-note-label">下</span>
            </div>
            <Kbd>⌘</Kbd>
            <Kbd>K</Kbd>
            <Button
              size="sm"
              onClick={() => push({ tone: "success", title: "已记下", description: "这一则写入草稿" })}
            >
              触发 Toast
            </Button>
          </SpecRow>

          <div className="mt-10 flex items-center justify-between border-t border-line pt-3">
            <Colophon label="卷末" value="HappyClaw 设计系统 · 方向 B" />
            <span className="inline-flex items-center gap-1.5 db-note-label">
              <Feather className="size-3" /> 待你选定
            </span>
          </div>
        </article>
      </div>

      <Dialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        title="删除这一则"
        description="这一页会从目录里消失，历史记录不可找回。"
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
