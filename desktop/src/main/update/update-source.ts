/**
 * Where the shell looks for updates (§6.1).
 *
 * Both the catalog address and the download origins used to be literal upstream
 * domains, so the update channel and the upstream site died together and a
 * self-hosted build had no way to point the shell anywhere else. Both are now
 * configuration:
 *
 * - ``HAPPYCLAW_UPDATE_ENDPOINT``: catalog URL. Two response shapes are understood.
 *   A GitHub Releases API URL (``api.github.com/repos/<owner>/<repo>/releases``)
 *   is read as releases; anything else must answer the Octop ``/api/downloads``
 *   envelope.
 * - ``HAPPYCLAW_UPDATE_DOWNLOAD_ORIGINS``: comma-separated https URL prefixes an
 *   installer may be downloaded from. Unset means "whatever the catalog address
 *   implies": the project's own release downloads, or the same ``owner/repo``
 *   when the endpoint names another repository.
 *
 * The default catalog is this project's own GitHub Releases, which
 * ``.github/workflows/octop-desktop.yml`` fills with the per-platform installers
 * (``Octop-desktop-<plat>-<version>.<ext>``). Nothing here reaches upstream.
 */

import { compareVersions, parseVersion } from "../supervisor/version";
import type { ChannelRelease, DownloadManifest, PlatformKey } from "./update-coordinator";

export const UPDATE_ENDPOINT_ENV = "HAPPYCLAW_UPDATE_ENDPOINT";
export const UPDATE_DOWNLOAD_ORIGINS_ENV = "HAPPYCLAW_UPDATE_DOWNLOAD_ORIGINS";

export const PROJECT_REPO = "xkx121029/HappyClaw";
export const DEFAULT_UPDATE_ENDPOINT =
  `https://api.github.com/repos/${PROJECT_REPO}/releases?per_page=30`;
export const DEFAULT_UPDATE_DOWNLOAD_ORIGINS = [
  `https://github.com/${PROJECT_REPO}/releases/download/`,
];

export type ManifestFormat = "github" | "octop";

export interface UpdateSource {
  manifestUrl: string;
  manifestFormat: ManifestFormat;
  downloadOrigins: readonly string[];
}

const GITHUB_REPO_PATH = /^\/repos\/([^/]+)\/([^/]+)\/releases\/?$/;
const GITHUB_ORIGIN = "https://api.github.com";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function httpsUrl(raw: string): URL | null {
  try {
    const parsed = new URL(raw);
    return parsed.protocol === "https:" ? parsed : null;
  } catch {
    return null;
  }
}

function githubRepo(parsed: URL): string | null {
  if (parsed.origin !== GITHUB_ORIGIN) return null;
  const match = GITHUB_REPO_PATH.exec(parsed.pathname);
  return match ? `${match[1]}/${match[2]}` : null;
}

/**
 * Download prefixes from ``HAPPYCLAW_UPDATE_DOWNLOAD_ORIGINS``. Each entry is
 * normalised to end in ``/`` so a prefix can never match a look-alike host
 * (``https://dl.example.com`` must not admit ``https://dl.example.com.evil``).
 * Non-https and unparsable entries are dropped: an empty result means every
 * installer is refused, which is the safe reading of a broken allow-list.
 */
function configuredOrigins(raw: string): string[] {
  return raw
    .split(",")
    .map((entry) => httpsUrl(entry.trim()))
    .filter((entry): entry is URL => entry !== null)
    .map((entry) => (entry.href.endsWith("/") ? entry.href : `${entry.href}/`));
}

/** Resolve the catalog address and download allow-list for this process. */
export function resolveUpdateSource(env: NodeJS.ProcessEnv = process.env): UpdateSource {
  const rawEndpoint = (env[UPDATE_ENDPOINT_ENV] ?? "").trim();
  const parsed = httpsUrl(rawEndpoint) ?? httpsUrl(DEFAULT_UPDATE_ENDPOINT)!;
  const repo = githubRepo(parsed);
  const manifestFormat: ManifestFormat = repo ? "github" : "octop";

  const rawOrigins = (env[UPDATE_DOWNLOAD_ORIGINS_ENV] ?? "").trim();
  if (rawOrigins) {
    return {
      manifestUrl: parsed.toString(),
      manifestFormat,
      downloadOrigins: configuredOrigins(rawOrigins),
    };
  }
  // No explicit allow-list: follow the endpoint. A GitHub catalog pins the
  // installers to that same repository's release downloads, so moving the
  // endpoint to a fork moves the trust anchor with it. A self-hosted catalog
  // that serves packages from another host must name it explicitly.
  return {
    manifestUrl: parsed.toString(),
    manifestFormat,
    downloadOrigins: repo ? [`https://github.com/${repo}/releases/download/`] : [`${parsed.origin}/`],
  };
}

/**
 * Installer file names the desktop workflow attaches to a release, per asset
 * key. ``platform`` values match the matrix in ``octop-desktop.yml``.
 */
const PLATFORM_ASSETS: Record<PlatformKey, { platform: string; ext: string }> = {
  mac_arm: { platform: "darwin-arm64", ext: "dmg" },
  mac_intel: { platform: "darwin-amd64", ext: "dmg" },
  win_x64: { platform: "windows-amd64", ext: "exe" },
  win_arm: { platform: "windows-arm64", ext: "exe" },
};

function assetsFromRelease(raw: Record<string, unknown>): ChannelRelease["assets"] {
  const files = Array.isArray(raw.assets) ? raw.assets : [];
  const assets: ChannelRelease["assets"] = {};
  for (const file of files) {
    if (!isRecord(file)) continue;
    const name = typeof file.name === "string" ? file.name.trim() : "";
    const url = typeof file.browser_download_url === "string" ? file.browser_download_url : "";
    if (!name || !url) continue;
    const lower = name.toLowerCase();
    for (const key of Object.keys(PLATFORM_ASSETS) as PlatformKey[]) {
      const { platform, ext } = PLATFORM_ASSETS[key];
      if (!assets[key] && lower.includes(platform) && lower.endsWith(`.${ext}`)) {
        assets[key] = { name, ext, url };
      }
    }
  }
  return assets;
}

/** Highest tag of a channel; ``null`` when the channel has no usable release. */
function newestOf(releases: ChannelRelease[]): ChannelRelease | null {
  const ranked = releases
    .filter((release) => parseVersion(release.tag) !== null)
    .sort((a, b) => compareVersions(b.tag, a.tag));
  return ranked[0] ?? null;
}

/**
 * Map a GitHub Releases listing onto the catalog the shell already consumes.
 *
 * Drafts are skipped. ``prerelease`` is the beta channel, everything else is
 * stable; each channel keeps only its own highest tag so the stable/beta choice
 * in §6.1 stays a single comparison.
 */
export function manifestFromGitHubReleases(body: unknown): DownloadManifest {
  if (!Array.isArray(body)) throw new Error("releases response is not a list");
  const stable: ChannelRelease[] = [];
  const beta: ChannelRelease[] = [];
  for (const raw of body) {
    if (!isRecord(raw) || raw.draft === true) continue;
    const tag = typeof raw.tag_name === "string" ? raw.tag_name.trim() : "";
    if (!tag || parseVersion(tag) === null) continue;
    const release: ChannelRelease = {
      tag,
      releasesUrl: typeof raw.html_url === "string" ? raw.html_url : "",
      assets: assetsFromRelease(raw),
    };
    (raw.prerelease === true ? beta : stable).push(release);
  }
  const client: DownloadManifest["client"] = {};
  const newestStable = newestOf(stable);
  const newestBeta = newestOf(beta);
  if (newestStable) client.stable = newestStable;
  if (newestBeta) client.beta = newestBeta;
  return { client };
}

/** Headers the GitHub Releases API asks for. Ignored by a self-hosted catalog. */
export function updateRequestHeaders(source: UpdateSource): Record<string, string> | undefined {
  return source.manifestFormat === "github"
    ? { Accept: "application/vnd.github+json" }
    : undefined;
}
