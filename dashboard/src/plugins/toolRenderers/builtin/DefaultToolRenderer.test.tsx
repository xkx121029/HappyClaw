import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import styles from "../../../pages/Chat/index.module.less";
import { builtinPluginHost } from "../host";
import { DefaultToolRenderer } from "./DefaultToolRenderer";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback ?? key,
  }),
}));

const base = {
  pluginId: "builtin",
  toolName: "read_file",
  displayName: "读取文件",
  status: "running" as const,
  isStreaming: true,
  host: builtinPluginHost,
};

describe("DefaultToolRenderer streaming chrome", () => {
  it("places the breathing dots to the right of the tool name and keeps status on the right", () => {
    render(<DefaultToolRenderer {...base} />);

    const name = screen.getByText("读取文件");
    const status = screen.getByText("Running");
    const dots = name.nextElementSibling;

    expect(dots).toHaveClass(styles.inlineToolLiveDots);
    expect(dots?.querySelectorAll("span")).toHaveLength(3);
    expect(dots?.contains(status)).toBe(false);
    expect(status).toHaveClass(styles.inlineToolStatus);
    expect(
      name.compareDocumentPosition(status) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      dots &&
        dots.compareDocumentPosition(status) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("shows the tool being called instead of the deferred wrapper name", () => {
    render(
      <DefaultToolRenderer
        {...base}
        toolName="call_deferred_tool"
        displayName="按需调用"
        status="done"
        isStreaming={false}
        args={{ name: "read_file", arguments: { file_path: "notes.txt" } }}
        output="ok"
      />,
    );

    expect(screen.getByText("read_file")).toBeInTheDocument();
    expect(screen.queryByText("按需调用")).not.toBeInTheDocument();
  });

  it("keeps the wrapper label until the deferred target name arrives", () => {
    render(
      <DefaultToolRenderer
        {...base}
        toolName="call_deferred_tool"
        displayName="按需调用"
        args={{}}
      />,
    );

    expect(screen.getByText("按需调用")).toBeInTheDocument();
  });

  it("caps overflowing details and only offers show-all when clipped", () => {
    const scrollHeight = vi
      .spyOn(HTMLElement.prototype, "scrollHeight", "get")
      .mockReturnValue(900);
    const clientHeight = vi
      .spyOn(HTMLElement.prototype, "clientHeight", "get")
      .mockReturnValue(360);
    try {
      render(
        <DefaultToolRenderer
          {...base}
          status="done"
          isStreaming={false}
          args={{ command: "pytest -q" }}
          output={"x".repeat(5000)}
        />,
      );

      fireEvent.click(screen.getByRole("button", { name: /读取文件/ }));
      const showAll = screen.getByRole("button", { name: "Show all" });
      expect(showAll).toHaveAttribute("aria-expanded", "false");
      const body = showAll.previousElementSibling as HTMLElement;
      expect(body).toHaveClass(styles.inlineToolDetailsClamped);
      expect(body).toHaveAttribute("data-tool-details-overflow", "true");

      fireEvent.click(showAll);
      const showLess = screen.getByRole("button", { name: "Show less" });
      expect(showLess).toHaveAttribute("aria-expanded", "true");
      expect(
        (showLess.previousElementSibling as HTMLElement).className,
      ).not.toContain(styles.inlineToolDetailsClamped);

      // Collapsing resets the preference so the next open is capped again.
      fireEvent.click(screen.getByRole("button", { name: /读取文件/ }));
      expect(
        screen.queryByRole("button", { name: "Show less" }),
      ).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: /读取文件/ }));
      expect(
        screen.getByRole("button", { name: "Show all" }),
      ).toBeInTheDocument();
    } finally {
      scrollHeight.mockRestore();
      clientHeight.mockRestore();
    }
  });

  it("does not offer show-all when the details fit", () => {
    render(
      <DefaultToolRenderer
        {...base}
        status="done"
        isStreaming={false}
        args={{ command: "pwd" }}
        output="ok"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /读取文件/ }));
    expect(
      screen.queryByRole("button", { name: "Show all" }),
    ).not.toBeInTheDocument();
    const body = (screen.getByText("Result").parentElement as HTMLElement)
      .parentElement as HTMLElement;
    expect(body).toHaveClass(styles.inlineToolDetailsClamped);
  });

  it("keeps a completed status without the breathing dots", () => {
    render(
      <DefaultToolRenderer
        {...base}
        status="done"
        isStreaming={false}
        output="ok"
      />,
    );

    const name = screen.getByText("读取文件");
    const status = screen.getByText("Done");
    expect(name.nextElementSibling).toBe(status);
    expect(status).toHaveClass(styles.inlineToolStatus);
    expect(
      name.parentElement?.querySelector(`.${styles.inlineToolLiveDots}`),
    ).toBeNull();
  });
});
