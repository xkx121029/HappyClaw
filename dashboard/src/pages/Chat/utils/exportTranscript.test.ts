import { afterEach, describe, expect, it, vi } from "vitest";
import type { ChatMessage } from "../hooks/sseHelpers";
import {
  buildTranscriptLines,
  buildTranscriptMarkdown,
  downloadTextFile,
  messageExportText,
  sanitizeTranscriptFileName,
} from "./exportTranscript";

function msg(overrides: Partial<ChatMessage>): ChatMessage {
  return {
    id: "m1",
    role: "user",
    content: "",
    timestamp: 1_700_000_000_000,
    ...overrides,
  } as ChatMessage;
}

const labels = { user: "我", assistant: "助手", failed: "发送失败" };

describe("messageExportText", () => {
  it("优先取文本块并跳过 thinking", () => {
    const text = messageExportText(
      msg({
        role: "assistant",
        content: "legacy",
        contentBlocks: [
          { type: "thinking", content: "思路" },
          { type: "text", content: "回答" },
        ],
      }),
    );
    expect(text).toBe("回答");
  });

  it("无文本块时回退到 content", () => {
    expect(messageExportText(msg({ content: "  直接内容  " }))).toBe(
      "直接内容",
    );
    expect(messageExportText(msg({ contentBlocks: [] }))).toBe("");
  });
});

describe("buildTranscriptLines", () => {
  it("保留 user/assistant，跳过 system/tool 与空消息", () => {
    const lines = buildTranscriptLines(
      [
        msg({ id: "a", role: "system", content: "sys" }),
        msg({ id: "b", role: "tool", content: "tool" }),
        msg({ id: "c", content: "你好" }),
        msg({ id: "d", role: "assistant", content: "   " }),
        msg({ id: "e", role: "assistant", content: "你好呀" }),
      ],
      labels,
      () => "12:30",
    );
    expect(lines).toHaveLength(2);
    expect(lines[0]).toMatchObject({
      speaker: "我",
      time: "12:30",
      text: "你好",
      failedNote: "",
    });
    expect(lines[1]).toMatchObject({
      speaker: "助手",
      text: "你好呀",
      failedNote: "",
    });
  });

  it("status=error 的气泡带失败标记", () => {
    const lines = buildTranscriptLines(
      [msg({ role: "assistant", content: "断了", status: "error" })],
      labels,
      () => "",
    );
    expect(lines[0].failedNote).toBe("发送失败");
  });
});

describe("buildTranscriptMarkdown", () => {
  it("拼接标题、导出时间与条目分隔线，失败气泡附提示", () => {
    const markdown = buildTranscriptMarkdown(
      "周报",
      [
        { speaker: "我", time: "12:30", text: "你好", failedNote: "" },
        {
          speaker: "助手",
          time: "12:31",
          text: "断了",
          failedNote: "发送失败",
        },
      ],
      "导出于 2026-11-12 16:20",
    );
    expect(markdown).toContain("# 周报");
    expect(markdown).toContain("> 导出于 2026-11-12 16:20");
    expect(markdown).toContain("**我** · 12:30");
    expect(markdown).toContain("**助手** · 12:31");
    expect(markdown).toContain("> 发送失败");
    expect(markdown).toMatch(/\n---\n/);
    expect(markdown.endsWith("\n")).toBe(true);
  });

  it("无条目且无导出时间时只剩标题", () => {
    expect(buildTranscriptMarkdown("空会话", [])).toBe("# 空会话\n");
  });
});

describe("sanitizeTranscriptFileName", () => {
  it("去掉平台非法字符并压缩空白", () => {
    expect(sanitizeTranscriptFileName('a<b>c:"d/e\\f*g?h|i.txt', "兜底")).toBe(
      "a b c d e f g h i.txt",
    );
  });

  it("去掉首尾的点与空格并限长 80", () => {
    const long = "很长的标题".repeat(30);
    const name = sanitizeTranscriptFileName(`... ${long} ...`, "兜底");
    expect(name.length).toBeLessThanOrEqual(80);
    expect(name.startsWith(".")).toBe(false);
    expect(name.endsWith(".")).toBe(false);
  });

  it("空标题回退到兜底名", () => {
    expect(sanitizeTranscriptFileName("   ", "会话导出")).toBe("会话导出");
    expect(sanitizeTranscriptFileName("///", "会话导出")).toBe("会话导出");
  });
});

describe("downloadTextFile", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("创建 blob 链接触发下载并回收 URL", () => {
    const createObjectURL = vi.fn(() => "blob:fake");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL });
    const click = vi.fn();
    const createElement = vi
      .spyOn(document, "createElement")
      .mockImplementation(() => {
        const anchor = {
          href: "",
          download: "",
          click,
        } as unknown as HTMLAnchorElement;
        return anchor;
      });

    downloadTextFile("周报.md", "# 周报");

    expect(createObjectURL).toHaveBeenCalledTimes(1);
    const blob = createObjectURL.mock.calls[0][0] as Blob;
    expect(blob).toBeInstanceOf(Blob);
    expect(anchorDownloadedName(createElement)).toBe("周报.md");
    expect(click).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:fake");
  });

  function anchorDownloadedName(
    createElement: ReturnType<typeof vi.spyOn>,
  ): string {
    const anchor = createElement.mock.results[0].value as unknown as {
      download: string;
    };
    return anchor.download;
  }
});
