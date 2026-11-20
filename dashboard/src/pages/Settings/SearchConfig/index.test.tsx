/**
 * SearchConfig.test.tsx — search provider settings page.
 *
 * Covers:
 *   - default source is HappySearch and an empty runtime state is shown
 *   - configured third-party providers remain additive
 *   - switching source calls the persisted settings API
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { App } from "antd";

vi.mock("../../../api/modules/env", () => ({
  envsApi: {
    listEnvs: vi.fn(),
    batchSaveEnvs: vi.fn(),
    deleteEnv: vi.fn(),
  },
}));

const settingsMocks = vi.hoisted(() => ({
  searchSource: vi.fn(),
  putSearchSource: vi.fn(),
  searchStatus: vi.fn(),
}));

vi.mock("../../../api/modules/settings", () => ({
  octopSettingsApi: settingsMocks,
}));

import { envsApi } from "../../../api/modules/env";
import SearchConfigPage from "./index";

const api = vi.mocked(envsApi, true);

const defaultSource = {
  effective: "happysearch",
  stored: null,
  env: null,
  origin: "default",
  applied: true,
};

const emptyStatus = {
  source: { effective: "happysearch", stored: null, env: null, origin: "default" },
  tools_visible: ["happysearch_search"],
  commercial_providers: [],
  happysearch: {
    enabled: true,
    runtime: {
      runs: 0,
      fallbacks: 0,
      errors: 0,
      in_flight: 0,
      last: null,
      engines_last: {},
    },
  },
  searchfree: {
    enabled: true,
    runtime: { runs: 0, errors: 0, in_flight: 0, last: null },
  },
  last: null,
};

function envResp(keys: string[]) {
  return keys.map((key, i) => ({ key, value: `v${i}` })) as never;
}

function renderPage() {
  return render(
    <App>
      <SearchConfigPage />
    </App>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  api.listEnvs.mockResolvedValue(envResp([]));
  settingsMocks.searchSource.mockResolvedValue(defaultSource);
  settingsMocks.searchStatus.mockResolvedValue(emptyStatus);
  settingsMocks.putSearchSource.mockResolvedValue({
    ...defaultSource,
    effective: "both",
    stored: "both",
    origin: "settings",
  });
});

describe("<SearchConfigPage />", () => {
  it("shows HappySearch as the default source with an empty runtime state", async () => {
    renderPage();
    await waitFor(() => expect(settingsMocks.searchSource).toHaveBeenCalled());

    expect(
      screen.getByText("advancedSettings.search.desc"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("advancedSettings.search.sourceHappyTitle"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("advancedSettings.search.sourceNativeTitle"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("advancedSettings.search.sourceBothTitle"),
    ).toBeInTheDocument();
    expect(
      screen.getAllByText("advancedSettings.search.statusNever").length,
    ).toBeGreaterThan(0);
  });

  it("keeps configured third-party providers as additive", async () => {
    api.listEnvs.mockResolvedValue(envResp(["TAVILY_API_KEY"]));

    renderPage();
    await waitFor(() => expect(api.listEnvs).toHaveBeenCalled());

    expect(screen.getByText("Tavily")).toBeInTheDocument();
    expect(
      screen.getByText("advancedSettings.search.thirdPartyAdditiveTitle"),
    ).toBeInTheDocument();
  });

  it("persists source changes through the settings API", async () => {
    renderPage();
    await waitFor(() => expect(settingsMocks.searchSource).toHaveBeenCalled());

    fireEvent.click(
      screen.getByRole("radio", {
        name: /advancedSettings.search.sourceBothTitle/,
      }),
    );

    await waitFor(() =>
      expect(settingsMocks.putSearchSource).toHaveBeenCalledWith({
        source: "both",
      }),
    );
  });
});
