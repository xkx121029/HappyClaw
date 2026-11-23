import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { EnvRow, type Row } from "./EnvRow";

function renderRow(row: Row = { key: "OPENAI_API_KEY", value: "sk-test" }) {
  return render(
    <EnvRow
      row={row}
      idx={0}
      checked={false}
      onToggle={vi.fn()}
      onChange={vi.fn()}
      onInsert={vi.fn()}
      onRemove={vi.fn()}
    />,
  );
}

describe("EnvRow", () => {
  it("本地化键值字段的标签与占位符，不再暴露英文原文", () => {
    renderRow();

    expect(screen.getByText("environments.key")).toBeInTheDocument();
    expect(screen.getByText("environments.value")).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText("environments.variableNamePlaceholder"),
    ).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText("environments.valuePlaceholder"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Key")).not.toBeInTheDocument();
    expect(screen.queryByText("Variable Name")).not.toBeInTheDocument();
  });

  it("为纯图标操作与勾选框提供可访问名称", () => {
    renderRow();

    expect(
      screen.getByRole("button", { name: "environments.insertRowBelow" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "environments.deleteRow" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "environments.showValue" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("checkbox", { name: "environments.selectVariable" }),
    ).toBeInTheDocument();
  });
});
