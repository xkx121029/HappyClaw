import assert from "node:assert/strict";
import { test } from "node:test";

import {
  channelHeadTag,
  manifestFromDownloadsResponse,
  selectRelease,
  platformAssetKey,
  isValidAssetUrl,
} from "./update-coordinator";

// The default download prefix (§6.1): the project's own release assets.
const RELEASE_ORIGIN = "https://github.com/xkx121029/HappyClaw/releases/download";

const stable = {
  tag: "v1.0.2",
  releasesUrl: "https://github.com/x/releases",
  assets: {
    mac_arm: {
      name: "Octop.dmg",
      ext: "dmg",
      url: `${RELEASE_ORIGIN}/v1.0.2/Octop-desktop-darwin-arm64-1.0.2.dmg`,
    },
  },
};
const beta = {
  tag: "v1.0.3b1",
  releasesUrl: "https://github.com/x/releases",
  assets: {
    mac_arm: {
      name: "Octop.dmg",
      ext: "dmg",
      url: `${RELEASE_ORIGIN}/v1.0.3b1/Octop-desktop-darwin-arm64-1.0.3b1.dmg`,
    },
  },
};

test("platformAssetKey maps platform+arch", () => {
  assert.equal(platformAssetKey("darwin", "arm64"), "mac_arm");
  assert.equal(platformAssetKey("darwin", "x64"), "mac_intel");
  assert.equal(platformAssetKey("win32", "arm64"), "win_arm");
  assert.equal(platformAssetKey("win32", "x64"), "win_x64");
  assert.equal(platformAssetKey("linux", "x64"), null);
});

test("channel head stays on stable when stableOnly and beta is higher", () => {
  assert.equal(channelHeadTag({ client: { stable, beta } }, true), "v1.0.2");
});

test("channel head is the higher tag when stableOnly is off", () => {
  assert.equal(channelHeadTag({ client: { stable, beta } }, false), "v1.0.3b1");
  const release = {
    ...stable,
    tag: "v1.0.3",
  };
  assert.equal(channelHeadTag({ client: { stable: release, beta } }, false), "v1.0.3");
});

test("missing channel is a failed check for the head", () => {
  assert.throws(() => channelHeadTag({ client: {} }, true), /selected channel/);
  assert.throws(() => channelHeadTag({ client: {} }, false), /selected channel/);
});

test("stableOnly ignores higher beta", () => {
  const sel = selectRelease(
    { client: { stable, beta } },
    "1.0.1",
    "mac_arm",
    true,
  );
  assert.equal(sel?.tag, "v1.0.2");
});

test("beta channel selected when stableOnly off and beta is newer", () => {
  const sel = selectRelease(
    { client: { stable, beta } },
    "1.0.2",
    "mac_arm",
    false,
  );
  assert.equal(sel?.tag, "v1.0.3b1");
});

test("installed beta higher than stable never downgrades", () => {
  const sel = selectRelease(
    { client: { stable, beta } },
    "1.0.3b1",
    "mac_arm",
    false,
  );
  assert.equal(sel, null);
});

test("missing platform asset yields no update", () => {
  const sel = selectRelease({ client: { stable } }, "1.0.1", "win_x64", true);
  assert.equal(sel, null);
});

test("downloads envelope unwraps data.client and ignores pet", () => {
  const manifest = manifestFromDownloadsResponse({
    success: true,
    code: 0,
    msg: "ok",
    data: {
      client: { stable, beta },
      pet: { tag: "v0.2.0" },
    },
  });
  const sel = selectRelease(manifest, "1.0.1", "mac_arm", true);
  assert.equal(sel?.tag, "v1.0.2");
});

test("failed or incomplete downloads envelope is a check failure", () => {
  assert.throws(
    () => manifestFromDownloadsResponse({ success: false, data: { client: { stable } } }),
    /failure/,
  );
  assert.throws(
    () => manifestFromDownloadsResponse({ success: true, data: { pet: {} } }),
    /data\.client/,
  );
  assert.throws(
    () => selectRelease({ client: {} }, "1.0.1", "mac_arm", true),
    /selected channel/,
  );
});

test("asset urls must sit under a trusted https prefix", () => {
  const origins = [`${RELEASE_ORIGIN}/`];
  assert.equal(isValidAssetUrl(`${RELEASE_ORIGIN}/v1.0.2/Octop.dll.dmg`, origins), true);
  assert.equal(isValidAssetUrl("http://github.com/xkx121029/HappyClaw/releases/download/a.dmg", origins), false);
  assert.equal(isValidAssetUrl("https://evil.example/a.dmg", origins), false);
  assert.equal(isValidAssetUrl("https://dl.example.com/a.dmg", origins), false);
  // The upstream host is no longer trusted by default.
  assert.equal(isValidAssetUrl("https://dl.example.com/a.dmg"), false);
  // A host that only shares the prefix text must not pass.
  assert.equal(isValidAssetUrl("https://github.com.evil.example/a.dmg"), false);
  // An empty allow-list trusts nothing.
  assert.equal(isValidAssetUrl(`${RELEASE_ORIGIN}/a.dmg`, []), false);
});
