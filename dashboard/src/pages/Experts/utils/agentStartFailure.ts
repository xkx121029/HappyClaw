import { Modal } from "antd";
import type { TFunction } from "i18next";

import { message } from "@/utils/antdMessage";
import { apiErrorMessage, parseApiError } from "../../../utils/apiError";
import {
  chatErrorActionByCode,
  formatChatErrorByCode,
  normalizeChatErrorCode,
} from "../../../utils/chatStreamError";

export interface AgentStartFailure {
  /** 可直接展示的中文说明。 */
  message: string;
  /** 需要用户去补配置时的设置页路径；其余失败为 null。 */
  configurePath: string | null;
  configureLabelKey: string | null;
}

/**
 * 专家「启动」失败的展示信息。
 *
 * 正常启动不依赖模型，但后端会在分发前拦下没有模型的专家并返回
 * ``AGENT_NO_MODEL``（409）。这类失败要给出可点的模型设置入口，
 * 不能只在控制台或开关状态里静默掉。
 */
export function resolveAgentStartFailure(
  error: unknown,
  t: TFunction,
): AgentStartFailure {
  const parsed = parseApiError(error);
  const code = normalizeChatErrorCode(parsed?.code);
  if (code === "AGENT_NO_MODEL") {
    const action = chatErrorActionByCode(code, parsed?.message);
    return {
      message: formatChatErrorByCode(code, parsed?.message, t),
      configurePath: action?.path ?? "/admin/models",
      configureLabelKey: action?.labelKey ?? "modelConfig.configureButton",
    };
  }
  return {
    message: apiErrorMessage(
      error,
      t("experts.agentStartFailed", "启动失败"),
      t,
    ),
    configurePath: null,
    configureLabelKey: null,
  };
}

/** 展示启动失败：缺模型弹可跳转设置的面板，其他失败保持一条中文提示。 */
export function reportAgentStartFailure(
  error: unknown,
  t: TFunction,
  onConfigure: (path: string) => void,
): void {
  const failure = resolveAgentStartFailure(error, t);
  if (!failure.configurePath) {
    message.error(failure.message);
    return;
  }
  Modal.confirm({
    title: t("experts.agentStartFailed", "启动失败"),
    content: failure.message,
    okText: t(failure.configureLabelKey ?? "modelConfig.configureButton"),
    cancelText: t("common.cancel", "取消"),
    onOk: () => onConfigure(failure.configurePath as string),
  });
}
