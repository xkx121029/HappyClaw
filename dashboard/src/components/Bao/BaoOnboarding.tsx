import { useCallback, useEffect, useMemo, useState } from "react";
import { Button, Modal, message } from "antd";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { getApiUrl } from "../../api/config";
import { providerApi } from "../../api/modules/provider";
import { request } from "../../api/request";
import type { ResolvedModel } from "../../api/types";
import { useAgent } from "../../context/AgentContext";
import type { OctopAgent } from "../../context/AgentContext";
import { apiErrorMessage } from "../../utils/apiError";
import { Mascot } from "../Mascot";
import { useBao } from "./BaoContext";

interface BaoOnboardingProps {
  open: boolean;
  /** The name the user just gave the mascot. */
  name: string;
  /** Close without persisting "done" (e.g. the step sends the user to settings). */
  onNavigate: () => void;
  onSkip: () => void;
  onDone: () => void;
}

type CheckState = "unknown" | "ok" | "todo";

interface GuideStatus {
  backend: CheckState;
  models: ResolvedModel[] | null;
  agent: OctopAgent | null;
  workspaceDir: string;
  agentRunning: boolean;
  checking: boolean;
  enabling: boolean;
  reload: () => Promise<void>;
  enableAgent: () => Promise<void>;
}

function pickExpert(agents: OctopAgent[]): OctopAgent | null {
  return (
    agents.find((item) => !item.bridge && item.kind !== "team") ??
    agents[0] ??
    null
  );
}

function workspaceOf(agent: OctopAgent | null): string {
  if (!agent) return "";
  const config = agent.config ?? {};
  const direct = typeof config.workspace_dir === "string" ? config.workspace_dir : "";
  if (direct) return direct;
  const backend = config.backend as { root_dir?: unknown } | undefined;
  return typeof backend?.root_dir === "string" ? backend.root_dir : "";
}

/**
 * Real first-run status, read from the running instance instead of the draft
 * the wizard handed over: model catalog, the auto-created expert, its state,
 * and the workspace it actually points at.
 */
function useGuideStatus(open: boolean): GuideStatus {
  const { t } = useTranslation();
  const { agents, refresh } = useAgent();
  const [backend, setBackend] = useState<CheckState>("unknown");
  const [models, setModels] = useState<ResolvedModel[] | null>(null);
  const [checking, setChecking] = useState(false);
  const [enabling, setEnabling] = useState(false);

  const reload = useCallback(async () => {
    setChecking(true);
    try {
      const response = await fetch(getApiUrl("/health"), {
        headers: { Accept: "application/json" },
      });
      setBackend(response.ok ? "ok" : "todo");
    } catch {
      setBackend("todo");
    }
    try {
      setModels(await providerApi.listResolvedModels());
    } catch {
      setModels(null);
    }
    setChecking(false);
  }, []);

  useEffect(() => {
    if (!open) return;
    void reload();
    void refresh({ silent: true, force: true });
  }, [open, reload, refresh]);

  useEffect(() => {
    if (!open) return;
    // Returning from the model/expert settings page must refresh the checks.
    const onFocus = () => void reload();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [open, reload]);

  const agent = useMemo(() => pickExpert(agents), [agents]);

  const enableAgent = useCallback(async () => {
    if (!agent) return;
    setEnabling(true);
    try {
      await request(`/agents/${agent.agent_id}/start`, { method: "POST" });
      message.success(t("chat.enableExpertStarted", { name: agent.name }));
      await refresh({ silent: true, force: true });
      await reload();
    } catch (error) {
      message.error(
        apiErrorMessage(error, t("chat.enableExpertFailed"), t),
      );
    } finally {
      setEnabling(false);
    }
  }, [agent, refresh, reload, t]);

  return {
    backend,
    models,
    agent,
    workspaceDir: workspaceOf(agent),
    agentRunning: Boolean(agent && agent.state === "running"),
    checking,
    enabling,
    reload,
    enableAgent,
  };
}

interface Step {
  key: string;
  title: string;
  state: "curious" | "listening" | "celebrate";
}

/**
 * First-deploy guide: model → expert & workspace → Bao's name → health check →
 * done. Every step reads the live instance, links to the page that fixes the
 * gap, and can be skipped: the conclusion then points at the same settings
 * pages instead of pretending the step passed.
 */
export default function BaoOnboarding({
  open,
  name,
  onNavigate,
  onSkip,
  onDone,
}: BaoOnboardingProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { appearance, openNaming } = useBao();
  const status = useGuideStatus(open);
  const [step, setStep] = useState(0);

  const steps: Step[] = useMemo(
    () => [
      { key: "model", title: t("bao.guide.stepModel", "配置模型"), state: "curious" },
      {
        key: "expert",
        title: t("bao.guide.stepExpert", "专家与工作区"),
        state: "listening",
      },
      {
        key: "identity",
        title: t("bao.guide.stepIdentity", "认识{{name}}", { name }),
        state: "listening",
      },
      {
        key: "health",
        title: t("bao.guide.stepHealth", "健康检查"),
        state: "curious",
      },
      { key: "done", title: t("bao.guide.stepDone", "完成"), state: "celebrate" },
    ],
    [name, t],
  );

  useEffect(() => {
    if (open) setStep(0);
  }, [open]);

  const current = steps[step];
  const last = step === steps.length - 1;
  const modelCount = status.models?.length ?? 0;
  const hasModels = modelCount > 0;
  const expertReady = Boolean(status.agent && status.agentRunning);
  const workspaceReady = Boolean(status.workspaceDir);

  const openSettings = (path: string) => {
    onNavigate();
    navigate(path);
  };

  const finish = () => {
    onDone();
    navigate("/chat");
  };

  const renderModelStep = () => (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <p style={{ margin: 0, lineHeight: 1.6 }}>
        {t(
          "bao.guide.modelIntro",
          "先接一个能用的大模型，我才能开始干活。配好之后回到这里会自动重新检查。",
        )}
      </p>
      <StatusLine
        state={hasModels ? "ok" : status.models === null ? "unknown" : "todo"}
        label={
          status.models === null
            ? t("bao.guide.modelLoading", "正在读取模型配置…")
            : hasModels
              ? t("bao.guide.modelReady", "已配置 {{count}} 个可用模型", {
                  count: modelCount,
                })
              : t("bao.guide.modelMissing", "还没有可用模型")
        }
      />
      <div style={{ display: "flex", gap: 8 }}>
        <Button
          type={hasModels ? "default" : "primary"}
          onClick={() => openSettings("/admin/models?tab=chat")}
        >
          {hasModels
            ? t("bao.guide.openModels", "管理模型")
            : t("modelConfig.configureButton", "去配置模型")}
        </Button>
      </div>
    </div>
  );

  const renderExpertStep = () => (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <p style={{ margin: 0, lineHeight: 1.6 }}>
        {t(
          "bao.guide.expertIntro",
          "专家负责干活，工作区是它能读写文件的地方。装好之后已经有一个默认专家。",
        )}
      </p>
      {status.agent ? (
        <StatusLine
          state={expertReady ? "ok" : "todo"}
          label={
            expertReady
              ? t("bao.guide.expertReady", "{{name}} 已启用", {
                  name: status.agent.name,
                })
              : t("bao.guide.expertStopped", "{{name}} 还没有启用", {
                  name: status.agent.name,
                })
          }
        />
      ) : (
        <StatusLine
          state="unknown"
          label={t("bao.guide.expertLoading", "正在读取专家…")}
        />
      )}
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 4,
          padding: "10px 12px",
          borderRadius: 10,
          background: "var(--fn-bg-base)",
          border: "1px solid var(--fn-border-subtle, rgba(0,0,0,0.08))",
        }}
      >
        <span style={{ fontSize: 12, color: "var(--fn-text-tertiary)" }}>
          {t("bao.guide.workspaceLabel", "工作区")}
        </span>
        <span
          title={status.workspaceDir}
          style={{
            fontSize: 12,
            wordBreak: "break-all",
            fontFamily:
              'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
          }}
        >
          {status.workspaceDir || t("bao.guide.workspaceUnknown", "暂时读不到，可在专家详情里查看")}
        </span>
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        {status.agent && !expertReady && hasModels ? (
          <Button
            type="primary"
            loading={status.enabling}
            onClick={() => void status.enableAgent()}
          >
            {t("chat.enableExpert", "启用这个专家")}
          </Button>
        ) : null}
        {status.agent && !expertReady && !hasModels ? (
          <Button
            type="primary"
            onClick={() => openSettings("/admin/models?tab=chat")}
          >
            {t("bao.guide.enableNeedsModel", "先配好模型再启用")}
          </Button>
        ) : null}
        <Button onClick={() => openSettings("/experts")}>
          {t("bao.guide.openExperts", "去看看专家")}
        </Button>
      </div>
    </div>
  );

  const renderIdentityStep = () => (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <p style={{ margin: 0, lineHeight: 1.6 }}>
        {t(
          "bao.guide.identityIntro",
          "名字会用在侧栏、项目宝和消息署名上，随时可以改。",
        )}
      </p>
      <StatusLine
        state="ok"
        label={t("bao.guide.identityCurrent", "现在叫「{{name}}」", { name })}
      />
      <div style={{ display: "flex", gap: 8 }}>
        <Button
          onClick={() => {
            onNavigate();
            openNaming();
          }}
        >
          {t("bao.identity.rename", "改名")}
        </Button>
      </div>
    </div>
  );

  const checks = [
    {
      key: "backend",
      state: status.backend,
      label: t("bao.guide.checkBackend", "本机服务"),
      value:
        status.backend === "ok"
          ? t("bao.guide.ok", "正常")
          : status.backend === "todo"
            ? t("bao.guide.todo", "连接不上")
            : t("bao.guide.checking", "检查中…"),
    },
    {
      key: "model",
      state: hasModels ? "ok" : status.models === null ? "unknown" : "todo",
      label: t("bao.guide.checkModel", "可用模型"),
      value:
        status.models === null
          ? t("bao.guide.checking", "检查中…")
          : hasModels
            ? t("bao.guide.modelCount", "{{count}} 个", { count: modelCount })
            : t("bao.guide.todo", "未就绪"),
    },
    {
      key: "expert",
      state: status.agent ? (expertReady ? "ok" : "todo") : "unknown",
      label: t("bao.guide.checkExpert", "专家状态"),
      value: status.agent
        ? expertReady
          ? t("bao.guide.expertRunning", "已启用")
          : t("bao.guide.todo", "未就绪")
        : t("bao.guide.checking", "检查中…"),
    },
    {
      key: "workspace",
      state: workspaceReady ? "ok" : "unknown",
      label: t("bao.guide.checkWorkspace", "工作区"),
      value: workspaceReady
        ? t("bao.guide.ok", "正常")
        : t("bao.guide.checking", "检查中…"),
    },
  ] as const;

  const todoCount = checks.filter((item) => item.state === "todo").length;

  const renderHealthStep = () => (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <p style={{ margin: 0, lineHeight: 1.6 }}>
        {t(
          "bao.guide.healthIntro",
          "这四项都正常就能直接开始。没就绪的会告诉你该去哪补。",
        )}
      </p>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {checks.map((item) => (
          <StatusLine
            key={item.key}
            state={item.state}
            label={item.label}
            value={item.value}
          />
        ))}
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <Button loading={status.checking} onClick={() => void status.reload()}>
          {t("bao.guide.recheck", "重新检查")}
        </Button>
        {!hasModels ? (
          <Button
            type="primary"
            onClick={() => openSettings("/admin/models?tab=chat")}
          >
            {t("modelConfig.configureButton", "去配置模型")}
          </Button>
        ) : null}
        {status.agent && !expertReady && hasModels ? (
          <Button
            type="primary"
            loading={status.enabling}
            onClick={() => void status.enableAgent()}
          >
            {t("chat.enableExpert", "启用这个专家")}
          </Button>
        ) : null}
      </div>
    </div>
  );

  const renderDoneStep = () => (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <p style={{ margin: 0, lineHeight: 1.6 }}>
        {todoCount === 0
          ? t("bao.guide.doneAllReady", "都准备好了，直接开始吧。")
          : t(
              "bao.guide.donePartial",
              "还有 {{count}} 项没就绪。可以先开始，之后在设置里的模型配置和专家页补齐。",
              { count: todoCount },
            )}
      </p>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {checks.map((item) => (
          <StatusLine
            key={item.key}
            state={item.state}
            label={item.label}
            value={item.value}
          />
        ))}
      </div>
    </div>
  );

  return (
    <Modal
      open={open}
      onCancel={onSkip}
      footer={null}
      width={480}
      destroyOnHidden
      centered
      // A stray click on the backdrop must not permanently skip the guide;
      // skipping is an explicit choice in the footer.
      maskClosable={false}
      title={t("bao.guide.title", "{{name}}带你走一遍", { name })}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <Mascot
            size={76}
            {...appearance}
            state={current.state}
            surface="var(--fn-bg-elevated)"
          />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontWeight: 600, marginBottom: 4 }}>
              {current.title}
            </div>
            <span style={{ color: "var(--fn-text-tertiary)", fontSize: 12 }}>
              {t("bao.guide.progress", "第 {{current}} / {{total}} 步", {
                current: step + 1,
                total: steps.length,
              })}
            </span>
          </div>
        </div>

        {/* Long steps stay scrollable so the footer buttons never fall below
            the fold on short windows. */}
        <div
          style={{
            minHeight: 148,
            maxHeight: "calc(100vh - 320px)",
            overflowY: "auto",
            paddingRight: 4,
          }}
        >
          {current.key === "model" && renderModelStep()}
          {current.key === "expert" && renderExpertStep()}
          {current.key === "identity" && renderIdentityStep()}
          {current.key === "health" && renderHealthStep()}
          {current.key === "done" && renderDoneStep()}
        </div>

        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <Button size="small" type="text" onClick={onSkip}>
            {t("bao.guide.skip", "跳过，稍后在设置里补")}
          </Button>
          <span style={{ flex: 1 }} />
          <Button
            size="small"
            disabled={step === 0}
            onClick={() => setStep((value) => Math.max(0, value - 1))}
          >
            {t("bao.onboarding.back", "上一步")}
          </Button>
          {last ? (
            <Button size="small" type="primary" onClick={finish}>
              {t("bao.guide.startChat", "开始对话")}
            </Button>
          ) : (
            <Button
              size="small"
              type="primary"
              onClick={() => setStep((value) => value + 1)}
            >
              {t("bao.onboarding.next", "下一步")}
            </Button>
          )}
        </div>
      </div>
    </Modal>
  );
}

function dotColor(state: CheckState): string {
  if (state === "ok") return "var(--fn-color-success, #22c55e)";
  if (state === "todo") return "var(--fn-color-warning, #f59e0b)";
  return "var(--fn-text-quaternary, #9aa2ad)";
}

function StatusLine({
  state,
  label,
  value,
}: {
  state: CheckState;
  label: string;
  value?: string;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        fontSize: "var(--fn-text-xs)",
        lineHeight: 1.5,
      }}
    >
      <span
        aria-hidden
        style={{
          width: 8,
          height: 8,
          borderRadius: 999,
          flex: "0 0 auto",
          background: dotColor(state),
        }}
      />
      <span style={{ flex: "0 0 auto", color: "var(--fn-text-secondary)" }}>
        {label}
      </span>
      {value ? (
        <span
          style={{
            marginLeft: "auto",
            color: "var(--fn-text-tertiary)",
            textAlign: "right",
          }}
        >
          {value}
        </span>
      ) : null}
    </div>
  );
}
