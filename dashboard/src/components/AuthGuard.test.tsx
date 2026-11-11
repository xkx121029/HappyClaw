import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { useEffect } from "react";
import AuthGuard from "./AuthGuard";

/**
 * 单人本机模式：入口不再校验登录态，只探测后端连通性。
 * 这些用例覆盖「离线面板 / 直接进入 / 重试」三条主路径。
 */
describe("AuthGuard local gate", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    // ``api/config`` reads the Vite ``define`` constant; Vitest config does not
    // inject it, so provide an empty base or the probe throws before fetching.
    vi.stubGlobal("BASE_URL", "");
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows offline panel instead of the shell when the local backend is unreachable", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));

    render(
      <MemoryRouter>
        <AuthGuard>
          <div>local-shell</div>
        </AuthGuard>
      </MemoryRouter>,
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toBeInTheDocument();
    expect(alert.textContent).toMatch(
      /errors\.offlineTitle|Cannot reach|无法连接/,
    );
    expect(
      screen.getByRole("button", { name: /errors\.retry|Retry|重试/ }),
    ).toBeInTheDocument();
    expect(screen.queryByText("local-shell")).not.toBeInTheDocument();
  });

  it("enters the shell directly without any auth request", async () => {
    fetchMock.mockResolvedValue({ ok: true, status: 200 } as Response);

    function NavProbe() {
      const navigate = useNavigate();
      useEffect(() => {
        navigate("/b");
      }, [navigate]);
      return <div>local-shell</div>;
    }

    render(
      <MemoryRouter initialEntries={["/a"]}>
        <AuthGuard>
          <Routes>
            <Route path="/a" element={<NavProbe />} />
            <Route path="/b" element={<div>local-shell</div>} />
          </Routes>
        </AuthGuard>
      </MemoryRouter>,
    );

    expect(await screen.findByText("local-shell")).toBeInTheDocument();
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain("/health");
  });

  it("retries from the offline panel without a blank shell", async () => {
    fetchMock
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValue({ ok: true, status: 200 } as Response);

    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <AuthGuard>
          <div>local-shell</div>
        </AuthGuard>
      </MemoryRouter>,
    );

    const retry = await screen.findByRole("button", {
      name: /errors\.retry|Retry|重试/,
    });
    await user.click(retry);
    expect(await screen.findByText("local-shell")).toBeInTheDocument();
  });
});
