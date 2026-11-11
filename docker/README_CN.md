# HappyClaw Docker 部署（本机单人版）

---

本目录包含 HappyClaw 的 Docker 构建与部署相关文件。默认按**单机、单人、单实例**运行：一个容器、一个数据卷、一个本机使用者。

### 文件说明

| 文件 | 说明 |
|------|------|
| `Dockerfile` | 多阶段镜像定义（构建上下文为仓库根目录） |
| `../.dockerignore` | 构建上下文忽略规则（Podman 与 BuildKit 均适用） |
| `docker_build.sh` | 从源码构建镜像（默认开启 BuildKit 缓存） |
| `docker-compose.yml` | 本地开发 / 自托管一键启动 |
| `docker-compose.cn.yml` | 同一套服务，拉取 `ghcr.nju.edu.cn/tencentcloud/octop:latest`（不本地构建） |
| `docker-compose.postgres.yml` | 仅 PostgreSQL（+ pgvector）开发/测试库；扩展在 `postgres/init-vector.sql` |
| `postgres/init-vector.sql` | 实例级 `CREATE EXTENSION vector`（initdb.d；**不**进 HappyClaw 迁移） |
| `docker-entrypoint.sh` | 容器入口：首次初始化数据库并启动服务 |

### 快速开始

**方式一：Compose（推荐）**

在仓库根目录执行：

```bash
docker compose -f docker/docker-compose.yml up -d --build
```

访问 `http://localhost:8088`。单人模式不需要预置管理员密码，也不需要走设置向导：首次启动会初始化数据库并自动绑定本机使用者，打开页面直接进入工作台。

> **兼容说明**：`OCTOP_DEFAULT_PASSWORD`、`OCTOP_ADMIN_USERNAME`、`OCTOP_ADMIN_DISPLAY_NAME` 仍被入口脚本读取，仅用于兼容旧部署。单人版启动后这些账号不会被使用；如需复用旧数据卷，保留原值即可。入口脚本的清理将在后端单人化接线完成后单独提交，避免与当前镜像启动流程冲突。

Compose 将多 agent 服务的文件描述符限制设为 65535。服务启动时也会在继承的 hard limit 内将 soft limit 提升至最多 65535，并记录实际限额。已有容器需重新创建才能应用 Compose 限额变化；仅重启不会改变容器的 hard limit。

**方式二：构建脚本**

```bash
bash docker/docker_build.sh
docker run -d \
  --name octop \
  --ulimit nofile=65535:65535 \
  -p 8088:8088 \
  -v octop-data:/data/.octop \
  -e HOME=/data \
  octop:latest
```

已发布标签：`ghcr.io/tencentcloud/octop:<version>` 和 `:latest` 是精简版。`:<version>-full` 和 `:full` 才带桌面、OCR 和本地向量。本地构建默认是完整版，精简版要加 `--build-arg OCTOP_IMAGE_VARIANT=lite`。

### 国内镜像加速

构建时可通过环境变量加速依赖下载：

```bash
PIP_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple \
PIP_TRUSTED_HOST=mirrors.cloud.tencent.com \
NPM_REGISTRY=https://mirrors.cloud.tencent.com/npm/ \
APT_MIRROR=mirrors.cloud.tencent.com \
bash docker/docker_build.sh
```

### 常用环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `HOME` | `/data` | 必须为 `/data`，数据目录映射到 `~/.octop` |
| `OCTOP_PORT` | `8088` | HTTP 服务端口 |
| `OCTOP_DATA` | `~/.octop` | 宿主机数据目录（Compose 挂载到 `/data/.octop`） |
| `OCTOP_DEFAULT_PASSWORD` | _(未设置)_ | **Legacy**：旧版首次管理员密码，单人版不读取账号逻辑，保留仅为兼容 |
| `OCTOP_ADMIN_USERNAME` | `admin` | **Legacy**：旧版管理员用户名，单人版忽略 |
| `OCTOP_DATABASE_URL` | — | PostgreSQL DSN（或其他 `OCTOP_DATABASE_*`，见 [configuration.md](../docs/configuration.md)） |
| `OCTOP_DATABASE_DRIVER` | — | 通过环境变量覆盖时：`sqlite` \| `postgresql` |
| `OPENAI_API_KEY` | — | OpenAI 兼容 API Key |
| `DASHSCOPE_API_KEY` | — | 阿里云通义千问 API Key |

Compose 可在 `docker/.env` 中配置上述变量。注意：`.env` 只参与 Compose 插值，变量必须出现在 `docker-compose.yml` 的 `environment:` 中才会进入容器。也可把相同键写入挂载数据目录下的 `~/.octop/env`。

### Node.js

运行镜像带 Node.js 20（`node` / `npm` / `npx`），与构建前端时使用的版本相同，供依赖 Node 的技能和专家 shell 使用。工具链从构建阶段的 `node:20-slim` 复用。已有部署需要重新构建或升级镜像后才会带上 Node.js；仅重启旧镜像无效。`npm install -g` 装进容器可写层，重建容器后需要重装。

### 知识库依赖

镜像除 `browser` 外，还包含 `local-embedding` 和 `knowledge-ocr` 可选依赖。
两次依赖安装均指定这些 extras，避免最后一次 `uv sync` 将其移除。构建时会检查
嵌入与 OCR 模块能否导入；不会下载模型权重，也不会自动开启知识库或 OCR。

通过控制台安装到运行中容器的依赖位于容器可写层，重建容器后会丢失。应重新构建或
拉取已包含这些 extras 的镜像，而不是依赖运行时安装。保留 `/data/.octop` 数据卷，
即可保留配置、知识库索引与本地嵌入模型缓存。已有部署需要重新构建或升级镜像才能
获得这些依赖，仅重启旧镜像无效。

### 数据持久化

- Compose 默认将宿主机 `~/.octop` 挂载到容器 `/data/.octop`
- `docker run` 示例使用命名卷 `octop-data`
- 首次启动：初始化运行目录与数据库，自动创建本机使用者；不需要密码、向导或 `credential.txt`
- 升级：保留数据卷、重新构建镜像即可，数据库结构在启动时迁移
- 备份：`docker exec -it octop octop backup create --include-chats`，归档保存在容器内，需 `docker cp` 取出

### 健康检查

镜像内置 `HEALTHCHECK`，探测 `GET /api/health`：

```bash
curl http://localhost:8088/api/health
```

### 常用运维命令

```bash
docker logs -f octop
docker exec -it octop octop --version
docker compose -f docker/docker-compose.yml down
docker compose -f docker/docker-compose.yml up -d --build
```
