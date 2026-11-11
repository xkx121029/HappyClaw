import { existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";

/**
 * "Open at login" for the desktop shell.
 *
 * Windows and macOS use Electron's login-item API. Linux has no equivalent, so
 * the shell writes the freedesktop autostart entry itself. The entry is
 * rewritten on every settings save so an upgrade that moves the executable
 * does not leave a dead launcher behind.
 */

export const AUTOSTART_FILE = "happyclaw.desktop";

export function linuxAutostartPath(homeDir: string): string {
  return join(homeDir, ".config", "autostart", AUTOSTART_FILE);
}

/** Quote one Exec argument per the Desktop Entry spec. */
export function quoteExecArg(value: string): string {
  return `"${value.replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`;
}

export function linuxAutostartEntry(options: {
  name: string;
  execPath: string;
  args?: readonly string[];
  comment?: string;
}): string {
  const command = [options.execPath, ...(options.args ?? [])].map(quoteExecArg).join(" ");
  return [
    "[Desktop Entry]",
    "Type=Application",
    `Name=${options.name}`,
    `Comment=${options.comment ?? "Open at login"}`,
    `Exec=${command}`,
    "Terminal=false",
    "X-GNOME-Autostart-enabled=true",
    "",
  ].join("\n");
}

export function writeLinuxAutostart(options: {
  homeDir: string;
  enabled: boolean;
  name: string;
  execPath: string;
  args?: readonly string[];
  comment?: string;
}): void {
  const file = linuxAutostartPath(options.homeDir);
  if (!options.enabled) {
    if (existsSync(file)) rmSync(file, { force: true });
    return;
  }
  mkdirSync(dirname(file), { recursive: true });
  writeFileSync(
    file,
    linuxAutostartEntry({
      name: options.name,
      execPath: options.execPath,
      args: options.args,
      comment: options.comment,
    }),
    { encoding: "utf8", mode: 0o644 },
  );
}
