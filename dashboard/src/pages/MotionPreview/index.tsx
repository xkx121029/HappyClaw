import { useCallback, useMemo, useRef, useState } from "react";
import { Button, Tag } from "antd";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ArrowLeft, Plus, Send, Sparkles, Trash2 } from "lucide-react";
import {
  BeamCardReveal,
  MotionEnter,
  SharedElement,
  rememberSharedElement,
  useMotion,
} from "../../motion";
import styles from "./index.module.less";

interface DemoMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
}

interface DemoCard {
  id: string;
  title: string;
  meta: string;
  glyph: string;
}

const INITIAL_MESSAGES: DemoMessage[] = [
  { id: "m1", role: "user", text: "帮我把今天的活动整理成一条时间线。" },
  {
    id: "m2",
    role: "assistant",
    text: "已经按时间顺序排好，重点动作我都标了出来。",
  },
];

const INITIAL_CARDS: DemoCard[] = [
  { id: "c1", title: "日报汇总", meta: "每天 09:00", glyph: "报" },
  { id: "c2", title: "仓库巡检", meta: "每 2 小时", glyph: "巡" },
  { id: "c3", title: "周报提醒", meta: "周五 17:30", glyph: "周" },
];

let seq = 100;

/**
 * 动效样例页：/motion-preview
 * 用来直接观察统一动效标尺下的各类场景，所有数值读取当前用户偏好。
 */
export default function MotionPreviewPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { prefs, tokens, reduced } = useMotion();

  const [messages, setMessages] = useState<DemoMessage[]>(INITIAL_MESSAGES);
  const [freshIds, setFreshIds] = useState<ReadonlySet<string>>(new Set());
  const [cards, setCards] = useState<DemoCard[]>(INITIAL_CARDS);
  const [questionOpen, setQuestionOpen] = useState(false);
  const [detailId, setDetailId] = useState<string | null>(null);
  const messageRef = useRef(0);

  const appendMessage = useCallback(
    (role: DemoMessage["role"]) => {
      messageRef.current += 1;
      const id = `m-${seq + messageRef.current}`;
      const text =
        role === "user"
          ? `第 ${messageRef.current} 条指令：继续推进刚才的任务。`
          : `收到，第 ${messageRef.current} 条回复已经生成。`;
      setMessages((prev) => [...prev, { id, role, text }]);
      setFreshIds(new Set([id]));
    },
    [],
  );

  const addCard = useCallback(() => {
    seq += 1;
    setCards((prev) => [
      ...prev,
      {
        id: `c-${seq}`,
        title: `新任务 ${seq}`,
        meta: "刚刚创建",
        glyph: "新",
      },
    ]);
  }, []);

  const removeCard = useCallback((id: string) => {
    setCards((prev) => prev.filter((card) => card.id !== id));
  }, []);

  const detailCard = useMemo(
    () => cards.find((card) => card.id === detailId) ?? null,
    [cards, detailId],
  );

  const openDetail = (card: DemoCard) => {
    rememberSharedElement(`preview-${card.id}-avatar`);
    rememberSharedElement(`preview-${card.id}-title`);
    setDetailId(card.id);
  };

  const closeDetail = () => {
    if (detailId) {
      rememberSharedElement(`preview-${detailId}-avatar`);
      rememberSharedElement(`preview-${detailId}-title`);
    }
    setDetailId(null);
  };

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <h1 className={styles.title}>
            {t("motionPreview.title", "动效样例")}
          </h1>
          <p className={styles.subtitle}>
            {t(
              "motionPreview.subtitle",
              "所有场景共用一套时长、曲线与位移标尺；修改个性化设置里的动效偏好会立即反映到这里。",
            )}
          </p>
        </div>
        <div className={styles.tokenBar}>
          <Tag bordered={false}>{t("account.motionCurve", "曲线")} · {prefs.curve}</Tag>
          <Tag bordered={false}>{t("account.motionSpeed", "速度")} · {prefs.speed}</Tag>
          <Tag bordered={false}>
            base {tokens.duration.base}ms · slow {tokens.duration.slow}ms
          </Tag>
          {reduced ? (
            <Tag color="orange">{t("account.motionReducedOn")}</Tag>
          ) : null}
        </div>
      </header>

      <div className={styles.grid}>
        <section className={styles.panel}>
          <div className={styles.panelHead}>
            <h2 className={styles.panelTitle}>{t("motionPreview.pageTitle", "页面切换")}</h2>
            <p className={styles.panelDesc}>
              {t(
                "motionPreview.pageDesc",
                "前进从右侧进入、后退从左侧回到原位；新页面立即可交互，离场层不接收点击。",
              )}
            </p>
          </div>
          <div className={styles.row}>
            <Button onClick={() => navigate("/home")}>
              {t("motionPreview.goHome", "去主页（前进）")}
            </Button>
            <Button onClick={() => navigate("/tasks")}>
              {t("motionPreview.goTasks", "去任务（前进）")}
            </Button>
            <Button icon={<ArrowLeft size={14} />} onClick={() => navigate(-1)}>
              {t("motionPreview.goBack", "返回上一页（后退）")}
            </Button>
          </div>

          <div className={styles.fakePageStrip}>
            <MotionEnter kind="from-left" animate={false} className={styles.stripItem}>
              A
            </MotionEnter>
            <MotionEnter kind="rise" animate={false} className={styles.stripItem}>
              B
            </MotionEnter>
            <MotionEnter kind="scale" animate={false} className={styles.stripItem}>
              C
            </MotionEnter>
          </div>
        </section>

        <section className={styles.panel}>
          <div className={styles.panelHead}>
            <h2 className={styles.panelTitle}>
              {t("motionPreview.messageTitle", "消息逐条出现")}
            </h2>
            <p className={styles.panelDesc}>
              {t(
                "motionPreview.messageDesc",
                "只有刚出现的消息做入场；历史载入与滚动复用不会重播。",
              )}
            </p>
          </div>
          <div className={styles.chatStage}>
            {messages.map((message) => (
              <MotionEnter
                key={message.id}
                kind="rise"
                duration="fast"
                animate={freshIds.has(message.id)}
                className={
                  message.role === "user"
                    ? styles.bubbleUser
                    : styles.bubbleAssistant
                }
              >
                {message.text}
              </MotionEnter>
            ))}
          </div>
          <div className={styles.row}>
            <Button icon={<Plus size={14} />} onClick={() => appendMessage("user")}>
              {t("motionPreview.addUserMessage", "来一条用户消息")}
            </Button>
            <Button icon={<Send size={14} />} onClick={() => appendMessage("assistant")}>
              {t("motionPreview.addAssistantMessage", "来一条回复")}
            </Button>
          </div>
        </section>

        <section className={styles.panel}>
          <div className={styles.panelHead}>
            <h2 className={styles.panelTitle}>
              {t("motionPreview.taskTitle", "任务卡片")}
            </h2>
            <p className={styles.panelDesc}>
              {t(
                "motionPreview.taskDesc",
                "出现有进节奏、删除有退节奏；状态徽章就地变化时轻微 pop。",
              )}
            </p>
          </div>
          <div className={styles.cardGrid}>
            {cards.map((card, index) => (
              <MotionEnter
                key={card.id}
                kind="rise"
                index={index}
                className={styles.taskCard}
              >
                <span className={styles.taskGlyph}>{card.glyph}</span>
                <div className={styles.taskBody}>
                  <strong>{card.title}</strong>
                  <span>{card.meta}</span>
                </div>
                <Button
                  type="text"
                  size="small"
                  icon={<Trash2 size={13} />}
                  aria-label="remove"
                  onClick={() => removeCard(card.id)}
                />
              </MotionEnter>
            ))}
          </div>
          <div className={styles.row}>
            <Button icon={<Plus size={14} />} onClick={addCard}>
              {t("motionPreview.addTask", "新增任务卡片")}
            </Button>
          </div>
        </section>

        <section className={styles.panel}>
          <div className={styles.panelHead}>
            <h2 className={styles.panelTitle}>
              {t("motionPreview.beamTitle", "Agent 提问卡片")}
            </h2>
            <p className={styles.panelDesc}>
              {t(
                "motionPreview.beamDesc",
                "一束光从活动核心射出，光斑放大铺开，再收拢成卡片；随时可按 Esc 或取消打断。",
              )}
            </p>
          </div>
          <div className={styles.beamStage}>
            {questionOpen ? (
              <BeamCardReveal
                open
                className={styles.questionCard}
                onCancel={() => setQuestionOpen(false)}
              >
                <div className={styles.questionHead}>
                  <Sparkles size={16} />
                  <span>{t("motionPreview.questionFrom", "HappyClaw 想确认一件事")}</span>
                </div>
                <p className={styles.questionText}>
                  {t(
                    "motionPreview.questionText",
                    "今天这份巡检报告要现在发出去，还是先存成草稿？",
                  )}
                </p>
                <div className={styles.questionActions}>
                  <Button size="small" type="primary">
                    {t("motionPreview.questionSend", "现在发送")}
                  </Button>
                  <Button size="small" onClick={() => setQuestionOpen(false)}>
                    {t("motionPreview.questionLater", "先存草稿")}
                  </Button>
                </div>
              </BeamCardReveal>
            ) : (
              <Button
                type="primary"
                icon={<Sparkles size={14} />}
                onClick={() => setQuestionOpen(true)}
              >
                {t("motionPreview.beamTrigger", "模拟提问出现")}
              </Button>
            )}
          </div>
        </section>

        <section className={`${styles.panel} ${styles.widePanel}`}>
          <div className={styles.panelHead}>
            <h2 className={styles.panelTitle}>
              {t("motionPreview.sharedTitle", "列表进详情（共享元素）")}
            </h2>
            <p className={styles.panelDesc}>
              {t(
                "motionPreview.sharedDesc",
                "同一个标题与头像在两个视图间平移缩放衔接；返回时回到原位置。",
              )}
            </p>
          </div>

          {detailCard ? (
            <div className={styles.detail}>
              <button
                type="button"
                className={styles.backBtn}
                onClick={closeDetail}
              >
                <ArrowLeft size={14} />
                {t("motionPreview.backToList", "返回列表")}
              </button>
              <div className={styles.detailHero}>
                <SharedElement
                  id={`preview-${detailCard.id}-avatar`}
                  as="span"
                  className={styles.detailAvatar}
                >
                  {detailCard.glyph}
                </SharedElement>
                <SharedElement
                  id={`preview-${detailCard.id}-title`}
                  as="h2"
                  className={styles.detailTitle}
                >
                  {detailCard.title}
                </SharedElement>
              </div>
              <p className={styles.detailText}>
                {t(
                  "motionPreview.detailBody",
                  "这里是详情内容。返回列表时，标题会沿着来时的路径回到卡片原位。",
                )}
              </p>
            </div>
          ) : (
            <div className={styles.listGrid}>
              {cards.map((card) => (
                <button
                  key={card.id}
                  type="button"
                  className={styles.listCard}
                  onClick={() => openDetail(card)}
                >
                  <SharedElement
                    id={`preview-${card.id}-avatar`}
                    as="span"
                    className={styles.listAvatar}
                  >
                    {card.glyph}
                  </SharedElement>
                  <SharedElement
                    id={`preview-${card.id}-title`}
                    as="strong"
                    className={styles.listTitle}
                  >
                    {card.title}
                  </SharedElement>
                  <span className={styles.listMeta}>{card.meta}</span>
                </button>
              ))}
            </div>
          )}
        </section>

        <section className={`${styles.panel} ${styles.widePanel}`}>
          <div className={styles.panelHead}>
            <h2 className={styles.panelTitle}>
              {t("motionPreview.timelineTitle", "进出场节奏")}
            </h2>
            <p className={styles.panelDesc}>
              {t(
                "motionPreview.timelineDesc",
                "同一组 token 生成的进场与退场节奏：进场略慢、退场略快。",
              )}
            </p>
          </div>
          <div className={styles.rhythm}>
            {(["instant", "fast", "base", "slow", "slower", "epic"] as const).map(
              (key) => (
                <div key={key} className={styles.rhythmRow}>
                  <span className={styles.rhythmName}>{key}</span>
                  <span
                    className={styles.rhythmBar}
                    style={{ width: `${Math.min(100, (tokens.duration[key] / 8) * 10)}%` }}
                  />
                  <span className={styles.rhythmValue}>
                    {tokens.duration[key]}ms
                  </span>
                </div>
              ),
            )}
          </div>
          <p className={styles.easeLine}>
            {tokens.enterEase} → {tokens.exitEase}
          </p>
        </section>
      </div>
    </div>
  );
}
