import assert from "node:assert/strict";
import { existsSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";

import {
  linuxAutostartEntry,
  linuxAutostartPath,
  quoteExecArg,
  writeLinuxAutostart,
} from "./auto-launch";

test("autostart lives under the XDG config dir", () => {
  assert.equal(
    linuxAutostartPath("/home/me"),
    join("/home/me", ".config", "autostart", "happyclaw.desktop"),
  );
});

test("exec arguments with spaces or quotes stay one argument", () => {
  assert.equal(quoteExecArg("/opt/Happy Claw/happyclaw"), '"/opt/Happy Claw/happyclaw"');
  assert.equal(quoteExecArg('a"b'), '"a\\"b"');
});

test("the entry launches the packaged executable", () => {
  const entry = linuxAutostartEntry({
    name: "HappyClaw",
    execPath: "/opt/HappyClaw/happyclaw",
    comment: "Open at login",
  });
  assert.match(entry, /^\[Desktop Entry\]$/m);
  assert.match(entry, /^Type=Application$/m);
  assert.match(entry, /^Exec="\/opt\/HappyClaw\/happyclaw"$/m);
  assert.match(entry, /^X-GNOME-Autostart-enabled=true$/m);
});

test("dev launches also pass the app directory", () => {
  const entry = linuxAutostartEntry({
    name: "HappyClaw",
    execPath: "/repo/node_modules/electron/dist/electron",
    args: ["/repo/desktop/src"],
  });
  assert.match(
    entry,
    /^Exec="\/repo\/node_modules\/electron\/dist\/electron" "\/repo\/desktop\/src"$/m,
  );
});

test("turning the setting off removes the entry", () => {
  const home = mkdtempSync(join(tmpdir(), "octop-autostart-"));
  writeLinuxAutostart({
    homeDir: home,
    enabled: true,
    name: "HappyClaw",
    execPath: "/opt/happyclaw",
  });
  const file = linuxAutostartPath(home);
  assert.equal(existsSync(file), true);
  assert.match(readFileSync(file, "utf8"), /Name=HappyClaw/);

  writeLinuxAutostart({
    homeDir: home,
    enabled: false,
    name: "HappyClaw",
    execPath: "/opt/happyclaw",
  });
  assert.equal(existsSync(file), false);
});
