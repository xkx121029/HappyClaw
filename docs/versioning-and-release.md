# 版本管理与发版

本文定义 HappyClaw 的版本号规则、CHANGELOG 写法、发布清单（release manifest）格式，以及打标签与发版步骤。

相关文件：

- `pyproject.toml`：包版本号的唯一来源（`version = "..."`，不使用动态版本）
- `CHANGELOG.md`：面向用户的版本记录
- `docs/release-manifest.schema.json`：发布清单 JSON Schema
- `scripts/release_manifest.py`：从构建产物生成并校验发布清单
- `src/octop/infra/setup/release_manifest.py` / `GET /api/update/check`：读取清单的只读更新检查
- `site/site.config.js`：官网下载区展示的产物列表（可选，与清单保持一致）

## 1. 版本号规则

版本号遵循 **PEP 440**（同时兼容 SemVer 2.0 的 `MAJOR.MINOR.PATCH` 读法），发布到 PyPI、wheel、安装脚本和 release manifest 的都是同一个字符串。

```
MAJOR.MINOR.PATCH[(a|b|rc)N][.postN][.devN][+local]
```

- `MAJOR`：不兼容的接口或数据格式变更
- `MINOR`：向后兼容的功能新增
- `PATCH`：向后兼容的修复
- 预发布标识：`a`（alpha）、`b`（beta）、`rc`（release candidate），可带序号，如 `1.0.4b1`
- 开发版本：`.devN`，只用于本地或 CI，不发布到 stable 渠道
- 已有的 `1.0.3b5` 表示 `1.0.3` 的 beta 5，不是 `1.0.35`

渠道与版本的关系：

| 渠道 | 接受的版本 | 说明 |
| --- | --- | --- |
| `stable` | 无预发布标识 | 正式发布；manifest 的 `channel` 必须是 `stable` |
| `beta` | 稳定版或预发布版 | 预发布清单的 `channel` 为 `beta`；`stable` 请求不会拿到 beta 清单 |

版本号一旦发布就不修改、不复用。需要修复时发布新的 `PATCH`。

`v` 前缀只用于 git 标签；`pyproject.toml` 和发布清单里的 `version` 不带 `v`。

## 2. CHANGELOG 写法

`CHANGELOG.md` 遵循 [Keep a Changelog](https://keepachangelog.com/) 的结构：

- 顶部保留 `## [Unreleased]`，发版时把条目移到新的版本标题下
- 版本标题格式固定为 `## [1.0.4] - 2026-11-14`（版本号 + ISO 日期）
- 分类按需使用：`Added`、`Changed`、`Deprecated`、`Removed`、`Fixed`、`Security`
- 每条写“用户能感知的变化”，不写提交流水账；破坏性变更必须在 `Changed` 或 `Removed` 中明确标注
- 预发布也单独记录，例如 `## [1.0.4b1] - 2026-11-10`
- 详细的长篇说明可以放在 `docs/release-notes-<version>.md`，CHANGELOG 中给出摘要

发版时 manifest 的 `notes` 字段可以直接取 `docs/release-notes-<version>.md` 的内容（脚本的 `--notes-file`）。

## 3. 发布清单格式

完整字段与约束见 [`docs/release-manifest.schema.json`](./release-manifest.schema.json)。一份最小示例（地址为**占位符**，真实发布时必须替换为你自己的下载地址）：

```json
{
  "schema_version": 1,
  "product": "HappyClaw",
  "version": "1.0.4",
  "channel": "stable",
  "published_at": "2026-11-14T08:00:00+00:00",
  "notes": "- 修复发布清单缓存\n- 新增发版校验脚本",
  "minimum_supported_version": "1.0.0",
  "artifacts": [
    {
      "platform": "windows",
      "arch": "x64",
      "kind": "portable",
      "filename": "HappyClaw-portable-windows-x64-1.0.4.zip",
      "url": "https://downloads.example.invalid/happyclaw/1.0.4/HappyClaw-portable-windows-x64-1.0.4.zip",
      "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
      "size_bytes": 104857600
    }
  ]
}
```

字段说明：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `schema_version` | 是 | 当前固定为 `1`；破坏性变更时才递增 |
| `product` | 否 | 展示名称，默认 `HappyClaw` |
| `version` | 是 | 本清单对应的版本，必须与 `pyproject.toml`、git 标签一致 |
| `channel` | 是 | `stable` 或 `beta` |
| `published_at` | 否 | ISO-8601 时间 |
| `notes` | 否 | Markdown 发布说明 |
| `minimum_supported_version` | 否 | 低于该版本时接口返回 `supported=false`，提示用户先升级 |
| `artifacts` | 是 | 至少一项；`filename` 与 `url` 全局唯一 |
| `artifacts[].platform` | 是 | `windows` / `macos` / `linux` / `fnos` / `android` / `ios` / `any` |
| `artifacts[].arch` | 是 | `x64` / `arm64` / `x86` / `arm` / `universal` / `any` |
| `artifacts[].kind` | 否 | `desktop` / `portable` / `installer` / `native` / `docker` / `cli` / `python` / `apk` / `source` / `artifact` |
| `artifacts[].filename` | 是 | 上传后的文件名 |
| `artifacts[].url` | 是 | 绝对 HTTP(S) 地址 |
| `artifacts[].sha256` | 是 | 64 位小写十六进制，按实际上传文件计算 |
| `artifacts[].size_bytes` | 是 | 文件字节数，必须与磁盘一致 |

约束：

- 不允许编造 URL。`--base-url` 是必填项，脚本不会用占位域名兜底。
- `sha256` 与 `size_bytes` 必须对应最终上传的那份文件；重新打包后必须重新生成清单。
- 旧版本的产物和清单不删除，保留回滚能力。

## 4. 生成与校验

构建产物命名必须带平台与架构标记，脚本据此推断元数据：

```
HappyClaw-portable-windows-x64-1.0.4.zip
HappyClaw-desktop-macos-arm64-1.0.4.dmg
HappyClaw-fnos-native-amd64-1.0.4.fpk
```

平台标记：`windows` / `win` / `macos` / `mac` / `darwin` / `linux` / `fnos` / `android`；架构标记：`amd64` / `x86_64` / `x64` / `arm64` / `aarch64`。`*.whl` 自动记为 `platform=any, arch=any, kind=python`。无法推断的文件会直接报错，不会被静默跳过。

生成清单：

```bash
python scripts/release_manifest.py build \
  --version 1.0.4 \
  --channel stable \
  --artifacts-dir dist/release \
  --base-url https://<你的下载根>/happyclaw/1.0.4 \
  --notes-file docs/release-notes-1.0.4.md \
  --minimum-supported-version 1.0.0 \
  --output dist/release-manifest.json
```

校验清单（重新计算每个文件的 SHA256 与体积）：

```bash
python scripts/release_manifest.py validate dist/release-manifest.json \
  --artifacts-dir dist/release
```

- 缺字段、`sha256` 格式错误、`size_bytes` 非正数、URL 非 HTTP(S)、文件名/URL 重复、文件缺失、哈希或体积不符，都会以非零退出码失败，并逐条打印原因。
- 只做结构校验时可以省略 `--artifacts-dir`，但发版前必须带目录做一次完整校验。
- `build` 内部也会先校验生成的清单，再写文件。

## 5. 更新检查接口

后端只读取清单并返回信息，不下载、不安装：

```
GET /api/update/check?current_version=1.0.3b5&channel=stable
```

- `current_version` 省略时使用当前运行版本
- `channel` 取 `stable` / `beta`；非法值返回 `400`
- 返回最新版本、`has_update`、`supported`、`minimum_supported_version`、发布说明、发布时间、各平台产物（URL/SHA256/体积/文件名）、`source` / `cached` / `stale`
- 清单未配置、不可达、格式错误时仍返回 HTTP 200，并带 `error_code`（`manifest_not_configured` / `manifest_unreachable` / `manifest_invalid` / `no_release_for_channel`），前端据此展示原因
- 远端不可达但内存里有旧结果时，返回旧结果并标记 `stale=true`，同时附上失败原因

部署侧配置：

| 环境变量 | 说明 |
| --- | --- |
| `OCTOP_RELEASE_MANIFEST_FILE` | 本地清单路径，优先级最高；适合内网/离线部署 |
| `OCTOP_RELEASE_MANIFEST_URL` | 清单的 HTTP(S) 地址；回环地址会绕过系统代理 |
| `OCTOP_RELEASE_MANIFEST_TTL_S` | 进程内缓存秒数，默认 600，范围 0–86400 |
| `OCTOP_RELEASE_MANIFEST_TIMEOUT_S` | 拉取超时秒数，默认 6，范围 1–30 |

清单应作为静态 JSON 托管在稳定地址；发布新版本时整体替换该文件（或把环境变量指向新路径）。

## 6. Git 标签约定

- 使用附注标签，格式 `v<version>`，与 manifest / `pyproject.toml` 的版本完全一致
- 正式版：`v1.0.4`；预发布：`v1.0.4b1`
- 标签必须打在实际构建出该批产物的提交上
- 已推送的标签不移动、不删除、不复用；需要修正时发新版本

```bash
git tag -a v1.0.4 -m "HappyClaw 1.0.4"
git push origin v1.0.4
```

## 7. 发版步骤

1. 确认 `CHANGELOG.md` 的 `[Unreleased]` 已整理，并新增 `## [1.0.4] - YYYY-MM-DD`
2. 修改 `pyproject.toml` 的 `version`，确保与计划标签一致
3. 构建各平台产物（桌面端、portable、fnOS 等），产物名包含平台/架构/版本
4. 运行 `release_manifest.py build` 生成 `release-manifest.json`
5. 运行 `release_manifest.py validate --artifacts-dir ...`，必须退出码 `0`
6. 上传产物与 manifest 到下载根，确认地址可访问、文件未被二次压缩
7. 配置服务端 `OCTOP_RELEASE_MANIFEST_URL`（或 `_FILE`）指向新清单
8. 打标签并推送：`git tag -a v1.0.4 -m "HappyClaw 1.0.4"`、`git push origin v1.0.4`
9. 验证：调用 `GET /api/update/check`，并在设置 → 高级设置 → 应用更新中点击「检查发布清单」
10. 如需官网展示下载项，同步更新 `site/site.config.js` 的 `downloads`（留空则显示「待配置」）

## 8. 回滚

- 保留上一个可用 manifest 的副本（例如 `release-manifest.previous.json`）
- 回滚时把 `OCTOP_RELEASE_MANIFEST_URL` 指回旧清单，或恢复旧文件；不要删除已发布的产物
- 已经安装新版本的用户仍可继续使用；若需要强制迁移，提升 `minimum_supported_version` 并不能降级客户端，只会在检查时提示
- 标签不移动；回滚通过“发布一个更高的修复版本”完成，而不是重写历史
