import { useMemo, useState, type ReactNode } from "react";
import { Button, Input, Tag } from "antd";
import {
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
  ChevronDown,
  CircleHelp,
  Inbox,
  RefreshCw,
  Send,
  ShieldQuestion,
  Smartphone,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import AskQuestionCard from "../Chat/components/AskQuestionCard";
import { BeamCardReveal, useNewIds } from "../../motion";
import { isOpen, type InboxItem, type InboxCounts } from "./homeInboxModel";
import styles from "./Home.module.less";

type FilterKey = "all" | "pairing" | "question" | "task";

interface InboxPanelProps {
  items: InboxItem[];
  counts: InboxCounts;
  loading: boolean;
  error: string | null;
  now: number;
  relativeTime: (at: number, now: number) => string;
  onRefresh: () => void;
  onApprove: (item: InboxItem) => Promise<void>;
  onReject: (item: InboxItem) => Promise<void>;
  onAnswer: (item: InboxItem, message: string) => Promise<void>;
  onAck: (item: InboxItem) => Promise<void>;
  onFollowUp: (item: InboxItem, text: string) => Promise<void>;
  onOpenThread: (item: InboxItem) => void;
}

function stateLabelKey(item: InboxItem): string {
  if (item.state === "expired" && item.source === "task") {
    return "home.inbox.state.acknowledged";
  }
  return `home.inbox.state.${item.state}`;
}

function StateTag({ item }: { item: InboxItem }) {
  const { t } = useTranslation();
  return (
    <Tag
      className={styles.inboxStateTag}
      color={isOpen(item) ? "processing" : undefined}
    >
      {t(stateLabelKey(item))}
    </Tag>
  );
}

export default function InboxPanel({
  items,
  counts,
  loading,
  error,
  now,
  relativeTime,
  onRefresh,
  onApprove,
  onReject,
  onAnswer,
  onAck,
  onFollowUp,
  onOpenThread,
}: InboxPanelProps) {
  const { t } = useTranslation();
  const [filter, setFilter] = useState<FilterKey>("all");
  // Handled rows stay visible by default: acting on a card must update it in
  // place, not make the context disappear from the inbox.
  const [showHandled, setShowHandled] = useState(true);
  const [busyKey, setBusyKey] = useState<string | null>(null);

  const run = async (key: string, action: () => Promise<void>) => {
    setBusyKey(key);
    try {
      await action();
    } finally {
      setBusyKey(null);
    }
  };

  const visible = useMemo(
    () =>
      items.filter((item) => {
        if (!showHandled && !isOpen(item)) return false;
        if (filter === "all") return true;
        if (filter === "question") {
          return item.source === "question" || item.source === "approval";
        }
        return item.source === filter;
      }),
    [filter, items, showHandled],
  );

  // 新到达的提问卡片用光束出场；首次载入的历史列表不播。
  const questionKeys = useMemo(
    () =>
      items
        .filter((item) => item.source === "question")
        .map((item) => item.key),
    [items],
  );
  const freshQuestions = useNewIds(questionKeys, undefined, 1);

  const filters: Array<{ key: FilterKey; label: string; count: number }> = [
    { key: "all", label: t("home.inbox.filter.all"), count: counts.total },
    { key: "pairing", label: t("home.inbox.filter.pairing"), count: counts.pairing },
    {
      key: "question",
      label: t("home.inbox.filter.question"),
      count: counts.question + counts.approval,
    },
    { key: "task", label: t("home.inbox.filter.task"), count: counts.task },
  ];

  return (
    <section className={styles.inbox}>
      <header className={styles.inboxHead}>
        <div className={styles.inboxTitleRow}>
          <span className={styles.inboxMark}>
            <Inbox size={17} strokeWidth={1.9} />
          </span>
          <div>
            <h2 className={styles.inboxTitle}>{t("home.inbox.title")}</h2>
            <p className={styles.inboxSubtitle}>
              {counts.total > 0
                ? t("home.inbox.subtitle", { count: counts.total })
                : t("home.inbox.subtitleClear")}
            </p>
          </div>
          <Button
            size="small"
            type="text"
            icon={<RefreshCw size={14} strokeWidth={1.8} />}
            loading={loading}
            onClick={onRefresh}
            aria-label={t("home.inbox.refresh")}
          />
        </div>
        <div className={styles.inboxFilters}>
          <div className={styles.inboxFilterGroup}>
            {filters.map((entry) => (
              <button
                key={entry.key}
                type="button"
                className={styles.inboxFilter}
                data-active={filter === entry.key}
                onClick={() => setFilter(entry.key)}
              >
                {entry.label}
                <span className={styles.inboxFilterCount}>
                  {entry.count}
                </span>
              </button>
            ))}
          </div>
          <label className={styles.inboxHandledToggle}>
            <input
              type="checkbox"
              checked={showHandled}
              onChange={(event) => setShowHandled(event.target.checked)}
            />
            <span>{t("home.inbox.filter.showHandled")}</span>
          </label>
        </div>
      </header>

      {error && (
        <div className={styles.inboxBanner}>
          <AlertTriangle size={14} strokeWidth={1.9} />
          <span>{error}</span>
        </div>
      )}

      <div className={styles.inboxList}>
        {visible.length === 0 && !loading && (
          <div className={styles.inboxEmpty}>
            <CheckCircle2 size={22} strokeWidth={1.6} />
            <p>{t("home.inbox.empty")}</p>
            <span>{t("home.inbox.emptyHint")}</span>
          </div>
        )}

        {visible.map((item) => {
          if (item.source === "pairing") {
            return (
              <PairingCard
                key={item.key}
                item={item}
                busy={busyKey === item.key}
                now={now}
                relativeTime={relativeTime}
                onApprove={() => run(item.key, () => onApprove(item))}
                onReject={() => run(item.key, () => onReject(item))}
              />
            );
          }
          if (item.source === "task") {
            return (
              <TaskCard
                key={item.key}
                item={item}
                busy={busyKey === item.key}
                relativeTime={relativeTime}
                onAck={() => run(item.key, () => onAck(item))}
                onFollowUp={(text) => run(item.key, () => onFollowUp(item, text))}
                onOpen={() => onOpenThread(item)}
              />
            );
          }
          if (item.source === "approval") {
            return (
              <ApprovalCard
                key={item.key}
                item={item}
                relativeTime={relativeTime}
                onOpen={() => onOpenThread(item)}
              />
            );
          }
          const questionCard = (
            <QuestionCard
              key={item.key}
              item={item}
              busy={busyKey === item.key}
              relativeTime={relativeTime}
              onAnswer={(message) => run(item.key, () => onAnswer(item, message))}
            />
          );
          // 刚到达的提问：从活动核心射出一束光，铺开后收拢成卡片。
          return freshQuestions.has(item.key) ? (
            <BeamCardReveal key={item.key} open>
              {questionCard}
            </BeamCardReveal>
          ) : (
            questionCard
          );
        })}
      </div>
    </section>
  );
}

function CardHead({
  item,
  icon,
  label,
}: {
  item: InboxItem;
  icon: ReactNode;
  label: string;
}) {
  const { t } = useTranslation();
  return (
    <div className={styles.cardHead}>
      <span className={styles.cardIcon} data-source={item.source}>
        {icon}
      </span>
      <div className={styles.cardHeadText}>
        <span className={styles.cardKind}>{label}</span>
        <span className={styles.cardContext}>
          {item.agentName || item.agentId || t("home.inbox.system")}
          {item.sessionTitle ? ` · ${item.sessionTitle}` : ""}
        </span>
      </div>
      <StateTag item={item} />
    </div>
  );
}

function PairingCard({
  item,
  busy,
  now,
  relativeTime,
  onApprove,
  onReject,
}: {
  item: InboxItem;
  busy: boolean;
  now: number;
  relativeTime: (at: number, now: number) => string;
  onApprove: () => void;
  onReject: () => void;
}) {
  const { t } = useTranslation();
  const request = item.pairing;
  if (!request) return null;
  const remaining = request.expiresAtMs ? request.expiresAtMs - now : 0;
  const expired = remaining <= 0;
  const minutes = Math.max(0, Math.ceil(remaining / 60_000));

  return (
    <article className={styles.card} data-state={item.state} data-source="pairing">
      <CardHead
        item={item}
        icon={<Smartphone size={16} strokeWidth={1.8} />}
        label={t("home.inbox.pairing.label")}
      />
      <div className={styles.cardBody}>
        <div className={styles.cardTitleRow}>
          <h3 className={styles.cardTitle}>
            {request.deviceName || t("home.inbox.pairing.unknownDevice")}
          </h3>
          <code className={styles.pairCode}>{request.code}</code>
        </div>
        <p className={styles.cardMeta}>
          {request.platform || "—"}
          {request.appVersion ? ` · v${request.appVersion}` : ""}
          <span className={styles.metaDivider}>·</span>
          {relativeTime(request.createdAtMs, now)}
          <span className={styles.metaDivider}>·</span>
          <span data-danger={expired}>
            {expired
              ? t("home.inbox.pairing.expired")
              : t("home.inbox.pairing.expiresIn", { count: minutes })}
          </span>
        </p>
        {item.error && <p className={styles.cardError}>{item.error}</p>}
        {isOpen(item) ? (
          <div className={styles.cardActions}>
            <Button
              type="primary"
              size="small"
              loading={busy}
              disabled={expired}
              onClick={onApprove}
            >
              {t("home.inbox.pairing.approve")}
            </Button>
            <Button size="small" disabled={busy} onClick={onReject}>
              {t("home.inbox.pairing.reject")}
            </Button>
          </div>
        ) : (
          <p className={styles.cardResolution}>
            {t("home.inbox.pairing.resolvedHint")}
          </p>
        )}
      </div>
    </article>
  );
}

function QuestionCard({
  item,
  busy,
  relativeTime,
  onAnswer,
}: {
  item: InboxItem;
  busy: boolean;
  relativeTime: (at: number, now: number) => string;
  onAnswer: (message: string) => void;
}) {
  const { t } = useTranslation();
  const questions = item.questions ?? [];
  const pending = isOpen(item);

  return (
    <article className={styles.card} data-state={item.state} data-source="question">
      <CardHead
        item={item}
        icon={<CircleHelp size={16} strokeWidth={1.8} />}
        label={t("home.inbox.question.label")}
      />
      <div className={styles.cardBody}>
        <div className={styles.cardTitleRow}>
          <h3 className={styles.cardTitle}>
            {questions[0]?.question || t("home.inbox.question.fallback")}
          </h3>
          <span className={styles.cardTime}>
            {relativeTime(item.createdAt, Date.now())}
          </span>
        </div>
        {pending ? (
          <div className={styles.askWrap} data-busy={busy}>
            <AskQuestionCard
              key={`${item.key}:${item.error ?? "ok"}`}
              questions={questions}
              status="pending"
              onSubmit={onAnswer}
            />
          </div>
        ) : (
          <div className={styles.answerBox}>
            {questions.map((question, index) => (
              <p key={`${item.key}:q:${index}`} className={styles.answerQuestion}>
                {question.question}
              </p>
            ))}
            <p className={styles.answerText}>
              <span>{t("home.inbox.question.answerLabel")}</span>
              {item.answer || t("home.inbox.question.answeredShort")}
            </p>
            {item.error && <p className={styles.cardError}>{item.error}</p>}
          </div>
        )}
      </div>
    </article>
  );
}

function ApprovalCard({
  item,
  relativeTime,
  onOpen,
}: {
  item: InboxItem;
  relativeTime: (at: number, now: number) => string;
  onOpen: () => void;
}) {
  const { t } = useTranslation();
  return (
    <article className={styles.card} data-state={item.state} data-source="approval">
      <CardHead
        item={item}
        icon={<ShieldQuestion size={16} strokeWidth={1.8} />}
        label={t("home.inbox.question.approvalTitle")}
      />
      <div className={styles.cardBody}>
        <p className={styles.cardMeta}>
          {relativeTime(item.createdAt, Date.now())}
          <span className={styles.metaDivider}>·</span>
          {t("home.inbox.question.approvalHint")}
        </p>
        <div className={styles.toolChips}>
          {(item.actionNames ?? []).map((name) => (
            <code key={name} className={styles.toolChip}>
              {name}
            </code>
          ))}
        </div>
        <div className={styles.cardActions}>
          <Button
            size="small"
            icon={<ArrowUpRight size={14} strokeWidth={1.9} />}
            onClick={onOpen}
          >
            {t("home.inbox.question.open")}
          </Button>
        </div>
      </div>
    </article>
  );
}

function TaskCard({
  item,
  busy,
  relativeTime,
  onAck,
  onFollowUp,
  onOpen,
}: {
  item: InboxItem;
  busy: boolean;
  relativeTime: (at: number, now: number) => string;
  onAck: () => void;
  onFollowUp: (text: string) => void;
  onOpen: () => void;
}) {
  const { t } = useTranslation();
  const task = item.task;
  const [replyOpen, setReplyOpen] = useState(false);
  const [text, setText] = useState("");
  if (!task) return null;
  const failed = task.status === "failed";
  const statusKey =
    task.status === "failed"
      ? "failed"
      : task.status === "awaiting"
      ? "awaiting"
      : "done";
  const output = failed ? task.error_text : task.result_text;

  return (
    <article className={styles.card} data-state={item.state} data-source="task">
      <CardHead
        item={item}
        icon={
          failed ? (
            <AlertTriangle size={16} strokeWidth={1.8} />
          ) : (
            <CheckCircle2 size={16} strokeWidth={1.8} />
          )
        }
        label={t(`home.inbox.task.${statusKey}`)}
      />
      <div className={styles.cardBody}>
        <div className={styles.cardTitleRow}>
          <h3 className={styles.cardTitle}>{task.task_text}</h3>
          <span className={styles.cardTime}>
            {relativeTime(item.createdAt, Date.now())}
          </span>
        </div>
        {output && (
          <details className={styles.taskOutput}>
            <summary>
              <span>{t(failed ? "home.inbox.task.error" : "home.inbox.task.result")}</span>
              <ChevronDown size={13} strokeWidth={1.9} />
            </summary>
            <pre>{output}</pre>
          </details>
        )}
        {item.reply && (
          <p className={styles.taskReply}>
            <span>{t("home.inbox.task.replyLabel")}</span>
            {item.reply}
          </p>
        )}
        {item.error && <p className={styles.cardError}>{item.error}</p>}
        <div className={styles.cardActions}>
          <Button
            size="small"
            type="text"
            icon={<ArrowUpRight size={14} strokeWidth={1.9} />}
            onClick={onOpen}
          >
            {t("home.inbox.task.open")}
          </Button>
          <Button
            size="small"
            type="text"
            onClick={() => setReplyOpen((open) => !open)}
          >
            {t("home.inbox.task.followUp")}
          </Button>
          {isOpen(item) && (
            <Button
              size="small"
              type="text"
              loading={busy}
              icon={<CheckCircle2 size={14} strokeWidth={1.9} />}
              onClick={onAck}
            >
              {t("home.inbox.task.ack")}
            </Button>
          )}
          {item.state === "acknowledged" && (
            <span className={styles.cardResolution}>
              {t("home.inbox.task.acknowledged")}
            </span>
          )}
        </div>
        {replyOpen && (
          <div className={styles.replyRow}>
            <Input
              size="small"
              value={text}
              placeholder={t("home.inbox.task.followUpPlaceholder")}
              onChange={(event) => setText(event.target.value)}
              onPressEnter={() => {
                if (!text.trim() || busy) return;
                onFollowUp(text);
                setText("");
                setReplyOpen(false);
              }}
              autoFocus
            />
            <Button
              size="small"
              type="primary"
              loading={busy}
              disabled={!text.trim()}
              icon={<Send size={13} strokeWidth={1.9} />}
              onClick={() => {
                onFollowUp(text);
                setText("");
                setReplyOpen(false);
              }}
            >
              {t("home.inbox.task.send")}
            </Button>
            <Button
              size="small"
              type="text"
              icon={<X size={13} strokeWidth={1.9} />}
              aria-label={t("home.inbox.task.cancel")}
              onClick={() => setReplyOpen(false)}
            />
          </div>
        )}
      </div>
    </article>
  );
}
