# 前端视觉方向：A 仪器 / B 读本 / C 工作台

这一轮只做方向探索，不铺页面。三个方向各自独立成一套视觉语言，落在同一批
20 个共享组件上：方向不改组件代码，只换 `html[data-direction]` 作用域下的语义
令牌，加上各自不同的页面骨架。选定之前，业务页面（Chat、Settings、Home…）一行没动。

```
/directions            三个方向的对照入口
/directions/a/chat     方向 A 会话页
/directions/a/design   方向 A 设计系统页
…                      b、c 同理
```

## 三个方向不是一套皮

| | A · 仪器 | B · 读本 | C · 工作台 |
| --- | --- | --- | --- |
| 给谁 | 整天把界面和终端并排放的技术用户 | 把对话当文稿读、一天结束要回看的人 | 不想学界面、只想知道「现在在做什么」的人 |
| 骨架 | 236 索引栏 + 主线（88px 角色槽）+ 272 仪表栏 | 268 目录 + 书页（书眉、版心 660、旁注 180） | 64 图标栏 + 288 会话列表 + 主栏 + 320 运行面板 + 悬浮输入坞 |
| 信息形状 | 逐行规格表，编号、等宽时间戳、刻度条 | 段落与脚注，工具调用是旁注 | 托盘，每块面板一个角色 |
| 字体 | Segoe UI Variable / Noto Sans SC + Cascadia Mono | 正文 Noto Serif SC 16/1.95，界面 Noto Sans SC | Noto Sans SC + Segoe UI |
| 彩色 | 无彩；只有状态色（蓝 `#1B44C8` / `#7B9BFF`） | 朱砂一枚（`#A63A22` / `#D2674A`） | 青瓷（`#3E7D6B` / `#64B79B`） |
| 圆角 | 0–2px | 0–3px | 6–22px |
| 层次 | 1px 线，没有阴影 | 纸色差 + 细线 | 四档短而软的阴影 |
| 空态 | 会显得空（要有真数据撑） | 像一张还没写的纸 | 最好过 |

## 令牌表

### A · 仪器

| 角色 | 浅 | 深 |
| --- | --- | --- |
| canvas | `#FAFAF8` | `#0B0B0A` |
| surface | `#FFFFFF` | `#111110` |
| raised | `#FFFFFF` | `#151514` |
| sunken | `#F2F2EF` | `#080807` |
| fg | `#131311` | `#EDEDE8` |
| fg-muted | `#55554F` | `#A3A39B` |
| fg-subtle | `#6B6B62` | `#7C7C74` |
| line | `#D7D7D1` | `#262622` |
| accent（按钮＝墨色） | `#17170F`（字 `#FBFBF7`） | `#EDEDE8`（字 `#0B0B0A`） |
| signal（焦点/链接/在线） | `#1B44C8` | `#7B9BFF` |
| 字阶 | 12 / 12 / 13 / 13.5 / 16 / 17 / 20 / 24 px | 同 |
| 圆角 | 0 / 2 / 2 / 2 / 2 / 3 px，`full` 也是 2px（徽标成方块） | 同 |
| 阴影 | `xs`/`sm`/`md` 全部归零，换成 `0 0 0 1px` 线；只有浮层有 24px 模糊 | 同 |

### B · 读本

| 角色 | 浅 | 深 |
| --- | --- | --- |
| canvas（桌面色） | `#EAE3D4` | `#14110C` |
| surface（纸面） | `#F7F2E7` | `#1A1610` |
| raised | `#FBF7EE` | `#201B14` |
| sunken | `#E5DDCB` | `#100D09` |
| fg | `#1E1A14` | `#EDE3D2` |
| fg-muted | `#5C5344` | `#B0A48E` |
| fg-subtle | `#6D6453` | `#8C8069` |
| line | `#D7CDB9` | `#332C22` |
| 朱砂 accent | `#A63A22` | `#D2674A` |
| 行距 | 正文 1.95，界面 1.75 | 同 |
| 圆角 | 0 / 0 / 2 / 2 / 3 / 4 px | 同 |
| 版心 | 660px 正文 + 180px 旁注 + 40px 间隔（总 880） | 同 |

### C · 工作台

| 角色 | 浅 | 深 |
| --- | --- | --- |
| canvas | `#F3F1EC` | `#101312` |
| surface（托盘） | `#FFFFFF` | `#171B19` |
| raised | `#FFFFFF` | `#1C211F` |
| sunken | `#EAE7E0` | `#0B0E0D` |
| fg | `#1B1D1B` | `#E9EDEA` |
| fg-muted | `#575E59` | `#A7AFAA` |
| fg-subtle | `#6B716C` | `#838C87` |
| line | `#E1DED7` | `#272C2A` |
| 青瓷 accent | `#3E7D6B`（字 `#FFFFFF`） | `#64B79B`（字 `#08201A`） |
| 字阶 | 12 / 12 / 13 / 14 / 16 / 18 / 22 / 28 px | 同 |
| 圆角 | 6 / 8 / 10 / 14 / 18 / 22 px | 同 |
| 阴影 | 四档，短而软（`0 3px 10px -4px` → `0 34px 60px -30px`） | 同 |

## 三条硬约束怎么落的

- **中文优先**：正文 14px（手机 16px），标签与元信息最低 12px，全部走 Noto Sans SC
  / Noto Serif SC；B 的正文用宋体 + `text-align: justify; text-justify: inter-character`。
- **深浅两套**：每个方向两条令牌块，`html[data-direction="x"]:not(.dark)` 与
  `html[data-direction="x"].dark`。浅色那条必须写 `:not(.dark)`，否则会输给
  `tokens.css` 里的 `:root:not(.dark)`（特异性 0,2,0）。
- **390×844**：三栏在 `lg` 以下折叠——A 换成顶部线程条 + 隐藏仪表栏，B 换成横排
  目录 + 旁注并进正文，C 隐藏图标栏与会话列表、输入坞贴底。

## 复核方式

本环境无法在本回合内看图，所以视觉复核由两组程序化断言兜底，图片本身交给你判断：

```bash
npm i --no-save playwright-core
npx vite --host 127.0.0.1 --port 5175 &
node scripts/shoot-directions.mjs http://127.0.0.1:5175   # 18 张 PNG + verification.json
node scripts/audit-directions.mjs http://127.0.0.1:5175   # 字体解析、对比度、最小字号、溢出、触控尺寸
```

`audit-directions.mjs` 会把半透明角色（`accent-soft`）先合成到画布色再算对比度，
否则 `rgba()` 的 alpha 会被当成实色，量出 1.17 这种假数字。

当前结果：六种组合最低对比度 4.49:1，最小字号 12px，无横向溢出，手机端可点元素
全部 ≥40px，控制台 0 错误。
