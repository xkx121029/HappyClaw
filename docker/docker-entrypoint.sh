#!/usr/bin/env bash
# =============================================================================
# HappyClaw 容器入口脚本
#
# 环境变量:
#   HOME                      — 必须为 /data，使 ~/.octop 映射到数据卷
#   HAPPYCLAW_PORT                — 服务端口（默认: 8088）
#
# 单人版说明：HappyClaw 没有账号步骤。首次启动只建目录、跑迁移，随后的
# `octop run` 自动绑定本机使用者；入口脚本不创建管理员，也不写任何凭据文件。
#
# 初始化标记（issue #1866）：PostgreSQL 等外部数据库不会在数据卷生成
# octop.db，仅凭 DB_FILE 判断会在每次重启重复执行 octop init。octop init
# 成功后写入 /data/.octop/.initialized，重启命中该标记即跳过引导直接启动。
#
# 旧部署的 HAPPYCLAW_DEFAULT_PASSWORD / HAPPYCLAW_ADMIN_USERNAME / HAPPYCLAW_ADMIN_DISPLAY_NAME
# 在此不再读取；它们由 fnOS 包等旧安装流程直接传给 `octop init`（见
# scripts/fnos/common.sh），容器本身不需要。
# =============================================================================
set -euo pipefail

export HOME="${HOME:-/data}"
HAPPYCLAW_HOME="${HAPPYCLAW_HOME:-${HOME}/.octop}"
export HAPPYCLAW_HOME
DB_FILE="${HAPPYCLAW_HOME}/octop.db"
INIT_MARKER="${HAPPYCLAW_HOME}/.initialized"
PORT="${HAPPYCLAW_PORT:-8088}"

# Docker 默认 /dev/shm 为 64MB。桌面已打进镜像时，太小的话用户一点启用，Xvnc 就会失败。
# 只提示，不阻止 HappyClaw 本身启动。conf_dir 默认 /etc/octop-desktop，测试可传入临时目录。
octop_warn_small_shm() {
    local conf_dir="${1:-/etc/octop-desktop}"
    local bytes
    [ -d "$conf_dir" ] || return 0
    bytes="$(df -B1 --output=size /dev/shm 2>/dev/null | awk 'NR==2 {print $1}')"
    [ -n "${bytes:-}" ] || return 0
    if [ "$bytes" -lt 536870912 ]; then
        echo "[entrypoint] /dev/shm 只有 $((bytes / 1024 / 1024))MB。启用远程桌面需要约 1GB，请使用 docker run --shm-size=1g，或在 compose 中设置 shm_size: 1gb。" >&2
    fi
}

# 部分 ARM 虚拟机（飞牛在 Parallels 上）会把 CPU 特性报高，OpenBLAS / onnxruntime 随后 SIGILL。
# 基线 OpenBLAS 对真 ARM 只是少用一点新指令。探测失败只写日志，服务继续启动。
octop_prepare_arm_runtime() {
    local py log code
    case "$(uname -m)" in
        aarch64|arm64) ;;
        *) return 0 ;;
    esac
    if [ -z "${OPENBLAS_CORETYPE:-}" ]; then
        export OPENBLAS_CORETYPE=ARMV8
    fi
    py="/app/.venv/bin/python"
    [ -x "$py" ] || return 0
    log="$(mktemp)"
    set +e
    "$py" -c "import cv2, onnxruntime" >"$log" 2>&1
    code=$?
    set -e
    if [ "$code" -eq 132 ] || grep -qi 'illegal instruction' "$log"; then
        echo "[entrypoint] cv2/onnxruntime 在这台 CPU 上出现非法指令（退出码 ${code}）。知识库 OCR 和本地向量不可用。ARM 虚拟机上常见（issues #2190、#2301）。HappyClaw 仍会启动。" >&2
    fi
    rm -f "$log"
}

octop_entrypoint_main() {
    octop_prepare_arm_runtime
    octop_warn_small_shm

    if [ ! -f "$DB_FILE" ] && [ ! -f "$INIT_MARKER" ]; then
        echo "[entrypoint] 首次启动，正在初始化 HappyClaw..."
        mkdir -p "$HAPPYCLAW_HOME"
        if ! octop init --yes; then
            echo "[entrypoint] 初始化失败。若数据目录已有文件但没有 octop.db（或使用外部数据库后端），请检查卷挂载与数据库连接。" >&2
            exit 1
        fi
        touch "$INIT_MARKER"
        echo "[entrypoint] 已写入初始化标记 ${INIT_MARKER}，重启将跳过 octop init。"
    fi

    if [ $# -eq 0 ]; then
        echo "[entrypoint] 正在启动 HappyClaw，端口 $PORT..."
        exec octop run --host 0.0.0.0 --port "$PORT"
    fi

    if [ "$1" = "octop" ]; then
        echo "[entrypoint] 执行命令: $*"
        exec "$@"
    fi

    echo "[entrypoint] 执行命令: $*"
    exec "$@"
}

# Allow tests to source helpers without starting the server.
if [ "${HAPPYCLAW_ENTRYPOINT_LIB:-}" = "1" ]; then
    return 0 2>/dev/null || exit 0
fi

octop_entrypoint_main "$@"
