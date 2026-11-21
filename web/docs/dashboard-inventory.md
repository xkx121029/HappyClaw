# HappyClaw dashboard → `web/` migration inventory

Read-only inventory of `dashboard/` (React 18 + antd 5 + react-router 7 + less) as the source of truth for a rewrite in `web/` (Vite + React + TS + Tailwind + TanStack Router/Query + zustand + i18next).

All numbers measured on this worktree, Nov 21 2026.

## 0. Scale

| Metric | Value |
|---|---|
| `dashboard/src` TS/TSX | **258,748 lines / 1,316 files** |
| `dashboard/src` LESS/CSS | **59,282 lines / 174 files** |
| Total source to consider | 318,030 lines |
| Entries in `routeConfigs` | **73** (`routes/index.tsx`, 330 lines) |
| Real page components | **30** modules across 35 real route entries (+`pages/Setup`, outside the shell) |
| Pure redirect entries | **38** (+3 more in `App.tsx`) |
| Mobile tree (`mobile/MobileRoutes.tsx`) | 33 files, **6,803 lines**, 13 pages under `/m/*` |
| i18n | `locales/en.json` 481,837 B, `zh.json` 468,356 B, **97 top-level namespaces** |
| API modules | **67** files in `api/modules/` (5 are tests → 62 live) |
| Backend routers | **81** files in `src/octop/api/routers/` (64 root + `browser/`5 + `chat/`7 + `desktop/`5), mounted via `app.py:493-565` |

Concentration: Chat + Experts + Memory + CloudHosts + Models = **130k lines**, ~50% of all TS/TSX.

---

## (a) Route table

`routes/index.tsx` is the single registry; `layouts/MainLayout/index.tsx` mounts it through `react-router`'s `<Routes>` and decides chrome. Flags come from `FULLSCREEN_PATHS`, `SELF_HEADER_PATHS`, `MOBILE_FULLSCREEN_PATHS` (empty) and `MainLayout`:

- **FS** = fullscreen (no page padding/scroll wrapper; `PageStage` without `.page-content`)
- **SH** = self-header (renders its own mobile header, global `<Header>` suppressed)
- **WRAP** = `useWrapper: true`, element is `null` in the registry and `ChatWithKey` (i.e. `pages/Chat`) is substituted at mount
- **KA** = keep-alive: element `null`; `pages/Control/Workbench` is mounted once in `MainLayout` and hidden/shown with `display:none` + `isVisible` prop
- **IMM** = immersive: hides the sidebar and the mobile tab bar (`isSoloRoute || isWorkbenchPath || isRemoteDesktopPath`)

### Real routes

| Path | Component | FS | SH | WRAP | KA | IMM | Notes |
|---|---|---|---|---|---|---|---|
| `/home` | `pages/Home` | – | – | – | – | – | default landing; `/` redirects here |
| `/chat` | `pages/Chat` | ✔ | ✔ | ✔ | – | – | |
| `/chat/:agentId` | `pages/Chat` | ✔ | ✔ | ✔ | – | – | same component, params only (no remount by design) |
| `/chat/:agentId/:threadId` | `pages/Chat` | ✔ | ✔ | ✔ | – | – | |
| `/mobile/sessions` | `pages/Mobile/MobileSessions` | – | – | – | – | – | phone-connector sessions |
| `/mobile/control` | `pages/Mobile/MobileControl` | – | – | – | – | – | |
| `/mobile/info` | `pages/Mobile/MobileInfo` | – | – | – | – | – | device link info |
| `/solo` | `pages/Solo` | ✔ | – | – | – | ✔ | standalone workspace: chat + editor + terminal + file tree |
| `/bao` | `components/Bao/BaoPage` | ✔ | ✔ | – | – | – | router UI; project scope via `?project=` |
| `/experts` | `pages/Experts` | – | – | – | – | – | |
| `/tasks` | `pages/Control/CronJobs` | – | – | – | – | – | |
| `/connectors` | `pages/Agent/Connectors` | – | – | – | – | – | |
| `/skill-packages` | `pages/SkillPackages` | – | – | – | – | – | |
| `/knowledge-bases` | `pages/KnowledgeBases` | – | – | – | – | – | |
| `/bridge` | `pages/Settings/Bridge` (16 lines → `AdvancedSettings/BridgeSettings`) | – | – | – | – | – | |
| `/personalization/*` | `pages/Agent/Personalization` | – | – | – | – | – | tabbed: skills, subagents, tools, plugins, mbti, bao, memory, channels |
| `/token-usage` | `pages/Control/TokenUsage` | – | – | – | – | – | |
| `/acp` | `pages/Agent/ACP` | – | – | – | – | – | |
| `/workbench` | `pages/Control/Workbench` | ✔ | – | – | ✔ | ✔ | shell only (118 lines), tabs below |
| `/workbench/terminal` | ↳ `pages/Control/Terminal` | ✔ | – | – | ✔ | ✔ | `embedded` prop |
| `/workbench/browser` | ↳ `pages/Control/RemoteBrowser` | ✔ | – | – | ✔ | ✔ | `embedded` prop |
| `/workbench/cloud` | ↳ `pages/Control/CloudHosts` | ✔ | – | – | ✔ | ✔ | CVM/Tencent Cloud control plane |
| `/remote-desktop` | `pages/Control/RemoteDesktop` | ✔ | – | – | – | ✔ | tab from path suffix |
| `/remote-desktop/desktop` | same | ✔ | – | – | – | ✔ | |
| `/remote-desktop/link` | same | ✔ | – | – | – | ✔ | |
| `/remote-desktop/pair` | same | ✔ | – | – | – | ✔ | not in `pathToKey` |
| `/admin/models` | `pages/Settings/Models` | – | – | – | – | – | embeds Voice, SearchConfig, MediaGeneration, Embedding panels |
| `/admin/backend` | `pages/Admin/Storage` | – | – | – | – | – | |
| `/admin/plugins` | `pages/Admin/Plugins` | – | – | – | – | – | |
| `/admin/advanced` | `pages/Settings/AdvancedSettings` | – | – | – | – | – | embeds Environments, Observability, BackupRestore, HttpsSettings, PhoneAccess |
| `/admin/security` | `pages/Settings/Security` | – | – | – | – | – | `?tab=audit` |
| `/agent-config` | `pages/Agent/Config` | – | – | – | – | – | |
| `/pwa-debug` | `pages/PwaDebug` | – | – | – | – | – | no nav entry, URL only |
| `/motion-preview` | `pages/MotionPreview` | – | – | – | – | – | no nav entry, design QA only |
| `*` | `components/NotFoundPage` | – | – | – | – | – | 23 lines |

Out-of-shell routes in `App.tsx`: `/setup` → `pages/Setup` (3,317 lines, 8 files, outside `AuthGuard`); `/login`, `/login/*`, `/invite` → `Navigate` to `/chat`.

### Redirects (38, all `replace`, most via `RedirectPreserveSearch` which keeps `?search` + `#hash`)

| Group | Paths → target |
|---|---|
| Legacy top-level | `/` → `/home`; `/workspace` → `/experts`; `/sessions` → `/chat`; `/cron-jobs` → `/tasks`; `/models` → `/admin/models`; `/plugins` → `/admin/plugins`; `/updates` → `/admin/advanced?tab=updates`; `/advanced-settings` → `/admin/advanced`; `/environments` → `/admin/advanced` |
| Personalization merge | `/skills` → `/personalization/skills`; `/channels` → `/personalization/channels`; `/subagents` → `/personalization/subagents`; `/mbti` → `/personalization/mbti`; `/memory` → `/personalization/memory`; `/personalization/acp` → `/acp` |
| Workbench | `/terminal` → `/workbench/terminal`; `/remote-browser` → `/workbench/browser` |
| Remote desktop | `/remote-phone`, `/remote-android`, `/remote-desktop/phone`, `/remote-desktop/phone/screen`, `/remote-desktop/phone/shell` → `/remote-desktop/link` |
| Admin | `/admin/users`, `/admin/sso`, `/admin/agents` → `/chat`; `/admin/shared-models` → `/admin/models`; `/admin/audit` → `/admin/security?tab=audit`; `/admin/voice` → `/admin/models?tab=voice`; `/admin/updates` → `/admin/advanced?tab=updates`; `/admin/storage` → `/admin/backend` |
| Orca/Octop-era bookmarks | `/orca/cron`, `/octop/cron` → `/tasks`; `/orca/channels`, `/octop/channels` → `/channels`; `/orca/admin/users`, `/octop/admin/users` → `/chat`; `/orca/admin/audit`, `/octop/admin/audit` → `/admin/security?tab=audit` |

### Mobile tree (`mobile/`, mounted instead of `MainLayout` when `useIsMobile()`)

`/m/home`, `/m/quick`, `/m/chat`, `/m/chat/:agentId`, `/m/chat/:agentId/:threadId`, `/m/experts`, `/m/bao`, `/m/tasks`, `/m/connectors`, `/m/knowledge-bases`, `/m/token-usage`, `/m/personalization[/\*]`, `/m/admin[/:section]`, `/m/more` — plus desktop paths re-pointed into `/m/*` on a phone viewport, and `/skills`, `/skill-packages`, `/agent-config`, `/bridge`, `/acp` → `/m/more`.

---

## (b) Page inventory

LOC = TS/TSX only, tests included. `less`/`antd` = number of files importing `.module.less` / `from "antd"`.

| Page module | Dir | Entry | Files | LOC | less | antd | Heavy deps | Class |
|---|---|---|---|---|---|---|---|---|
| Home | `pages/Home` | `index.tsx` | 11 | 5,534 | 4 | 2 | — | rewrite |
| Chat | `pages/Chat` | `index.tsx` (2,890) | 303 | 62,719 | 71 | 40 | — (markdown/katex/mermaid via `components/Markdown`) | rewrite (split) |
| Chat · components | `pages/Chat/components` | — | 139 | 30,702 | | | | |
| Chat · hooks | `pages/Chat/hooks` | `chatStore.ts` (4,392) | 78 | 20,840 | | | — | reuse-logic |
| Chat · utils | `pages/Chat/utils` | — | 92 | 10,406 | | | — | reuse-logic |
| MobileSessions | `pages/Mobile/MobileSessions` | `index.tsx` | 1 | 275 | 0 | 1 | — | delete |
| MobileControl | `pages/Mobile/MobileControl` | `index.tsx` | 1 | 223 | 0 | 1 | — | delete |
| MobileInfo | `pages/Mobile/MobileInfo` | `index.tsx` | 1 | 645 | 1 | 1 | — | delete |
| Solo | `pages/Solo` | `index.tsx` | 21 | 4,988 | 14 | 6 | monaco (1) | rewrite |
| Bao | `components/Bao` | `BaoPage.tsx` | 9 | 2,575 | 3 | 3 | — | rewrite |
| Experts | `pages/Experts` | `index.tsx` | 67 | 15,188 | 24 | 28 | — | rewrite (split) |
| CronJobs (`/tasks`) | `pages/Control/CronJobs` | `index.tsx` | 17 | 3,535 | 5 | 6 | — | rewrite |
| Connectors | `pages/Agent/Connectors` | `index.tsx` | 22 | 5,927 | 7 | 7 | — | rewrite |
| SkillPackages | `pages/SkillPackages` | `index.tsx` | 6 | 1,876 | 4 | 4 | — | rewrite |
| KnowledgeBases | `pages/KnowledgeBases` | `index.tsx` | 12 | 5,082 | 2 | 2 | — | rewrite |
| Bridge | `pages/Settings/Bridge` | `index.tsx` (16) | 1 | 16 | 0 | 0 | — | delete (merge into Advanced) |
| Personalization | `pages/Agent/Personalization` | `index.tsx` | 8 | 2,514 | 6 | 6 | — | rewrite |
| ↳ Skills tab | `pages/Agent/Skills` | `components/SkillsTabs` | 32 | 7,901 | 11 | 13 | — | rewrite |
| ↳ Tools tab | `pages/Agent/Tools` | `ToolsTabs` | 4 | 812 | 2 | 1 | — | rewrite |
| ↳ Memory tab | `pages/Agent/Memory` | `MemoryPanel` | 48 | 15,336 | 10 | 25 | recharts (2) | rewrite |
| ↳ Channels tab | `pages/Agent/Channels` | `ChannelsPanel` | 11 | 4,898 | 3 | 3 | — | rewrite |
| ↳ Subagents tab | `pages/Experts/components/SubagentManager` | — | (in Experts) | — | — | — | — | rewrite |
| TokenUsage | `pages/Control/TokenUsage` | `index.tsx` | 5 | 1,574 | 2 | 2 | recharts (1) | rewrite |
| ACP | `pages/Agent/ACP` | `index.tsx` | 4 | 765 | 3 | 3 | — | rewrite |
| Workbench shell | `pages/Control/Workbench` | `index.tsx` (118) | 1 | 118 | 1 | 0 | — | rewrite |
| ↳ Terminal | `pages/Control/Terminal` | `index.tsx` | 14 | 3,435 | — | — | xterm (4) | rewrite |
| ↳ RemoteBrowser | `pages/Control/RemoteBrowser` | `index.tsx` | 2 | 1,696 | — | — | — | rewrite |
| ↳ CloudHosts | `pages/Control/CloudHosts` | `index.tsx` | 20 | 11,040 | — | — | recharts (1) | rewrite |
| RemoteDesktop | `pages/Control/RemoteDesktop` | `index.tsx` | 4 | 1,791 | 2 | 2 | — | rewrite |
| Models | `pages/Settings/Models` | `index.tsx` | 36 | 8,572 | 19 | 23 | — | rewrite |
| ↳ + embedded panels | `Settings/{Voice,SearchConfig,MediaGeneration}` + `Models/components/EmbeddingSettingsPanel` | — | — | — | — | — | — | rewrite |
| Storage | `pages/Admin/Storage` | `index.tsx` | 9 | 2,541 | 5 | 5 | — | rewrite |
| Plugins | `pages/Admin/Plugins` | `index.tsx` | 9 | 2,444 | 4 | 5 | — | rewrite |
| AdvancedSettings | `pages/Settings/AdvancedSettings` | `index.tsx` | 12 | 4,489 | 8 | 6 | — | rewrite |
| ↳ + embedded panels | `Settings/{Environments,Observability,BackupRestore,HttpsSettings,PhoneAccess}` | — | — | — | — | — | — | rewrite |
| Security | `pages/Settings/Security` | `index.tsx` | 6 | 1,429 | 4 | 4 | — | rewrite |
| AgentConfig | `pages/Agent/Config` | `index.tsx` | 3 | 290 | 1 | 1 | — | reuse-logic |
| Setup | `pages/Setup` | `index.tsx` | 8 | 3,317 | — | — | — | rewrite |
| PwaDebug | `pages/PwaDebug` | `index.tsx` | 1 | 710 | 0 | 0 | — | delete |
| MotionPreview | `pages/MotionPreview` | `index.tsx` | 2 | 796 | 1 | 1 | — | delete |
| NotFound | `components/NotFoundPage` | `NotFoundPage.tsx` (23) | 3 | 23 | 1 | 0 | — | rewrite (trivial) |

**Orphan/unrouted dirs** (no `routeConfigs` entry — embedded only): `pages/Invite`, `pages/Login` (dead, redirect only), `pages/Admin/SharedModels` (111 lines, unreachable since `/admin/shared-models` redirects), `pages/Chat/Weather` (240 lines, used by Chat), `pages/Agent/Workspace` (17 files, 3,634 lines — consumed by Solo/Chat file trees), `pages/Settings/octop`, `pages/Settings/Language`.

**Dependency reality check:** only 8 non-test files in all of `pages/` touch a heavy renderer, and all heavy code lives in `components/`:

| Component | Lines | Package | Consumers |
|---|---|---|---|
| `components/Markdown/index.tsx` | 450 | react-markdown, remark-gfm/math, rehype-katex, mermaid | Chat, Bao, Solo, Memory |
| `components/Markdown/mermaidLoader.ts` | – | mermaid 11 (lazy) | same |
| `components/DocumentPreviewCore.tsx` | 780 | docx-preview, xlsx, pptx-renderer, monaco, react-pdf | Chat file preview, KnowledgeBases |
| `components/PdfDocumentPreview.tsx` | 952 | react-pdf 10 | same |
| `components/monaco.ts` | 12 | `@monaco-editor/react` loader config | Solo, Agent/Workspace |
| `pages/Control/Terminal/*` | 3,435 | `@xterm/xterm` 5.5 + fit/web-links addons | Terminal, Solo |

---

## (c) API surface per page

`api/request.ts` (833 lines) is the only transport: `getApiUrl()` prefixes `/api`, `Authorization: Bearer` from `localStorage`, `Accept-Language`, optional `X-Octop-Agent-Id`, 401 → `octop:unauthorized` event, error envelope parsed into `ApiHttpError`. WebSockets go through `getWsUrl()` (adds `octop_token` query for phone clients).

| Page | API modules (`api/modules/*.ts`) | Backend router mount (`app.py`) |
|---|---|---|
| Home | `runtime`, `agentTools`, `bao`, `connectorPair`, `hitlPending`, `octopThreads`, `provider`, `wsChat`, `wsNotifications` | `/api/agents/{id}/…`, `/api/bao`, `/api/connector`, `/api/notifications` (WS), `/api/agents/{id}/chat/ws` |
| Chat | `agentChat`, `octopThreads`, `octopAgents`, `wsChat`, `upload`, `trajectory`, `slash`, `subagents`, `browser`, `connectors`, `knowledgeBases`, `projects`, `provider`, `preferences`, `settings`, `textAssist`, `auth` | `/api/agents/{id}/chat` (SSE), `/api/agents/{id}/chat/ws` (WS), `/api/agents/{id}/threads`, `/api/agents/{id}/trajectory`, `/api/agents/{id}/upload`, `/api/slash`, `/api/subagents`, `/api/subagent-catalog`, `/api/projects`, `/api/preferences`, `/api/knowledge-bases`, `/api/connector-instances` |
| Solo | `workspace` (+ direct `request`) | `/api/agents/{id}/workspace`, `/api/agent`, `/api/agents/{id}/terminal` |
| Bao | `bao`, `octopThreads`, `provider` | `/api/bao/{overview,tasks,chat,route,settings,dispatch}` |
| Experts | `octopAgents`, `agentChat`, `publishedExperts`, `expertMarket`, `subagents`, `teams`, `skillPackages`, `knowledgeBases`, `connectors`, `userGroups`, `workspace` | `/api/experts`, `/api/agents`, `/api/teams`, `/api/user-groups` |
| Tasks (CronJobs) | `cronjob`, `agentChat`, `connectors`, `octopThreads`, `provider` | `/api/cron`, `/api/agents/{id}/cron` |
| Connectors | `connectors`, `userGroups` | `/api/connectors`, `/api/connector-instances`, `/api/user-groups` |
| SkillPackages | `skillPackages`, `expertMarket`, `auth`, `userGroups` | `/api/skill-packages`, `/api/experts`, `/api/user-groups` |
| KnowledgeBases | `knowledgeBases`, `auth`, `userGroups` | `/api/knowledge-bases` |
| Personalization | `plugins` (+`api/index`), `mbti` via components | `/api/plugins`, `/api/mbti`, `/api/agents/{id}/skills`, `/api/agents/{id}/tools`, `/api/agents/{id}/memory`, `/api/agents/{id}/channels`, `/api/agents/{id}/subagents` |
| TokenUsage | direct `request("/admin/usage/summary")` | `/api/admin/usage/summary` (`routers/usage.py`, `usage.admin_router`) |
| ACP | `acp` | `/api/acp`, `/api/agents/{id}/acp` |
| Workbench · Terminal | `terminalAi`, `provider` | `/api/agents/{id}/terminal` (WS), `/api/agents/{id}/terminal/ai` |
| Workbench · Browser | `browser`, `preferences` | `/api/browser`, `/api/browser-stream` (WS) |
| Workbench · CloudHosts | direct `request("/cloud/*")` | `/api/cloud/{status,regions,authorize,callback,action,refresh,import-from-tccli,instances,metrics}` |
| RemoteDesktop | `desktop`, `connectorPairing` | `/api/desktop`, `/api/desktop-stream` (WS), `/api/connector`, `/api/device-link` |
| Models | `provider`, `decision`, `ollamaModel`, `onnxModel`, `onnxDownloadWatcher`, `preferences`, `userGroups` | `/api/admin/providers`, `/api/providers`, `/api/ollama-models`, `/api/onnx-models`, `/api/settings`, `/api/admin/voice/providers`, `/api/admin/media-generation`, `/api/onnx-models` |
| Storage | `userGroups` + direct `/storage-backends`, `/filesystem/*` | `/api/admin/storage-backends`, `/api/storage-backends`, `/api/filesystem/{probe,roots,dirs,mkdir,rename,ensure-bwrap}`, `/api/backend` |
| Plugins | `plugins`, `userGroups` | `/api/plugins`, `/api/user-groups` |
| AdvancedSettings | `settings`, `bridge`, `update`, `userGroups` | `/api/settings`, `/api/bridge`, `/api/update`, `/api/envs`, `/api/admin/observability` (langfuse), `/api/backup`, `/api/admin/tls`, `/api/phone-access`, `/api/setup` |
| Security | `security` | `/api/admin/security`, `/api/admin/audit-log`, `/api/admin/overview`, `/api/admin/metrics` |
| AgentConfig | direct `request("/agents/{id}")` | `/api/agents/{id}` |
| Mobile sessions/control | `connectorPairing` | `/api/connector` |
| Mobile info | `deviceLink` | `/api/device-link` |
| Setup | `auth`, `setup` (direct) | `/api/setup/{status,begin,validate-token,verify-password,presets,finish}` |
| PwaDebug / MotionPreview | — | — |

---

## (d) Classification

| Class | Pages | Rationale |
|---|---|---|
| **reuse-logic** | Chat hooks (20.8k) + Chat utils (10.4k), `pages/Agent/Config` (290), `utils/messageParser`, `parseHarnessChunk`, `parseWriteTodos`, `parseAcpPermission`, `collectTurnToolMedia`, `chatStreamError`, `formatMessageTime`, `permissions.ts`, `modelOptions`, `agentRuntimeConfig`, `docKind`, `workspaceIoPath` | Pure state machines and parsers with no DOM or antd; porting them verbatim is the cheapest way to keep SSE chunk semantics, HITL resume, and citations correct |
| **rewrite** | 20 pages: Home, Chat UI, Solo, Bao, Experts, CronJobs, Connectors, SkillPackages, KnowledgeBases, Personalization + 4 tabs, TokenUsage, ACP, Workbench + 3 sub-pages, RemoteDesktop, Models, Storage, Plugins, AdvancedSettings, Security, Setup, NotFound | Every file imports antd and/or a `.module.less`; the value is the behavior + endpoint contract, not the JSX |
| **delete** | `pages/PwaDebug` (710), `pages/MotionPreview` (796), `pages/Mobile/{MobileSessions,MobileControl,MobileInfo}` (1,143), `pages/Settings/Bridge` (16, folded into Advanced), `pages/Admin/SharedModels` (111, unreachable), `pages/Login`, `pages/Invite`, `motion/`, `page-transitions/` | Debug/preview surfaces, phone-connector UI superseded by device link, or dead redirect targets; nothing to port |
| **keep as data, not code** | `locales/en.json` + `zh.json` (950 KB) | Import the JSON; discard the antd-coupled `apiErrors` UI wiring |

Deleted-by-redirect (do not port pages): `/admin/users`, `/admin/sso`, `/admin/agents`, `/orca/*`, `/octop/*` — single-user model removed those screens.

---

## (e) Shared infrastructure to port first

| # | Item | Location | What it does | Port as |
|---|---|---|---|---|
| 1 | `api/request.ts` (833) + `api/config.ts` (68) — **already partly replaced**: `web/src/lib/api/client.ts` uses `openapi-fetch` + generated `schema.gen.ts` (38.5k lines from `openapi/octop.openapi.json`) | `api/` | `/api` prefix, bearer token + `X-Octop-Access-Token` renewal, `Accept-Language`, `X-Octop-Agent-Id`, 401/`FORBIDDEN` window events, `SetupRequiredError`, `ApiHttpError` + envelope, `requestBlob`/`requestStream`/`requestUpload`, `getWsUrl` with phone token | Keep `openapi-fetch`; **add the Bearer token, `X-Octop-Agent-Id`, `X-Octop-Access-Token` renewal, 401 event and WS `octop_token` bits it lacks** |
| 2 | Auth model | `components/AuthGuard`, `api/request.ts:53-110` | Single local owner: no login; token may be absent; `/setup` unlock | Keep: `AuthGuard` becomes a router `beforeLoad` gate |
| 3 | Contexts (7) | `context/` | `AgentContext` (active agent + refresh), `ThemeContext` (light/dark + palette), `LayoutModeContext` (classic/minimal), `ServiceRestartContext`, `BackupOperationContext`, `VoiceOutputContext`, `ScrollContext` | zustand stores: `useAgentStore`, `useThemeStore`, `useLayoutStore`, `useVoiceStore` |
| 4 | Server timezone | `hooks/useServerTimezone.ts`, `utils/formatMessageTime.ts` | `GET /api/settings/timezone` → all displayed datetimes | Port verbatim; ban bare `toLocale*` (see AGENTS.md §7) |
| 5 | i18n | `i18n.ts`, `locales/{en,zh}.json`, `utils/localePrefs.ts` | 97 namespaces; lazy bundle load; hydrates tool + skill labels from `GET /api/i18n/tools` / `/skills`; `Accept-Language` echoed to server | i18next with the same two bundles + same hydration; `apiErrors` namespaces must stay key-identical to backend `errors.*` (tests enforce) |
| 6 | Theme tokens | `styles/tokens/antd.ts`, `styles/theme-vars.css`, `motion/motion.css` | antd `ConfigProvider` theme + CSS vars `--fn-*` | Convert `--fn-*` vars to Tailwind `@theme` tokens; drop antd config |
| 7 | Permissions | `utils/permissions.ts`, `hooks/useCurrentUser`, `hooks/useUserRole` | `userCan` / `userCanAny` / `userCanKey` per route + tab | Port as-is; drives nav, tabs (`PA_MBTI_TAB_PERMISSIONS`-style maps) and Workbench tab gating |
| 8 | Layout shell | `layouts/{Sidebar 1035, Header 119, PageShell 251, MobileTabBar 98, MobileMoreSheet 393, SidebarNavCustomizer 360, sidebarNav 329, shortcutCatalog, railShortcuts}` | nav model, collapsed rail, custom nav ordering, `?` cheatsheet, ⌘K | Batch 0 territory; `sidebarNav.tsx` + `pathToKey` are the nav contract |
| 9 | PWA / SW | `pwa.ts`, `pwa-prompt.ts`, `sw-register.ts`, `components/PwaUpdatePrompt`, `components/PwaInstallPrompt` | install prompt, update prompt, notification worker; skipped when `window.octopDesktop` | Port later; `vite-plugin-pwa` equivalent, keep the desktop skip |
| 10 | Desktop chrome | `hooks/{useDesktopChrome,useNativeWindowChrome}`, `utils/{desktopChrome,desktopBridge,desktopWsUrl,nativeWindowChrome}`, `components/{DesktopWindowDragBand,WindowsAppMenu}` | macOS title band, native window buttons, relay WS URLs | Required for the desktop build; ~500 lines |
| 11 | Streaming | `utils/parseHarnessChunk`, `chatStreamError`, `pages/Chat/hooks/chatStore.ts` (4,392) | SSE `text/event-stream` parse + resume + HITL, WS chat fallback | Port parser + reducer; wrap UI in React |
| 12 | Mobile shell | `mobile/` (6,803, 33 files), `hooks/{useIsMobile,useKeyboardOffset,useMobileKeyboardOpen}`, `utils/mobileEndpoint` | separate `/m/*` app, phone-hosted base URL + credential token | Decide: one responsive tree or keep two; keeping two means re-doing `mobile/components/*` |
| 13 | Plugins runtime | `plugins/` (tool renderers, surfaces, `dshCompat`) | plugin-provided React tool UIs | Needs a stable component contract before Chat migrates |

---

## (f) Batch plan

Dependency order: shell → transport/i18n → simple read-only pages → CRUD pages → heavy engines (chat/terminal/browser/desktop). Each batch must be independently shippable behind `/web` while `dashboard/` still serves the app.

**Batch 0 — shell + design system (parent, already in progress).**
Sidebar/nav model, Header, PageShell, theme tokens, i18next bootstrap, `request.ts` port, TanStack Router tree with all 73 paths registered (redirects real, pages as placeholders), TanStack Query provider, zustand stores for agent/theme/layout.
*Accept:* `cd web && pnpm build`; every path in section (a) resolves (200 in dev server, placeholders render); `pnpm tsc --noEmit`; nav parity with `pathToKey` — 43 keys, incl. alias keys that map several paths to one nav item.

**Batch 1 — static/read-only surfaces (~9k LOC).**
Home, TokenUsage, NotFound, Setup wizard, AgentConfig, `/m/*` redirect stubs.
*Accept:* `/home` renders agent activity with live data; `GET /api/usage/summary?group_by=day` returns 200 and the chart draws; `/setup` completes first-boot flow against a fresh `OCTOP_HOME`.

**Batch 2 — content CRUD (~16k LOC).**
KnowledgeBases, SkillPackages, Connectors, Plugins (admin), Storage (admin).
*Accept:* create/list/delete one knowledge base, one skill package, one connector instance each; `GET /api/knowledge-bases`, `/api/skill-packages`, `/api/connectors` return 200; file upload preview path works.

**Batch 3 — agents, experts, tasks, personalization (~29k LOC, biggest UI batch).**
Experts (+ SubagentManager), CronJobs (`/tasks`), Personalization with 4 tabs (Skills 7.9k, Memory 15.3k, Channels 4.9k, Tools 0.8k), ACP, Bao (`/bao`).
*Accept:* agent create/start/stop round trip; cron job create + run-now returns a run; memory tab lists and edits a memory; `GET /api/mbti`, `/api/plugins` 200.

**Batch 4 — settings/admin (~18k LOC).**
Models (+ Voice/Search/MediaGeneration/Embedding panels), AdvancedSettings (+ Environments, Observability, Backup, TLS, PhoneAccess), Security, and the `/bridge` fold-in.
*Accept:* provider test connection succeeds; `POST /api/update/check` 200; theme + language switch persists and re-renders without reload.

**Batch 5 — chat (~63k LOC; the long pole — plan 2–3 sub-batches: message list → composer/tools → dock/preview).**
`pages/Chat` on ported `chatStore` + `messageParser`, markdown/katex/mermaid renderer, file preview core, attachment upload.
*Accept:* send a message and see SSE tokens stream in; reload mid-turn and history resumes; swap thread without remount; HITL approval card resolves; upload a PDF/DOCX/XLSX and preview it.

**Batch 6 — workbench + remote (~18k LOC).**
Terminal (xterm), RemoteBrowser (canvas stream), CloudHosts, RemoteDesktop, Solo (composes chat + editor + terminal).
*Accept:* open a terminal session and run `ls` (WS `/api/agents/{id}/terminal`); browser tab streams a frame; desktop tab shows a frame at ≥1 fps; Solo split panes resize.

**Batch 7 — cutover.**
Point the FastAPI static mount at `web/dist`, keep `dashboard/` importable one release, delete `dashboard/src`, `motion/`, `page-transitions/`, and the PWA debug routes.
*Accept:* `make build-frontend` produces from `web/`; `make all` green; smoke every path in section (a) on Linux + Windows CI.

Sizing guide: batches 1–4 ≈ 72k lines of source but ~80% of it is straightforward antd form/table replacement; batches 5–6 are ~81k lines with the actual technical risk.

---

## (g) Cross-cutting matrix

| Capability | Pages that need it | Old implementation | New stack |
|---|---|---|---|
| Chat streaming (SSE) | Chat, Solo, Bao, Home (activity), Experts (test chat), CronJobs (test) | `fetch` + `text/event-stream` in `chatStore.ts:3664`, `parseHarnessChunk.ts` | `@microsoft/fetch-event-source` (or raw fetch + `TextDecoder`); keep TanStack Query out of the stream, own it in a zustand store |
| Chat streaming (WS) | Chat fallback, notifications | `api/modules/wsChat.ts` → `/agents/{id}/chat/ws`, `/notifications`; `desktopWsUrl.ts` relay | native `WebSocket` + reconnect/backoff util; same URL builder incl. `octop_token` |
| Markdown + math + mermaid | Chat, Bao, Solo, Memory, Experts | react-markdown 10, remark-gfm, remark-math, rehype-katex, mermaid 11 (lazy loader) | identical packages are fine on the new stack; keep the lazy mermaid loader pattern |
| File preview pdf | Chat dock, KnowledgeBases | `PdfDocumentPreview.tsx` (react-pdf 10, windowed) | `react-pdf` + `pdfjs-dist` worker; or `@react-pdf-viewer/core` |
| File preview docx / pptx / xlsx | Chat dock, KnowledgeBases | `docx-preview`, `@aiden0z/pptx-renderer`, `xlsx` | same packages; `xlsx` → `@e965/xlsx` if the npm tarball is a blocker |
| Code/monaco | Solo, Agent/Workspace, Memory (overview) | `@monaco-editor/react` 4.7 | same, lazy-loaded; only 12 lines of loader config to port |
| Terminal | Terminal, Solo | `@xterm/xterm` 5.5 + fit + web-links | same packages (`@xterm/*`), keep `useTerminal.ts` logic |
| Browser view | RemoteBrowser, Chat (browser panel) | `useBrowserStream`/canvas + `/browser-stream/ws` | canvas 2D + WS, no library; `useBrowserCanvasInteraction` logic is reusable |
| Remote desktop | RemoteDesktop | `/desktop-stream` WS → canvas, `desktopShortcuts` | same; needs pointer/keyboard capture utils |
| Voice in / out | Chat composer, Voice settings, VoiceOutputContext | `useVoiceInput`, `realtimeStt`, `pcmCapture`, `wavStreamPlayer`, `browserSpeech` | WebAudio + `/api/voice/stt-stream`; keep `pcmCapture.ts` verbatim |
| Charts | TokenUsage, Memory, CloudHosts | recharts 3 | recharts 3 or `@nivo`; 4 files total, low risk |
| Virtualized lists | Chat messages, session list | react-virtuoso 4 | `@tanstack/react-virtual` |
| QR / pair | RemoteDesktop, Bao | `qrcode.react` | `qrcode.react` unchanged |
| PWA | shell | `vite-plugin-pwa` 0.21 + custom `pwa-prompt` | `vite-plugin-pwa` (same), drop antd-flavored prompts |

---

## (h) Risks & unknowns

1. **Chat is 24% of the frontend** (62.7k lines, `chatStore.ts` alone 4,392). Any plan that lists "chat" as one batch under-estimates by ~3×. Split it by surface: message list → composer/tool dock → preview/attachments.
2. **`useWrapper` / keep-alive semantics must be reproduced deliberately.** Chat must not remount on `:threadId` change, and Workbench keeps all three panels mounted with `display:none`. TanStack Router preserves routes differently — these need explicit `shouldReload`/`keepAlive` handling or users lose composer state and terminal sessions.
3. **`redirectPreserveSearch` on 15 routes.** Bookmarks in the wild carry `?search`/`#hash`; a naive `<Navigate>` drops them.
4. **Two page trees.** `mobile/` (6,803 lines) is a separate app with its own components and `/m/*` URLs, chosen at runtime by `useIsMobile()`. Unverified whether product wants to keep a distinct phone design; if not, this is 6.8k lines of "delete" and the new shell must be responsive instead.
5. **Desktop chrome coupling.** `utils/desktopBridge`, `desktopWsUrl`, `nativeWindowChrome`, and `window.octopDesktop` gates (SW registration, window drag) are used by the Electron/desktop shell. Unknown: whether `web/` is also shipped inside the desktop shell, which decides what batch 0 must include.
6. **antd-specific UX with no Tailwind equivalent**: `Segmented`, `Table` sorting/pagination, `DatePicker` with dayjs locale, `ConfigProvider.getPopupContainer` (`popupLayer`), `Spin` indicator, drawer/modal stacking that mobile Escape handling depends on (`MainLayout:238`). Budget for a real component library layer, not just Tailwind primitives.
7. **i18n key parity is test-enforced** (`tests/unit/i18n/`): backend `errors.*` and dashboard `apiErrors.*` must match. Copying `zh.json`/`en.json` unchanged is the safe move; renaming namespaces breaks the Python tests.
8. **`/api/admin/usage/summary` is documented as `/api/usage/summary`** in `TokenUsage`'s header comment (`index.tsx:6`) but called as `/admin/usage/summary` (line 437). Trust the code; the comment is stale.
9. **Unmeasured**: LOC of the embedded settings panels (`Settings/{Voice,SearchConfig,MediaGeneration,Embedding,Environments,Observability,BackupRestore,HttpsSettings,PhoneAccess,Language,octop}`) — they are composed inside Models/AdvancedSettings and were not sized individually. Treat batch 4 as ±20%.
10. **`pages/Admin/SharedModels` (111) is unreachable** — `/admin/shared-models` redirects to `/admin/models`. Do not port; confirm with the backend that `/admin/providers` has no shared-model mode left.
11. **Dead client module**: `api/modules/embedding.ts` calls `/api/embedding/{config,models,apply,download-local,download-status}`, but no such router is mounted — `grep -rn "embedding/config" src/` (Python) returns nothing, and nothing imports the module. The live embedding UI is `Models/components/EmbeddingSettingsPanel` → `/api/onnx-models`. Don't port it.
12. **Vite `BASE_URL` + `routerBasename()`** support mounting under a subpath, and the phone client rebases the API origin to a user-entered host (`mobileApiBase`). A rewrite that hard-codes same-origin `/api` breaks the phone-hosted deployment.

---

## (i) Current `web/` scaffold vs this inventory

Measured in the same worktree (`web/src`, untracked, 42,240 lines incl. the 38.5k generated schema):

| Layer | Present | Gap against this inventory |
|---|---|---|
| Routes | 5 files: `_app.index`, `_app.chat`, `_app.settings`, `_app.design`, `__root` | **68 of 73 paths still unregistered**; no redirect table, no `/m/*` decision |
| Transport | `lib/api/client.ts` (`openapi-fetch`, typed from `openapi/octop.openapi.json`), `errors.ts` | Bearer auth, `X-Octop-Agent-Id`, token renewal header, 401 → event, WS `octop_token` |
| Chat | `features/chat` (ChatPage, Composer, MessageList, ThreadRail, `api.ts`, `queries.ts`, `useChatSocket.ts`, `mock.ts`) — 954 lines | `chatStore` semantics (4,392) not ported: resume, HITL, tool blocks, dock/preview, citations |
| Settings | `features/settings/SettingsPage.tsx` | 12 settings/admin pages |
| State | `stores/ui.ts` (64) | agent, theme, layout, voice stores |
| i18n | `lib/i18n` | bundle copy (950 KB, 97 namespaces) + tool/skill label hydration |
| Design | `features/design` (token/component showcase) | replaces `pages/MotionPreview` as the design QA surface — good |

The typed client from the backend OpenAPI document is the right call and makes section (c) cheaper: each page's HTTP surface is already described, so those rows are the checklist for which typed calls to add, not new hand-written modules.
