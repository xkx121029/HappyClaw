import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback ?? key,
    i18n: { language: "zh" },
  }),
}));

vi.mock("react-router-dom", () => ({
  useNavigate: () => vi.fn(),
}));

vi.mock("../hooks/useIsMobile", () => ({
  useIsMobile: () => false,
}));

vi.mock("../context/LayoutModeContext", () => ({
  useLayoutMode: () => ({
    layoutMode: "classic",
    setLayoutMode: vi.fn(),
  }),
}));

vi.mock("../utils/locale", () => ({
  applyUserLocale: vi.fn(() => Promise.resolve("zh")),
}));

vi.mock("./ThemeSwitcher", () => ({ default: () => null }));
vi.mock("./PaletteSwitcher", () => ({ default: () => null }));

vi.mock("../pages/Admin/Users/ProfileAvatar", () => ({
  ProfileAvatar: () => <span data-testid="profile-avatar" />,
  ProfileAvatarPicker: () => <div data-testid="avatar-picker" />,
}));

import AvatarDropdown from "./AvatarDropdown";

/**
 * 单人本机模式：入口只保留本机外观 / 语言 / 显示名与备份入口，
 * 不再有账号、角色、改密与退出登录。
 */
describe("AvatarDropdown local profile", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  async function openMenu() {
    const view = userEvent.setup();
    render(<AvatarDropdown placement="sidebar" />);
    await view.click(screen.getByRole("button", { name: /我/ }));
    return view;
  }

  it("labels the profile as local single-user mode", async () => {
    await openMenu();

    expect(screen.getByText("本机 · 单人模式")).toBeInTheDocument();
    expect(screen.getByText("account.settings")).toBeInTheDocument();
    expect(screen.getByText("本机数据备份与恢复")).toBeInTheDocument();
    expect(screen.queryByText("account.roleUser")).toBeNull();
    expect(screen.queryByText("account.changePassword")).toBeNull();
  });

  it("puts close and save in the settings drawer footer", async () => {
    const view = await openMenu();
    await view.click(screen.getByRole("button", { name: "account.settings" }));

    const save = await screen.findByRole("button", { name: "common.save" });
    // antd 会在两个汉字之间插入空格，按正则匹配。
    const close = screen.getByRole("button", { name: /关\s*闭/ });
    const footer = close.closest(".ant-drawer-footer");
    expect(footer).toContainElement(save);

    expect(await screen.findByTestId("avatar-picker")).toBeInTheDocument();
    expect(screen.queryByText("account.currentPassword")).toBeNull();
  });

  it("keeps display name and mode hint together in the drawer identity", async () => {
    const view = await openMenu();
    await view.click(screen.getByRole("button", { name: "account.settings" }));

    const modeHint = await screen.findByText("本机 · 单人模式");
    const identity = modeHint.parentElement as HTMLElement;
    expect(identity.textContent).toContain("我");
    expect(identity.textContent).toContain("本机 · 单人模式");
  });
});
