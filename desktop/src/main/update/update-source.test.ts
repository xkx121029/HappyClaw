import assert from "node:assert/strict";
import { test } from "node:test";

import { isValidAssetUrl, selectRelease } from "./update-coordinator";
import {
  DEFAULT_UPDATE_ENDPOINT,
  manifestFromGitHubReleases,
  PROJECT_REPO,
  resolveUpdateSource,
  UPDATE_DOWNLOAD_ORIGINS_ENV,
  UPDATE_ENDPOINT_ENV,
  updateRequestHeaders,
} from "./update-source";

const PROJECT_DOWNLOADS = "https://github.com/xkx121029/HappyClaw/releases/download/";

function release(tag: string, overrides: Record<string, unknown> = {}) {
  return {
    tag_name: tag,
    html_url: `https://github.com/xkx121029/HappyClaw/releases/tag/${tag}`,
    draft: false,
    prerelease: false,
    assets: [
      {
        name: `HappyClaw-desktop-darwin-arm64-${tag.replace(/^v/, "")}.dmg`,
        browser_download_url: `${PROJECT_DOWNLOADS}${tag}/HappyClaw-desktop-darwin-arm64-1.dmg`,
      },
      {
        name: `HappyClaw-desktop-windows-amd64-${tag.replace(/^v/, "")}.exe`,
        browser_download_url: `${PROJECT_DOWNLOADS}${tag}/HappyClaw-desktop-windows-amd64-1.exe`,
      },
    ],
    ...overrides,
  };
}

test("the default catalog is this project's own GitHub Releases", () => {
  const source = resolveUpdateSource({});
  assert.equal(source.manifestUrl, DEFAULT_UPDATE_ENDPOINT);
  assert.equal(source.manifestFormat, "github");
  assert.deepEqual(source.downloadOrigins, [PROJECT_DOWNLOADS]);
  assert.equal(source.manifestUrl.includes(PROJECT_REPO), true);
});

test("an unusable endpoint falls back to the default instead of a dead address", () => {
  for (const raw of ["", "   ", "http://api.github.com/repos/a/b/releases", "not a url"]) {
    const source = resolveUpdateSource({ [UPDATE_ENDPOINT_ENV]: raw });
    assert.equal(source.manifestUrl, DEFAULT_UPDATE_ENDPOINT);
    assert.equal(source.manifestFormat, "github");
  }
});

test("a github endpoint for another repository moves the trust anchor with it", () => {
  const source = resolveUpdateSource({
    [UPDATE_ENDPOINT_ENV]: "https://api.github.com/repos/someone/fork/releases",
  });
  assert.equal(source.manifestFormat, "github");
  assert.deepEqual(source.downloadOrigins, ["https://github.com/someone/fork/releases/download/"]);
});

test("a self-hosted catalog speaks the octop envelope and trusts its own origin", () => {
  const source = resolveUpdateSource({
    [UPDATE_ENDPOINT_ENV]: "https://market.internal:9000/api/downloads",
  });
  assert.equal(source.manifestFormat, "octop");
  assert.deepEqual(source.downloadOrigins, ["https://market.internal:9000/"]);
});

test("an explicit download allow-list wins and is normalised", () => {
  const source = resolveUpdateSource({
    [UPDATE_DOWNLOAD_ORIGINS_ENV]: " https://dl.example.com , http://plain.example , broken",
  });
  assert.deepEqual(source.downloadOrigins, ["https://dl.example.com/"]);
  // Trailing slash added, so a look-alike host cannot ride the prefix.
  assert.equal(isValidAssetUrl("https://dl.example.com/a.dmg", source.downloadOrigins), true);
  assert.equal(isValidAssetUrl("https://dl.example.com.evil/a.dmg", source.downloadOrigins), false);
});

test("the github catalog yields one release per channel", () => {
  const manifest = manifestFromGitHubReleases([
    release("v1.0.2"),
    release("v1.0.4"),
    release("v1.0.3b1", { prerelease: true }),
    release("v1.0.5b1", { prerelease: true }),
    release("v1.1.0", { draft: true }),
  ]);
  assert.equal(manifest.client.stable?.tag, "v1.0.4");
  assert.equal(manifest.client.beta?.tag, "v1.0.5b1");
  assert.equal(manifest.client.stable?.releasesUrl, `https://github.com/xkx121029/HappyClaw/releases/tag/v1.0.4`);
});

test("installers are mapped to asset keys by platform, not by position", () => {
  const manifest = manifestFromGitHubReleases([release("v1.0.2")]);
  const assets = manifest.client.stable!.assets;
  assert.equal(assets.mac_arm?.ext, "dmg");
  assert.equal(assets.win_x64?.ext, "exe");
  assert.match(assets.mac_arm!.url, /HappyClaw-desktop-darwin-arm64-1\.dmg$/);
  // The stable release carries no Windows arm64 or macOS intel installer.
  assert.equal(assets.win_arm, undefined);
  assert.equal(assets.mac_intel, undefined);
});

test("unusable releases are skipped, and a non-list body is a check failure", () => {
  assert.throws(() => manifestFromGitHubReleases({ success: true }), /not a list/);
  const empty = manifestFromGitHubReleases([release("nightly"), null, "v1.0.3"]);
  assert.equal(empty.client.stable, undefined);
  assert.equal(empty.client.beta, undefined);

  // A tag with no installer is still the channel head, but offers no update.
  const noAssets = manifestFromGitHubReleases([{ tag_name: "v1.0.2" }]);
  assert.equal(noAssets.client.stable?.tag, "v1.0.2");
  assert.deepEqual(noAssets.client.stable?.assets, {});
  assert.equal(selectRelease(noAssets, "1.0.1", "mac_arm", true), null);
});

test("the github format asks for the github media type; a self-hosted one does not", () => {
  assert.deepEqual(updateRequestHeaders(resolveUpdateSource({})), {
    Accept: "application/vnd.github+json",
  });
  assert.equal(
    updateRequestHeaders(
      resolveUpdateSource({ [UPDATE_ENDPOINT_ENV]: "https://market.internal/api/downloads" }),
    ),
    undefined,
  );
});
