import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Toolbar } from "./Toolbar";

function renderToolbar(overrides: Partial<Parameters<typeof Toolbar>[0]> = {}) {
  return render(
    <Toolbar
      workingRowsLength={10}
      allSelected={false}
      someSelected
      selectedSize={3}
      dirty={false}
      saving={false}
      indeterminate
      onToggleSelectAll={vi.fn()}
      onRemoveSelected={vi.fn()}
      onReset={vi.fn()}
      onSave={vi.fn()}
      {...overrides}
    />,
  );
}

describe("Toolbar", () => {
  it("用一条可翻译的整句表达选中数量，避免拼接造成的语序错乱", () => {
    renderToolbar();

    expect(
      screen.getByText("environments.selectionSummary"),
    ).toBeInTheDocument();
    // 旧实现把「共」「已选」拼成 "3 共 10 已选"，中文语序错误。
    expect(screen.queryByText(/共/)).not.toBeInTheDocument();
  });

  it("没有选中项时只显示变量总数", () => {
    renderToolbar({ someSelected: false, indeterminate: false, selectedSize: 0 });

    expect(screen.getByText("10 environments.variables")).toBeInTheDocument();
    expect(
      screen.queryByText("environments.selectionSummary"),
    ).not.toBeInTheDocument();
  });
});
