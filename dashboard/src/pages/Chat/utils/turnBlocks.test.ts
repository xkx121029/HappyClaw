import { describe, expect, it } from "vitest";
import type { ChatMessage } from "../hooks/useChat";
import { buildTurnBlocks, planTurnBlocks } from "./turnBlocks";

function message(
  extra: Partial<ChatMessage> & Pick<ChatMessage, "id">,
): ChatMessage {
  return {
    role: "assistant",
    content: "",
    status: "done",
    timestamp: 1,
    ...extra,
  };
}

function tool(id: string, extra: Partial<ChatMessage> = {}): ChatMessage {
  return message({
    id,
    toolData: { name: "execute", arguments: "{}" },
    ...extra,
  });
}

describe("buildTurnBlocks", () => {
  it("keeps narration and tool runs in time order", () => {
    const blocks = buildTurnBlocks([
      message({ id: "t1", content: "先看下目录" }),
      tool("tool1"),
      message({ id: "t2", content: "目录里只有一个文件" }),
      tool("tool2"),
      message({ id: "t3", content: "改好了" }),
    ]);

    expect(blocks.map((block) => block.kind)).toEqual([
      "text",
      "process",
      "text",
      "process",
      "text",
    ]);
    expect(
      blocks.flatMap((block) =>
        block.kind === "text" ? [block.message.content] : [],
      ),
    ).toEqual(["先看下目录", "目录里只有一个文件", "改好了"]);
  });

  it("reconstructs interleaved blocks kept inside one legacy row", () => {
    const blocks = buildTurnBlocks([
      message({
        id: "legacy",
        content: "第一段第二段",
        contentBlocks: [
          { type: "text", content: "第一段" },
          { type: "thinking", content: "想一想" },
          { type: "text", content: "第二段" },
        ],
      }),
    ]);

    expect(blocks.map((block) => block.kind)).toEqual([
      "text",
      "process",
      "text",
    ]);
    const process = blocks[1];
    expect(process.kind === "process" && process.steps[0].kind).toBe(
      "thinking",
    );
  });

  it("marks failed tools and keeps their error code", () => {
    const blocks = buildTurnBlocks([
      tool("boom", { status: "error", errorInfo: { code: "tool_error" } }),
    ]);
    const process = blocks[0];
    expect(process.kind).toBe("process");
    if (process.kind !== "process") return;
    expect(process.steps[0].kind).toBe("tool");
    expect(
      process.steps[0].kind === "tool" &&
        process.steps[0].message.status === "error",
    ).toBe(true);
  });

  it("routes pinned rich tool UIs into their own block", () => {
    const blocks = buildTurnBlocks([tool("chart"), tool("plain")], {
      isPinnedTool: (msg) => msg.id === "chart",
    });
    expect(blocks.map((block) => block.kind)).toEqual(["toolCard", "process"]);
  });

  it("splits the approval card into position", () => {
    const blocks = buildTurnBlocks([
      message({ id: "t1", content: "要执行命令" }),
      message({
        id: "card",
        hitlData: { action_requests: [{ name: "execute" }], status: "pending" },
      }),
      message({ id: "t2", content: "命令执行完了" }),
    ]);
    expect(blocks.map((block) => block.kind)).toEqual(["text", "hitl", "text"]);
  });
});

describe("planTurnBlocks", () => {
  it("leaves a single-text turn as per-step rows", () => {
    const planned = planTurnBlocks(
      buildTurnBlocks([
        tool("a"),
        tool("b"),
        message({ id: "t", content: "好了" }),
      ]),
    );
    const process = planned.find((block) => block.kind === "process");
    expect(process?.kind === "process" && process.merged).toBe(false);
  });

  it("folds earlier steps once a second text segment appears", () => {
    const planned = planTurnBlocks(
      buildTurnBlocks([
        message({ id: "t1", content: "先读文件", timestamp: 1000 }),
        tool("a", { timestamp: 2000 }),
        message({ id: "t2", content: "读完了", timestamp: 5000 }),
        tool("b", { timestamp: 6000 }),
        message({ id: "t3", content: "改完了", timestamp: 12000 }),
      ]),
    );

    expect(planned.map((block) => block.kind)).toEqual([
      "text",
      "process",
      "text",
      "text",
    ]);
    const group = planned[1];
    expect(group.kind).toBe("process");
    if (group.kind !== "process") return;
    expect(group.merged).toBe(true);
    expect(group.steps).toHaveLength(2);
    expect(group.durationMs).toBe(10000);
    expect(group.failedCount).toBe(0);
  });

  it("does not invent a duration when history has no timestamps", () => {
    const planned = planTurnBlocks(
      buildTurnBlocks([
        message({ id: "t1", content: "先读文件", timestamp: 0 }),
        tool("a", { timestamp: 0 }),
        message({ id: "t2", content: "读完了", timestamp: 0 }),
      ]),
    );
    const group = planned.find((block) => block.kind === "process");
    expect(group?.kind === "process" && group.durationMs).toBe(null);
  });

  it("counts failed tools in the folded group", () => {
    const planned = planTurnBlocks(
      buildTurnBlocks([
        message({ id: "t1", content: "开始", timestamp: 1000 }),
        tool("a", { status: "error", timestamp: 2000 }),
        message({ id: "t2", content: "失败了", timestamp: 3000 }),
      ]),
    );
    const group = planned.find((block) => block.kind === "process");
    expect(group?.kind === "process" && group.failedCount).toBe(1);
  });
});
