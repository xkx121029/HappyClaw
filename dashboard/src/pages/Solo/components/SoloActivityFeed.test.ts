import { describe, expect, it } from "vitest";
import {
  extractDiffLines,
  extractDiffStat,
  extractExitCode,
  summarizeCommandTail,
  tailOutput,
} from "./SoloActivityFeed";

describe("extractExitCode", () => {
  it("从常见写法里读出退出码", () => {
    expect(extractExitCode("[exit code: 0]")).toBe(0);
    expect(extractExitCode("Exit status 2")).toBe(2);
    expect(extractExitCode("process exited with exit 127")).toBe(127);
  });

  it("没有退出码时返回 null", () => {
    expect(extractExitCode("")).toBeNull();
    expect(extractExitCode("all good")).toBeNull();
  });
});

describe("tailOutput", () => {
  it("短输出原样返回", () => {
    expect(tailOutput("a\nb")).toBe("a\nb");
  });

  it("长输出只留尾部并标注省略行数", () => {
    const output = Array.from({ length: 50 }, (_, i) => `line ${i}`).join("\n");
    const tail = tailOutput(output, 10);
    expect(tail.startsWith("…（前面 40 行已省略）")).toBe(true);
    expect(tail).toContain("line 49");
    expect(tail).not.toContain("line 39\n");
  });
});

describe("summarizeCommandTail", () => {
  it("摘要取最后一行有内容的输出", () => {
    expect(summarizeCommandTail("step 1\nstep 2\n\n")).toBe("step 2");
  });
});

describe("extractDiffStat", () => {
  it("优先用输出里的 unified diff 统计行数", () => {
    const output = [
      "diff --git a/a.ts b/a.ts",
      "--- a/a.ts",
      "+++ b/a.ts",
      "@@ -1,2 +1,3 @@",
      "-old line",
      "+new line",
      "+another line",
    ].join("\n");
    const stat = extractDiffStat(null, output);
    expect(stat).toMatchObject({ added: 2, removed: 1, preview: "new line" });
    expect(stat?.lines.map((line) => line.type)).toEqual([
      "context",
      "del",
      "add",
      "add",
    ]);
  });

  it("没有 diff 时按 old/new 参数估算", () => {
    const stat = extractDiffStat({
      file_path: "src/a.ts",
      old_string: "const a = 1;",
      new_string: "const a = 2;\nconst b = 3;",
    });
    expect(stat).toMatchObject({ added: 2, removed: 1, preview: "const a = 2;" });
    expect(stat?.lines).toEqual([
      { type: "del", text: "const a = 1;" },
      { type: "add", text: "const a = 2;" },
      { type: "add", text: "const b = 3;" },
    ]);
  });

  it("读文件这类没有改动的动作不产生 diff 摘要", () => {
    expect(extractDiffStat({ file_path: "src/a.ts" }, "hello")).toBeNull();
  });
});

describe("extractDiffLines", () => {
  it("解析 patch 参数里的增删行，并丢掉文件头", () => {
    const lines = extractDiffLines({
      patch: [
        "*** Begin Patch",
        "*** Update File: src/a.ts",
        "@@",
        "-old",
        "+new",
        "*** End Patch",
      ].join("\n"),
    });
    expect(lines.map((line) => [line.type, line.text])).toEqual([
      ["context", "@@"],
      ["del", "old"],
      ["add", "new"],
    ]);
  });

  it("写文件只有 content 时整段按新增行展示", () => {
    const lines = extractDiffLines({
      file_path: "src/new.ts",
      content: "line 1\nline 2",
    });
    expect(lines).toEqual([
      { type: "add", text: "line 1" },
      { type: "add", text: "line 2" },
    ]);
  });
});
