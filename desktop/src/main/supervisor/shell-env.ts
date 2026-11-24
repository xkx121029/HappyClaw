import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

/**
 * HAPPYCLAW_HOME resolution (§3.2): the data root used both for the extraction
 * directory and the child process env, so the shell and ``PathLayout.from_env()``
 * agree on one location.
 *
 * Priority:
 *   1. non-empty ``HAPPYCLAW_HOME`` (then legacy ``OCTOP_HOME``) inherited by the process
 *   2. the same variables from the login shell (macOS / Linux only)
 *   3. ``~/.happyclaw``, or ``~/.octop`` when only the pre-rename data directory exists
 *
 * A leading ``~`` expands against the current user's home directory.
 */

export function expandHome(raw: string, home = homedir()): string {
  const trimmed = raw.trim();
  if (trimmed === "~") return home;
  if (trimmed.startsWith("~/") || trimmed.startsWith("~\\")) {
    return join(home, trimmed.slice(2));
  }
  return trimmed;
}

export function resolveHappyclawHome(
  processEnv: NodeJS.ProcessEnv,
  loginShellEnv: Record<string, string | undefined>,
  home = homedir(),
): string {
  const inherited = (processEnv.HAPPYCLAW_HOME ?? "").trim() || (processEnv.OCTOP_HOME ?? "").trim();
  if (inherited) return expandHome(inherited, home);
  const shellValue =
    (loginShellEnv.HAPPYCLAW_HOME ?? "").trim() || (loginShellEnv.OCTOP_HOME ?? "").trim();
  if (shellValue) return expandHome(shellValue, home);
  const current = join(home, ".happyclaw");
  const legacy = join(home, ".octop");
  if (!existsSync(current) && existsSync(legacy)) return legacy;
  return current;
}

/** Run ``$SHELL -ilc 'env -0'`` and parse NUL-delimited ``KEY=VALUE`` pairs. */
export function readLoginShellEnv(
  shell: string | undefined,
): Promise<Record<string, string>> {
  return new Promise((resolvePromise) => {
    const command = shell && shell.trim() ? shell.trim() : process.env.SHELL || "/bin/bash";
    execFile(
      command,
      ["-ilc", "env -0"],
      { maxBuffer: 64 * 1024 * 1024, timeout: 5000 },
      (err, stdout) => {
        if (err) {
          resolvePromise({});
          return;
        }
        const out: Record<string, string> = {};
        for (const chunk of stdout.split("\0")) {
          const eq = chunk.indexOf("=");
          if (eq <= 0) continue;
          out[chunk.slice(0, eq)] = chunk.slice(eq + 1);
        }
        resolvePromise(out);
      },
    );
  });
}
