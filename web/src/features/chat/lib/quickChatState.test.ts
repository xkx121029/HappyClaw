import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  chatThreadIdFromPath,
  setActiveQuickChatThread,
  useQuickChatActive,
} from "./quickChatState";

describe("quickChatState", () => {
  it("reads the thread id from chat paths", () => {
    expect(chatThreadIdFromPath("/chat/55AK5S/thr_123")).toBe("thr_123");
    expect(chatThreadIdFromPath("/chat/55AK5S")).toBeNull();
    expect(chatThreadIdFromPath("/home")).toBeNull();
  });

  it("only marks the published quick thread as active", () => {
    const quick = renderHook(() => useQuickChatActive("thr_quick"));
    const normal = renderHook(() => useQuickChatActive("thr_normal"));
    expect(quick.result.current).toBe(false);

    act(() => setActiveQuickChatThread("thr_quick"));
    expect(quick.result.current).toBe(true);
    expect(normal.result.current).toBe(false);

    act(() => setActiveQuickChatThread(null));
    expect(quick.result.current).toBe(false);
  });
});
