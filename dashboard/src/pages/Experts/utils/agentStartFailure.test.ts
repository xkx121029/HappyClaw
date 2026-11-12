import { describe, expect, it } from "vitest";
import type { TFunction } from "i18next";
import { resolveAgentStartFailure } from "./agentStartFailure";

const COPY: Record<string, string> = {
  "chat.agentNoModel": "还没有配置模型，去设置里添加。",
  "modelConfig.configureButton": "去配置模型",
  "experts.agentStartFailed": "启动失败",
};

const t = ((key: string, options?: string | { defaultValue?: string }) => {
  if (COPY[key]) return COPY[key];
  if (typeof options === "string") return options;
  return options?.defaultValue ?? key;
}) as unknown as TFunction;

describe("resolveAgentStartFailure", () => {
  it("maps AGENT_NO_MODEL to Chinese copy with a model-settings link", () => {
    const error = Object.assign(
      new Error("还没有配置模型。请先在设置里添加一个模型，再开始对话。"),
      { code: "AGENT_NO_MODEL" },
    );

    const failure = resolveAgentStartFailure(error, t);

    expect(failure.message).toBe("还没有配置模型，去设置里添加。");
    expect(failure.configurePath).toBe("/admin/models");
    expect(failure.configureLabelKey).toBe("modelConfig.configureButton");
  });
});
