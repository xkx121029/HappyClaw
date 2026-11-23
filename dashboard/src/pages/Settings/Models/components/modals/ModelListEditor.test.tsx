import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "antd";
import { describe, expect, it, vi } from "vitest";
import { ModelListEditor } from "./ModelListEditor";
import type { ProviderModel, ProviderRow } from "../../useProviders";

function renderEditor(models: ProviderModel[]) {
  const provider: ProviderRow = {
    id: 1,
    name: "mindie",
    kind: "openai",
    base_url: "http://10.0.0.8/v1",
    api_key: "sk-test",
    models,
    note: null,
    enabled: true,
  };
  return render(
    <App>
      <ModelListEditor
        provider={provider}
        models={models}
        onModelsChange={vi.fn()}
        canTest={false}
      />
    </App>,
  );
}

describe("ModelListEditor", () => {
  it("shows protocol fallback after selecting Responses", async () => {
    const user = userEvent.setup();
    HTMLElement.prototype.scrollIntoView = vi.fn();
    renderEditor([
      { id: "deepseek-chat", name: "DeepSeek Chat", enabled: true },
    ]);

    await user.click(screen.getByRole("button", { name: "models.editModel" }));
    // antd Select 只在选择器上的 mousedown 时展开下拉；用 userEvent 点击选中值
    // 文本在 jsdom 里不会触发 rc-select 的展开逻辑（与 RootDirSelect 测试同法）。
    fireEvent.mouseDown(
      screen.getByRole("combobox", { name: "models.apiMode" }),
    );
    await user.click(await screen.findByText("models.apiModeResponses"));

    expect(screen.getByText("models.apiFallback")).toBeInTheDocument();
    expect(screen.getByText("models.apiFallbackNone")).toBeInTheDocument();
  });

  it("scrolls to the edit form after clicking edit", async () => {
    const user = userEvent.setup();
    const scrollIntoView = vi.fn();
    HTMLElement.prototype.scrollIntoView = scrollIntoView;
    vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
      cb(0);
      return 1;
    });
    renderEditor([
      { id: "qwen", name: "Qwen", enabled: true, input: ["text"] },
    ]);

    await user.click(screen.getByRole("button", { name: "models.editModel" }));
    expect(await screen.findByDisplayValue("qwen")).toBeInTheDocument();
    expect(scrollIntoView).toHaveBeenCalled();
    // 用途由所属 tab / provider lane 固定，编辑表单里不再有 per-model 用途单选。
    expect(screen.queryByText("models.purposeChat")).not.toBeInTheDocument();
    expect(screen.queryByText("models.reasoning")).not.toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "models.showAdvanced" }),
    );
    expect(screen.getByText("models.reasoning")).toBeInTheDocument();
  });
});
