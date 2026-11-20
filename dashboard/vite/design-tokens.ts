import { execFileSync } from "node:child_process";
import path from "node:path";
import type { Plugin } from "vite";

/**
 * Regenerate `src/styles/tokens.generated.css` whenever a token source changes.
 *
 * The TS tables under `src/styles/tokens/` are the single source of truth, so
 * editing them must refresh the CSS in the same dev loop; otherwise the running
 * page keeps using stale variables until someone runs the script by hand.
 */
export function designTokens(rootDir: string): Plugin {
  const script = path.join(rootDir, "scripts/gen-tokens.mjs");
  const sources = [
    path.join(rootDir, "src/styles/tokens/scales.ts"),
    path.join(rootDir, "src/styles/tokens/colors.ts"),
  ];

  const regenerate = () => {
    execFileSync(process.execPath, [script], { cwd: rootDir, stdio: "inherit" });
  };

  return {
    name: "octop-design-tokens",
    buildStart() {
      regenerate();
      for (const file of sources) this.addWatchFile(file);
    },
    handleHotUpdate({ file, server }) {
      if (!sources.includes(file)) return;
      regenerate();
      server.ws.send({ type: "full-reload" });
      return [];
    },
  };
}
