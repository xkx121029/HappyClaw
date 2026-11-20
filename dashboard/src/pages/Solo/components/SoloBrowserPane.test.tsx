import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import SoloBrowserPane from "./SoloBrowserPane";

const mocks = vi.hoisted(() => ({
  refresh: vi.fn(),
  state: {
    sessionId: null as string | null,
    environment: "desktop",
    isConnected: false,
  },
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => {
      const templates: Record<string, string> = {
        "solo.browserEmptyTitle": "还没有可预览的浏览器会话",
        "solo.browserEmptyBody": "agent 用浏览器工具打开页面后，预览会自动出现。",
        "solo.browserNoThread": "先选择一个会话，才能看它的浏览器预览。",
        "solo.browserRemoteHint": "远端专家的浏览器通过 Bridge 接入。",
        "solo.browserWaitingHint": "浏览器服务已连接，等待 agent 打开页面。",
        "solo.browserStreamOffline": "浏览器服务未连接；浏览器启动后会自动重连。",
        "solo.browserRefresh": "重新检测",
        "solo.agentStoppedHint": "当前专家未运行，启动后才能对话",
      };
      return templates[key] ?? key;
    },
  }),
}));

vi.mock("../../../hooks/useBrowserSessionState", () => ({
  useBrowserSessionState: () => ({
    sessionId: mocks.state.sessionId,
    environment: mocks.state.environment,
    isConnected: mocks.state.isConnected,
    refresh: mocks.refresh,
  }),
}));

vi.mock("../../../components/BrowserWorkspace", () => ({
  default: ({ sessionId }: { sessionId?: string | null }) => (
    <div data-testid="browser-workspace">{sessionId}</div>
  ),
}));

describe("SoloBrowserPane", () => {
  beforeEach(() => {
    mocks.state.sessionId = null;
    mocks.state.isConnected = false;
    mocks.refresh.mockReset();
  });

  it("没有选中会话时不假装能预览，并禁用重新检测", () => {
    render(<SoloBrowserPane threadId={null} agentReady />);

    expect(
      screen.getByText("先选择一个会话，才能看它的浏览器预览。"),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("browser-workspace")).toBeNull();
    expect(screen.getByRole("button", { name: /重新检测/ })).toBeDisabled();
  });

  it("有会话但 agent 没打开页面时说明会自动接入，并显示连接状态", () => {
    mocks.state.isConnected = true;
    render(<SoloBrowserPane threadId="thr_1" agentReady />);

    expect(screen.getByText("还没有可预览的浏览器会话")).toBeInTheDocument();
    expect(
      screen.getByText("浏览器服务已连接，等待 agent 打开页面。"),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("browser-workspace")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /重新检测/ }));
    expect(mocks.refresh).toHaveBeenCalledTimes(1);
  });

  it("专家未运行时如实提示，而不是显示成空列表", () => {
    render(<SoloBrowserPane threadId="thr_1" agentReady={false} />);

    expect(
      screen.getByText("当前专家未运行，启动后才能对话"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /重新检测/ })).toBeDisabled();
  });

  it("已有浏览器会话时直接渲染预览", () => {
    mocks.state.sessionId = "user-1";
    render(<SoloBrowserPane threadId="thr_1" agentReady />);

    expect(screen.getByTestId("browser-workspace")).toHaveTextContent("user-1");
    expect(screen.queryByText("还没有可预览的浏览器会话")).toBeNull();
  });
});
