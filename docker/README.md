# HappyClaw Docker Deployment

---

This directory contains the Docker build and deployment assets for HappyClaw.

### Files

| File | Description |
|------|-------------|
| `Dockerfile` | Multi-stage image definition (build context is the repo root) |
| `../.dockerignore` | Build context ignore rules (applies to both Podman and BuildKit) |
| `docker_build.sh` | Build image from source (BuildKit cache enabled by default) |
| `docker-compose.yml` | One-command local / self-hosted deployment |
| `docker-compose.cn.yml` | Same stack, pulls `ghcr.nju.edu.cn/xkx121029/happyclaw:latest` (no local build) |
| `docker-compose.postgres.yml` | PostgreSQL (+ pgvector) for dual-backend dev/tests |
| `postgres/init-vector.sql` | Instance-level `CREATE EXTENSION vector` (initdb.d; **not** HappyClaw migrations) |
| `docker-entrypoint.sh` | Container entrypoint: first-run bootstrap (dirs + DB, no account) + start server |

### Quick start

**Option 1: Compose (recommended)**

From the repository root:

```bash
docker compose -f docker/docker-compose.yml up -d --build
```

Open `http://localhost:8088`. Single-user mode needs no administrator password and no setup wizard: the first boot initializes the database and binds the local owner automatically, and the dashboard opens straight into the workspace.

> **Upgrading from an older image:** the container no longer reads `HAPPYCLAW_DEFAULT_PASSWORD`, `HAPPYCLAW_ADMIN_USERNAME`, or `HAPPYCLAW_ADMIN_DISPLAY_NAME`, and creates no account. First boot runs `octop init --yes` (runtime directory + migrations only) and the server binds the local owner on start, so an existing data volume keeps every user row and you open the dashboard as that owner. `credential.txt` and `octop-login.txt` are no longer written; leftovers from an older image are harmless.

Compose sets the open-file limit to 65535 for multi-agent workloads. Server startup also raises the soft limit up to 65535 within the inherited hard limit and logs the effective limits. Recreate existing containers to apply changed Compose limits; a restart alone does not change their hard limit.

**Option 2: Build script**

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

Published tags: `ghcr.io/xkx121029/happyclaw:<version>` and `:latest` are the lite image. `:<version>-full` and `:full` add desktop, OCR, and local embedding. A local build is full unless you pass `--build-arg HAPPYCLAW_IMAGE_VARIANT=lite`. The image name comes from the repository that runs `docker-publish`, so a tag is pullable only after that workflow has completed once for it; until then build locally.

### Faster downloads (China mirrors)

Pass mirror env vars when building:

```bash
PIP_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple \
PIP_TRUSTED_HOST=mirrors.cloud.tencent.com \
NPM_REGISTRY=https://mirrors.cloud.tencent.com/npm/ \
APT_MIRROR=mirrors.cloud.tencent.com \
bash docker/docker_build.sh
```

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HOME` | `/data` | Must be `/data` so `~/.happyclaw` maps to the data volume |
| `HAPPYCLAW_PORT` | `8088` | HTTP listen port |
| `HAPPYCLAW_DATA` | `~/.happyclaw` | Host data directory (mounted at `/data/.octop`) |
| `HAPPYCLAW_DATABASE_URL` | — | PostgreSQL DSN (or other `HAPPYCLAW_DATABASE_*`; see [configuration.md](../docs/configuration.md)) |
| `HAPPYCLAW_DATABASE_DRIVER` | — | `sqlite` \| `postgresql` when overriding defaults via env |
| `OPENAI_API_KEY` | — | OpenAI-compatible API key |
| `DASHSCOPE_API_KEY` | — | Alibaba DashScope API key |

For Compose, put these in `docker/.env`. Values only reach the container if listed under `environment:` in `docker-compose.yml` (Compose interpolates `.env`; it does not auto-export every key). Alternatively write the same keys into the mounted data dir as `~/.happyclaw/env`.

### Node.js

The runtime image includes Node.js 20 (`node`, `npm`, and `npx`), the same major version used to build the dashboard, so skills and expert shells that need Node can run. The toolchain is copied from the `node:20-slim` build stage. Existing deployments must rebuild or upgrade the image to receive it; restarting an older image is insufficient. Packages installed with `npm install -g` live in the container writable layer and must be reinstalled after the container is recreated.

### Knowledge-base dependencies

The image includes the `local-embedding` and `knowledge-ocr` extras alongside
`browser`. Both dependency installation steps use these extras, so the final
`uv sync` retains them. The build checks that the embedding and OCR modules can
be imported; it does not download model weights or enable either feature.

Dependencies installed from the dashboard into a running container live in its
writable layer and disappear when that container is recreated. Rebuild or pull
an image containing these extras instead of relying on runtime installation.
Keep the `/data/.octop` volume to preserve settings, knowledge indexes and the
local embedding model cache. Existing deployments must rebuild or upgrade their
image to receive these dependencies; restarting an older image is insufficient.

### Data persistence

- Compose mounts host `~/.happyclaw` → container `/data/.octop`
- `docker run` example uses named volume `octop-data`
- First boot: initializes the runtime directory and database, then creates the local owner; no password, wizard, or `credential.txt`
- Upgrade: keep the data volume and rebuild the image; schema migrations run at startup
- Backup: `docker exec -it octop octop backup create --include-chats`, then `docker cp` the archive out

### Health check

The image probes `GET /api/health`:

```bash
curl http://localhost:8088/api/health
```

### Operations

```bash
docker logs -f octop
docker exec -it octop octop --version
docker compose -f docker/docker-compose.yml down
docker compose -f docker/docker-compose.yml up -d --build
```
