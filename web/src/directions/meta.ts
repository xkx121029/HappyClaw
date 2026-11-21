import type { DirectionId } from "@/directions/scope";

export const directionMeta: Record<
  DirectionId,
  { name: string; subtitle: string; note: string }
> = {
  a: {
    name: "方向 A · 仪器",
    subtitle: "无彩版式，状态色唯一",
    note: "指数栏 / 主线 / 仪表栏三栏，等宽字承载数字，1px 线代替阴影。",
  },
  b: {
    name: "方向 B · 读本",
    subtitle: "暖纸宋体，朱砂一枚",
    note: "对话当文稿读，工具调用退到旁注栏，目录代替线程列表。",
  },
  c: {
    name: "方向 C · 工作台",
    subtitle: "青瓷点缀，托盘分层",
    note: "圆角托盘与柔和层次，右侧运行面板，悬浮输入坞。",
  },
};
