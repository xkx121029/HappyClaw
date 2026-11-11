# 多用户文案审计（2026-11-12）

范围：`docs/`、`README.md`、`README_CN.md`、`dashboard/src`（含 `locales/zh.json`）。
关键词：团队、邀请、成员、角色、管理员。
方法：文本检索 + 路由核对 + i18n key 使用点定位。**本轮只读，未修改任何 dashboard 文案。**

## 结论摘要

| 位置 | 命中 | 其中建议改 | 说明 |
|------|------|-----------|------|
| `dashboard/src/locales/zh.json` | 200 | 约 40 个 key | 大部分是「专家团队」产品词；多用户残留集中在分享面板、插件/知识库错误提示、已下线页面 |
| `docs/` | 130（12 个文件） | 2 个文件需处理 | `ldap.md`、`user-guide.html` 已标注历史；`projects.md` 部分段落仍按多用户写 |
| `README.md` / `README_CN.md` | 7 | 2 行 | 第 31 行「没有团队」与「专家团队」功能冲突 |

最重要的判断：**「团队」「成员」「角色」有三种含义，不能一律删**——

1. 多用户语义（成员账号、邀请、权限、管理员）：该改；
2. 专家团队语义（多个 AI 专家协作）：保留；
3. 历史兼容（旧页面、旧接口、旧文档）：保留但标注。

## 一、建议改（界面可达，会真的被用户看到）

| 位置 | 现文案 | 问题 | 建议 |
|------|--------|------|------|
| `components/ResourceVisibilityFields/index.tsx`（技能包 / 知识库 / 模型 / 连接器 / 专家分享共用） | `resourceVisibility.*` 共 10 条：`label=谁可以使用`、`groups=指定用户分组`、`groupPlaceholder=至少选择一个用户分组`、`groupAccessHint=默认所有人可用。需要限制时，指定用户分组；管理员不受限制。` | 单人模式没有“其他用户/分组/管理员”，分组选项无法管理（`/admin/users` 已重定向） | 只保留「仅自己 / 所有人」；删掉 groups 选项与分组提示，hint 改为「本机只有你一个使用者」 |
| `CreateFromExpertDrawer.tsx:828` | `experts.visibilityHint=仅自己：只有你和管理员能用。所有人：其他登录用户可以对话……` | 同上 | 改为单人表述，去掉管理员/其他登录用户/分组 |
| `Connectors/index.tsx:2278` | `connectors.visibilityHint` 同上 | 同上 | 同上 |
| `SkillPackages/index.tsx:1298` | `skillPackages.visibilityHint=只有创建者和管理员能用……登录用户可查看……` | 同上 | 同上 |
| `CreateFromExpertDrawer.tsx:696` | `experts.noModelsWarning=当前未配置任何模型，请前往管理员页面配置供应商。` | 没有“管理员页面” | 改为「请前往设置 → 模型配置供应商」 |
| `ModelConfigEmpty.tsx:31` | `modelConfig.promptMessageNoPermission=当前没有可用模型，请联系管理员配置后再开始对话。` | 单人没有可联系的管理员 | 改为「请先在设置 → 模型中配置供应商」 |
| `Connectors/index.tsx:1454` | `connectors.cliInstallAdminOnly=主机 CLI 需管理员安装；可复制命令交给管理员执行` | 用户就是本机维护者 | 改为「需在本机终端安装，可复制命令执行」 |
| 连接器 OAuth 提示 | `connectors.oauthNeedAdmin=此连接器需管理员配置 OAuth 应用后方可一键授权`、`oauthNeedAdminHint=请联系管理员配置环境变量……` | 同上；且动态拼接 key，静态检索未命中调用点 | 改为「需先在本机配置 OAuth 应用」 |
| `KnowledgeBases/index.tsx:2191` | `knowledgeBases.unavailableDescriptionNonAdmin=知识库尚未启用或未配置向量模型，请联系管理员。` | 同上 | 改为「请先在设置中启用知识库并配置向量模型」 |
| `AgentPluginsPanel.tsx:339` 等 | `plugins.globalDisabledHint=管理员已全局关闭此插件`、`plugins.noPlugins=请联系管理员先安装插件` | 同上 | 改为「已在全局设置中关闭」「可在设置 → 插件中安装」 |
| 聊天错误提示 | `stream_errors.stream_stall=……请联系管理员排查流式超时设置。` | 同上 | 改为「请检查供应商状态或流式超时设置」 |
| `apiErrors.*` | `KNOWLEDGE_FEATURE_DISABLED=管理员尚未启用知识库功能`、`WEBAUTHN_CONFIG_INVALID`、`WEBAUTHN_LOGIN_DISABLED`、`AGENT_QUOTA_EXCEEDED`、`TOKEN_QUOTA_EXCEEDED`（均含“管理员”） | 这些错误仍可能从后端返回 | 改为自助表述（去「管理员」，指向设置页） |
| 通行密钥设置 | `account.securityPasskeyUnconfigured=请让管理员打开「应用设置 → 通行密钥」……` | 同上 | 改为「请在本机设置 → 通行密钥中填写」 |
| `common.noPermissionHint` | `你没有访问此页面的权限，请联系管理员开通。` | 单人不应出现权限页 | 若保留，改为「当前操作不可用」 |
| `/admin/audit` 审计页 | `adminAudit.actorAdmin=管理员`、`actions.user.set_role=设置角色` | 路由仍可达（不在侧栏）；单人下“管理员”标签会误导 | 标签改为「本机使用者」「修改角色（历史）」或直接隐藏该页 |
| `README.md:31` / `README_CN.md:31` | 「没有账号体系……也没有团队与权限配置」 | 与 `README.md:61` 的「AgentTeams / 专家团队」直接冲突 | 改为「没有成员账号与权限配置」，保留专家团队 |
| `docs/projects.md:26,82,96,101` | 「准入不是点名用户」「用户分组」「不点名用户，不用第二张成员表」 | 团队本身是 AI 专家团队（保留），但这几句是旧多用户准入语义 | 标注“历史设计”，或改成单人下的可见性说明 |

## 二、不可达页面 / 死代码（历史兼容，可保留，下版建议删）

| 位置 | 数量 | 依据 |
|------|------|------|
| `adminUsers.*` | 64 | `/admin/users` 已 `<Navigate to="/chat">`；`AvatarPicker` 的 user/role 预设只有导出、无消费方 |
| `invite.*` | 7 | `/invite` 已重定向；邀请创建接口返回 400 |
| `wizard.*` | 8 | setup 固定为不需要初始化；`/setup/begin`、`/setup/finish` 返回 400 |
| `adminSso.*` | 11 | `/admin/sso` 已重定向；LDAP 停用 |
| `login.forgotPasswordHelp` | 1 | 登录页已重定向 |
| `apiErrors.INVITE_*` | 6 | 邀请流程不可达 |
| `apiErrors.USER_ROLE_*` | 3 | 角色管理不可达 |
| `apiErrors.LDAP_*` | 2 | LDAP 停用 |
| `account.role` / `account.roleAdmin` | 2 | 仅测试引用；账号抽屉不展示角色 |
| `models.cannotDeleteSharedDesc` / `models.sharedProviders` / `models.groupAccessHint` | 3 | 仅语言包，无界面引用 |
| `storage.featureAccessHint`、`remoteDesktop.adminOnlyTitle/Desc`、`toolFeedback.actions.contact_administrator`、`memory.storage.blocked_postgres` | 5 | 检索不到直接引用；若后续恢复功能，先改文案再上线 |
| `adminProviders.pageDescription` | 1 | `Settings/octop/Providers.tsx` 组件未被任何路由引用 |

## 三、保留（产品功能语义，不是多用户残留）

- `experts.teams.*`、`experts.myTeams`、`teamId`、`copyTeamId`：专家团队。
- `chat.*` 的 `teamBadge`、`membersResponding`、`teamProfile.members`、`decisionMember`：团队房间与派工。
- `agentSelector.teamsGroup`、`chatWelcome.*Team`。
- `advancedSettings.bridge.*`：对端实例的专家/团队。
- `models.decision*`：按轮次筛选技能、工具、团队成员。
- `tokenUsage.callRole`（模型调用角色）、`subagents.newBodyTemplate`（子智能体角色设定）。
- `apiErrors.TEAM_*`（5 条）：专家团队的错误。
- 文档：`expert-teams.md`（52）、`plugin-package.md`（4，成员=包内条目）、`expert-package.md`（3，同上）、`discord-channel.md`（2，邀请机器人/角色提及）、`bridge.md`（1，Bridge 角色）。

## 四、文档逐条

| 文件 | 命中 | 结论 |
|------|------|------|
| `docs/expert-teams.md` | 52 | 全部为 AI 专家团队语义，保留 |
| `docs/ldap.md` | 25 | 顶部已标注「单人模式下已停用」，历史兼容，保留 |
| `docs/user-guide.html` | 17 | 第 134 行已有「旧版多用户文档的 HTML 快照」横幅；但正文第 397 行仍写默认管理员密码 `octop`。已标注失效，建议不再对外发布或直接删除 |
| `docs/projects.md` | 13 | 团队=AI 专家团队，主体保留；第 26/82/96/101 行的准入与分组表述需改写（见上表） |
| `docs/octop-introduction.html` | 5 | **没有快照横幅**；第 526 行「团队披露」、第 742 行「团队治理」容易被读成多用户能力。建议加历史横幅或改写 |
| `docs/RELEASE-CHECKLIST.md` | 5 | 检查项中的「管理员密码 / 账号」，属于历史检查项，保留 |
| `docs/plugin-package.md` / `expert-package.md` | 4 / 3 | 「成员」指包内条目，保留 |
| `docs/discord-channel.md` | 2 | Discord 的邀请与角色，保留 |
| `docs/user-guide.md` / `docs/quickstart.md` | 2 / 1 | 「无需预置管理员密码」是兼容说明，可保留；建议顺手改为「无需账号」 |
| `docs/bridge.md` | 1 | Bridge 角色，保留 |

## 五、范围外但发现（desktop，本轮未改）

`desktop/src/renderer/src/onboarding.tsx:66` 首次引导写着「HappyClaw 没有账号、邀请和团队」，与「专家团队」功能冲突。建议把「团队」改为「成员账号与权限配置」。desktop 归桌面壳线，交回对应负责人。

## 六、给前端线的处理顺序

1. 先改分享面板（`ResourceVisibilityFields` + 三个 `visibilityHint`）：这是用户最常看到、也最容易困惑的一处。
2. 再改「去管理员化」的报错与空状态（模型、连接器、知识库、插件、通行密钥、流式超时）。
3. 删除已重定向页面的语言包（`adminUsers`、`invite`、`wizard`、`adminSso`、`login`），顺带移除 `AvatarPicker` 未使用的 user/role 预设。
4. 最后处理 `/admin/audit` 的标签；若确定不开放，直接隐藏入口。
5. 英文 `en.json` 同步改，避免中英不一致。
