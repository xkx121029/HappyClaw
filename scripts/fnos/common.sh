#!/bin/bash
#
# Octop FnOS 打包共享函数库。
# 仓库唯一来源：scripts/fnos/common.sh
# 打包时由 scripts/build-fpk.sh 注入到包内 cmd/common.sh；
# fnos/docker/ 与 fnos/native/ 的 cmd 脚本及 app/bin 脚本统一 source 本文件，
# 避免 find_python312 / fix_ownership_and_perms / free_octop_ports 重复维护。
#
set -u

# ---------------------------------------------------------------------------
# 杀掉 pid 及其子孙（先 TERM / 再由调用方决定 KILL）。
# 本地版 start 经 runuser 拉起 bin/octop，PID 文件里往往是外壳，真正
# 监听 8089 的是 exec 后的 Python 子进程；只杀外壳会留下孤儿占端口。
# ---------------------------------------------------------------------------
octop_kill_pid_tree() {
    local pid="${1:-}" sig="${2:-TERM}" child
    [ -n "$pid" ] || return 0
    for child in $(pgrep -P "$pid" 2>/dev/null || true); do
        octop_kill_pid_tree "$child" "$sig"
    done
    kill -s "$sig" "$pid" 2>/dev/null || true
}

octop_port_pids() {
    local port="$1" pids
    pids="$(ss -ltnp 2>/dev/null | grep -E "[:.]${port}([[:space:]]|$)" | sed -n 's/.*pid=\([0-9]*\).*/\1/p' | sort -u)" || true
    if [ -z "$pids" ] && command -v fuser >/dev/null 2>&1; then
        pids="$(fuser "${port}/tcp" 2>/dev/null | tr -cs '[:digit:]' ' ')" || true
    fi
    if [ -z "$pids" ] && command -v lsof >/dev/null 2>&1; then
        pids="$(lsof -ti tcp:"$port" 2>/dev/null)" || true
    fi
    printf '%s' "$pids"
}

# 等一组 pid 退出。第一参数是 0.2s 的轮询次数，其余为 pid。
octop_wait_pids_gone() {
    local rounds="${1:-15}" pid still i
    shift
    for i in $(seq 1 "$rounds"); do
        still=0
        for pid in "$@"; do
            [ -n "$pid" ] || continue
            if kill -0 "$pid" 2>/dev/null; then
                still=1
                break
            fi
        done
        [ "$still" = 0 ] && return 0
        sleep 0.2
    done
    return 1
}

# bin/octop 会 exec 成 python -m octop.cli.main run，命令行不再含启动器路径。
# 用安装时写入的 OCTOP_INSTALL_MODE=fpk-native 识别本包服务进程。
octop_fpk_native_run_pids() {
    local pid
    for pid in $(pgrep -f -- 'octop.cli.main run' 2>/dev/null || true); do
        [ -n "$pid" ] || continue
        if tr '\0' '\n' < "/proc/${pid}/environ" 2>/dev/null | grep -qx 'OCTOP_INSTALL_MODE=fpk-native'; then
            printf '%s\n' "$pid"
        fi
    done
}

octop_signal_pids() {
    local sig="$1" pid
    shift
    for pid in "$@"; do
        [ -n "$pid" ] || continue
        octop_kill_pid_tree "$pid" "$sig"
    done
}

# ---------------------------------------------------------------------------
# 释放 Octop 端口并清理本应用残留进程。
# 无参数：8088=Docker 版 + 8089=本地版（安装/卸载用）。
# 有参数：只释放指定端口（本地版 stop 只清 8089，避免误伤 Docker 版）。
# 仅清理：(1) 占用这些端口的进程；(2) 本安装目录下尚未 exec 的启动器；
# (3) 带 OCTOP_INSTALL_MODE=fpk-native 的 `octop.cli.main run`（仅当本次
# 要释放 8089 时）。不使用宽泛的 `pgrep -f octop`。
# ---------------------------------------------------------------------------
free_octop_ports() {
    local port pid pids pat appdir ports
    if [ "$#" -gt 0 ]; then
        ports="$*"
    else
        ports="8088 8089"
    fi
    for port in $ports; do
        pids="$(octop_port_pids "$port")"
        octop_signal_pids TERM $pids
        for pid in $pids; do
            [ -n "$pid" ] || continue
            echo "[octop] 已发送 TERM 给占用 ${port} 的进程 ${pid}" > "${TRIM_TEMP_LOGFILE:-/dev/null}" 2>/dev/null || true
        done
        octop_wait_pids_gone 10 $pids || true
        octop_signal_pids KILL $pids
        for pid in $pids; do
            [ -n "$pid" ] || continue
            if kill -0 "$pid" 2>/dev/null; then
                echo "[octop] 已强制 KILL 占用 ${port} 的进程 ${pid}" > "${TRIM_TEMP_LOGFILE:-/dev/null}" 2>/dev/null || true
            fi
        done
    done

    appdir="${TRIM_APPDEST:-/var/apps/octop-native}"
    for pat in "$appdir/bin/octop" "$appdir/app/bin/octop"; do
        pids="$(pgrep -f -- "$pat" 2>/dev/null | tr '\n' ' ')" || true
        [ -z "$pids" ] && continue
        echo "[octop] 发现本应用残留服务进程（$pat）: $pids，准备清理" > "${TRIM_TEMP_LOGFILE:-/dev/null}" 2>&1 || true
        octop_signal_pids TERM $pids
        octop_wait_pids_gone 10 $pids || true
        octop_signal_pids KILL $pids
    done

    case " ${ports} " in
        *" 8089 "*)
            pids="$(octop_fpk_native_run_pids | tr '\n' ' ')"
            if [ -n "$pids" ]; then
                echo "[octop] 发现 fpk-native 残留 run 进程: $pids，准备清理" > "${TRIM_TEMP_LOGFILE:-/dev/null}" 2>&1 || true
                octop_signal_pids TERM $pids
                octop_wait_pids_gone 10 $pids || true
                octop_signal_pids KILL $pids
            fi
            ;;
    esac
}

# ---------------------------------------------------------------------------
# 修正数据目录与 .env 的属主/权限。
# install_callback/config_callback 以 root 写 .env，若不 chown 给运行用户，
# 服务（octop-native）启动时 `. "$PKGVAR/.env"` 会 Permission denied。
# 若目录曾带 ACL，单纯 chmod 会把 mask 压成 ---，需 setfacl -b 清除。
# ---------------------------------------------------------------------------
fix_ownership_and_perms() {
    local pkgvar="$1" envfile="$2"
    local octop_user="octop-native"
    id "$octop_user" >/dev/null 2>&1 || {
        echo "[octop] 警告：${octop_user} 账户不存在，跳过数据目录 chown（服务将回退以 root 运行）" > "${TRIM_TEMP_LOGFILE:-/dev/null}" 2>&1 || true
        return 0
    }

    # 1) 应用数据目录与 .env 改属主为运行用户
    chown -R "$octop_user:$octop_user" "$pkgvar" 2>/dev/null || true
    chmod 700 "$pkgvar" 2>/dev/null || true
    [ -f "$envfile" ] && chmod 600 "$envfile" 2>/dev/null || true

    # 2) 清除 ACL，避免 chmod 把 mask 压成 --- 导致仍读不到
    if command -v setfacl >/dev/null 2>&1; then
        setfacl -b "$pkgvar" 2>/dev/null || true
        [ -f "$envfile" ] && setfacl -b "$envfile" 2>/dev/null || true
    fi

    # 3) 共享数据目录（@appshare）：确保属主正确且可进入
    if [ -n "${TRIM_DATA_SHARE_PATHS:-}" ]; then
        local ds="${TRIM_DATA_SHARE_PATHS%%:*}"
        chown -R "$octop_user:$octop_user" "$ds" 2>/dev/null || true
        local share_root="$ds"
        while [ "$share_root" != "/" ] && [ "$(basename "$(dirname "$share_root")")" != "@appshare" ]; do
            share_root="$(dirname "$share_root")"
        done
        chown "$octop_user:$octop_user" "$share_root" 2>/dev/null || true
        chmod 755 "$share_root" 2>/dev/null || true
        if command -v setfacl >/dev/null 2>&1; then
            setfacl -b "$share_root" 2>/dev/null || true
            setfacl -b "$ds" 2>/dev/null || true
        fi
    fi

    echo "[octop] 已修正数据目录/.env 属主与权限（${octop_user}:${octop_user}）" > "${TRIM_TEMP_LOGFILE:-/dev/null}" 2>&1 || true
}

# ---------------------------------------------------------------------------
# 本地版 FPK 架构：build-fpk.sh 写入 cmd/fpk-arch（amd64 / arm64）。
# 旧包没有该文件则跳过，避免升级路径误伤。
# 测试可设 OCTOP_FPK_ARCH_FILE / OCTOP_FPK_HOST_ARCH。
# ---------------------------------------------------------------------------
octop_host_fpk_arch() {
    if [ -n "${OCTOP_FPK_HOST_ARCH:-}" ]; then
        printf '%s' "$OCTOP_FPK_HOST_ARCH"
        return 0
    fi
    case "$(uname -m)" in
        aarch64|arm64) printf '%s' arm64 ;;
        x86_64|amd64) printf '%s' amd64 ;;
        *) uname -m ;;
    esac
}

octop_packed_fpk_arch() {
    local f here
    if [ -n "${OCTOP_FPK_ARCH_FILE:-}" ]; then
        [ -f "$OCTOP_FPK_ARCH_FILE" ] || return 1
        tr -d '[:space:]' < "$OCTOP_FPK_ARCH_FILE"
        return 0
    fi
    here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    for f in "$here/fpk-arch" "/var/apps/octop-native/cmd/fpk-arch"; do
        if [ -f "$f" ]; then
            tr -d '[:space:]' < "$f"
            return 0
        fi
    done
    return 1
}

octop_assert_native_arch() {
    local packed host
    packed="$(octop_packed_fpk_arch 2>/dev/null || true)"
    [ -n "$packed" ] || return 0
    host="$(octop_host_fpk_arch)"
    if [ "$packed" != "$host" ]; then
        echo "此本地版安装包是 ${packed}，当前设备是 ${host}。请改用对应架构的包：x86_64 用 Octop-fnos-native-amd64，ARM64 用 Octop-fnos-native-arm64。ARM 飞牛已装 Docker 时优先用 Docker 版。"
        return 1
    fi
    return 0
}

# ---------------------------------------------------------------------------
# 查找飞牛系统上的 Python 3.12（应用商店提供）。
# ---------------------------------------------------------------------------
find_python312() {
    local cand py
    for cand in \
        /var/apps/python312/target/bin/python3.12 \
        /usr/local/bin/python3.12 \
        /var/apps/python3.12/bin/python3.12 \
        python3.12
    do
        if command -v "$cand" >/dev/null 2>&1; then
            py="$(command -v "$cand")"
            if "$py" -c 'import sys; assert sys.version_info[:2] == (3,12)' >/dev/null 2>&1; then
                printf '%s' "$py"
                return 0
            fi
        fi
    done
    return 1
}

# ---------------------------------------------------------------------------
# 复用飞牛已装的 Node.js（开发工具），供专家 shell / 技能 / npx 使用。
# 不强制安装：找不到就保持 PATH 不变。已在 PATH 上则不改。
# 测试可设 OCTOP_FNOS_NODE_BIN_DIRS（冒号分隔）。
# ---------------------------------------------------------------------------
octop_fnos_node_candidate_dirs() {
    local d oldifs
    if [ -n "${OCTOP_FNOS_NODE_BIN_DIRS:-}" ]; then
        oldifs="$IFS"
        IFS=':'
        for d in $OCTOP_FNOS_NODE_BIN_DIRS; do
            [ -n "$d" ] && printf '%s\n' "$d"
        done
        IFS="$oldifs"
        return 0
    fi
    printf '%s\n' \
        /usr/local/bin \
        /var/apps/nodejs/target/bin \
        /var/apps/nodejs/bin \
        /var/apps/NodeJS/target/bin \
        /var/apps/node/target/bin
    for d in /var/apps/nodejs*/target/bin /var/apps/node[0-9]*/target/bin /var/apps/nodejs*/bin; do
        if [ -d "$d" ]; then
            printf '%s\n' "$d"
        fi
    done
}

octop_prepend_fnos_node_path() {
    local dir
    if command -v node >/dev/null 2>&1; then
        return 0
    fi
    while IFS= read -r dir; do
        [ -n "$dir" ] || continue
        if [ -x "$dir/node" ]; then
            case ":${PATH:-}:" in
                *":$dir:"*) ;;
                *) PATH="$dir${PATH:+:$PATH}" ;;
            esac
            export PATH
            return 0
        fi
    done <<EOF
$(octop_fnos_node_candidate_dirs)
EOF
    return 0
}

# 单人自托管没有账号：安装向导不再收集用户名/密码，下列回调也不读凭据。

# 从 .env 文件读取 KEY=VALUE 的值（容忍引号与行尾空白）。
octop_env_get() {
    local file="$1" key="$2" line
    [ -f "$file" ] || return 0
    line="$(grep -E "^${key}=" "$file" 2>/dev/null | tail -n 1)"
    line="${line#*=}"
    line="${line%\"}"; line="${line#\"}"
    printf '%s' "$line"
}

# 原地更新 .env 中的单个 KEY（保留其余行）；不存在则创建。
# 纯 bash 实现：密码可能包含 | & / 等 sed 特殊字符，不能用 sed 替换。
octop_env_set() {
    local file="$1" key="$2" value="$3" tmp line
    if [ -f "$file" ]; then
        tmp="${file}.tmp.$$"
        : > "$tmp"
        while IFS= read -r line || [ -n "$line" ]; do
            case "$line" in
                "${key}="*) ;;
                *) printf '%s\n' "$line" >> "$tmp" ;;
            esac
        done < "$file"
        printf '%s=%s\n' "$key" "$value" >> "$tmp"
        mv -f "$tmp" "$file"
    else
        printf '%s=%s\n' "$key" "$value" > "$file"
    fi
    chmod 600 "$file" 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# Docker 版数据持久化：必须挂飞牛 data-share，不能写 /var/apps/<app>/share/。
#
# 旧 FPK 把 compose 绑到 /var/apps/octop/share/octop/data（单数 share，且
# 不是 @appshare）。应用中心重启 / 重建容器后该目录被清空或未挂载，
# entrypoint 看不到 octop.db 就再次 init，表现为「每次重启都要重新配置」。
# 官方 docker-project 在 compose up 时注入 TRIM_DATA_SHARE_PATHS
# （一般为 /volX/@appshare/octop/data）；本地版回调也读同一变量。
# ---------------------------------------------------------------------------

octop_legacy_docker_data_dir() {
    printf '%s' "/var/apps/octop/share/octop/data"
}

# 解析飞牛持久 data-share 目录。可选参数为 resource.json 里的 share name。
octop_data_share_dir() {
    local share_name="${1:-}" app="${TRIM_APPNAME:-octop}" cand dir
    if [ -z "$share_name" ]; then
        case "$app" in
            octop-native) share_name="octop-native/data" ;;
            *) share_name="octop/data" ;;
        esac
    fi
    if [ -n "${TRIM_DATA_SHARE_PATHS:-}" ]; then
        dir="${TRIM_DATA_SHARE_PATHS%%:*}"
        if [ -n "$dir" ]; then
            printf '%s' "$dir"
            return 0
        fi
    fi
    cand="/var/apps/${app}/shares/${share_name}"
    if [ -d "$cand" ]; then
        printf '%s' "$cand"
        return 0
    fi
    if [ -n "${TRIM_APPDEST:-}" ]; then
        cand="$(dirname "$TRIM_APPDEST")/shares/${share_name}"
        if [ -d "$cand" ]; then
            printf '%s' "$cand"
            return 0
        fi
    fi
    for cand in /vol*/@appshare/"${share_name}"; do
        if [ -d "$cand" ]; then
            printf '%s' "$cand"
            return 0
        fi
    done
    printf '%s' "/var/apps/${app}/shares/${share_name}"
}

# 旧绑定目录里若有 octop.db / config.json，迁到 share/.octop（不覆盖已有库）。
octop_migrate_legacy_docker_data() {
    local dest="$1" src home
    src="$(octop_legacy_docker_data_dir)"
    [ -n "$dest" ] || return 0
    home="${dest}/.octop"
    mkdir -p "$home"
    [ -d "$src" ] || return 0
    [ "$src" = "$home" ] && return 0
    [ "$src" = "$dest" ] && return 0
    if [ -f "${home}/octop.db" ]; then
        return 0
    fi
    if [ -f "${src}/octop.db" ] || [ -f "${src}/config.json" ]; then
        cp -a "${src}/." "${home}/" 2>/dev/null || true
        echo "[octop] 已将旧数据目录 ${src} 迁移到 ${home}" > "${TRIM_TEMP_LOGFILE:-/dev/null}" 2>/dev/null || true
    fi
}

# 飞牛 docker-project 的 compose 工作目录（payload 与 @appcenter 运行副本）。
octop_docker_compose_dirs() {
    local d
    [ -n "${TRIM_APPDEST:-}" ] && printf '%s\n' "${TRIM_APPDEST}/docker"
    printf '%s\n' "/var/apps/octop/target/docker"
    for d in /vol*/@appcenter/octop; do
        if [ -d "$d" ]; then
            printf '%s\n' "${d}/docker"
        fi
    done
}

# 只把数据卷写成绝对路径，并删掉 env_file（缺文件 compose 会直接失败）。
octop_sync_fnos_compose() {
    local compose="$1" data_dir="$2" env_file="${3:-}" bind tmp line in_env_file=0
    [ -f "$compose" ] || return 0
    [ -n "$data_dir" ] || return 0
    bind="${data_dir}/.octop"
    mkdir -p "$bind"
    tmp="${compose}.tmp.$$"
    : > "$tmp"
    while IFS= read -r line || [ -n "$line" ]; do
        case "$line" in
            *"env_file:"*)
                in_env_file=1
                continue
                ;;
        esac
        if [ "$in_env_file" = 1 ]; then
            case "$line" in
                *" - "*|*" -"*)
                    continue
                    ;;
                *)
                    in_env_file=0
                    ;;
            esac
        fi
        case "$line" in
            *":/data/.octop"*)
                printf '      - "%s:/data/.octop"\n' "$bind" >> "$tmp"
                ;;
            *)
                printf '%s\n' "$line" >> "$tmp"
                ;;
        esac
    done < "$compose"
    mv -f "$tmp" "$compose"
}

# 把 .env 拷到飞牛实际执行 compose 的目录（含 /volX/@appcenter/octop/docker）。
octop_distribute_docker_env() {
    local src="$1" data_dir="${2:-}" d dest seen=""
    [ -f "$src" ] || return 0
    [ -n "$data_dir" ] || data_dir="$(octop_env_get "$src" TRIM_DATA_SHARE_PATHS)"
    while IFS= read -r d; do
        [ -n "$d" ] || continue
        case " $seen " in
            *" $d "*) continue ;;
        esac
        seen="${seen} ${d}"
        mkdir -p "$d" 2>/dev/null || continue
        dest="${d}/.env"
        if [ "$dest" != "$src" ]; then
            cp -a "$src" "$dest" 2>/dev/null || true
            chmod 600 "$dest" 2>/dev/null || true
        fi
        if [ -f "${d}/docker-compose.yaml" ]; then
            octop_sync_fnos_compose "${d}/docker-compose.yaml" "$data_dir" "$src"
        fi
    done <<EOF
$(octop_docker_compose_dirs)
EOF
}

# docker/.env 在 target/ 下，升级会整目录替换；副本落到 TRIM_PKGVAR（@appdata）。
octop_persist_docker_env() {
    local env_file="$1" pkgvar="${TRIM_PKGVAR:-/var/apps/octop/var}"
    [ -f "$env_file" ] || return 0
    mkdir -p "$pkgvar"
    cp -a "$env_file" "${pkgvar}/docker.env" 2>/dev/null || true
}

octop_restore_docker_env() {
    local env_file="$1" pkgvar="${TRIM_PKGVAR:-/var/apps/octop/var}"
    [ -f "$env_file" ] && return 0
    [ -f "${pkgvar}/docker.env" ] || return 0
    mkdir -p "$(dirname "$env_file")"
    cp -a "${pkgvar}/docker.env" "$env_file" 2>/dev/null || true
}

# 解析 data-share、迁旧数据、把路径写进 compose 插值用的 .env。
octop_prepare_docker_persist() {
    local env_file="$1" data_dir compose
    octop_restore_docker_env "$env_file"
    data_dir="$(octop_data_share_dir octop/data)"
    mkdir -p "${data_dir}/.octop"
    octop_migrate_legacy_docker_data "$data_dir"
    octop_env_set "$env_file" TRIM_DATA_SHARE_PATHS "$data_dir"
    octop_env_set "$env_file" OCTOP_DATA "$data_dir"
    octop_persist_docker_env "$env_file"
    compose="$(dirname "$env_file")/docker-compose.yaml"
    octop_sync_fnos_compose "$compose" "$data_dir" "$env_file"
    octop_distribute_docker_env "$env_file" "$data_dir"
    printf '%s' "$data_dir"
}

# 渲染应用「设置」窗口（wizard/config）：单人版只提示数据目录与配置入口。
# wizard_dir 为已安装包的向导目录（/var/apps/<app>/wizard），template 为
# 包内载荷自带的模板文件路径。任一文件缺失则静默跳过（不影响安装）。
octop_render_config_wizard() {
    local template="$1" wizard_dir="$2" data_dir="${3:-}" target tmp content dir_label
    [ -f "$template" ] || return 0
    [ -d "$wizard_dir" ] || return 0
    target="${wizard_dir}/config"
    content="$(cat "$template" 2>/dev/null)" || return 0
    dir_label="${data_dir:-应用共享 / HappyClaw 数据目录}"
    content="${content//<octop-data-dir>/${dir_label}}"
    tmp="${target}.tmp.$$"
    if printf '%s\n' "$content" > "$tmp" 2>/dev/null; then
        mv -f "$tmp" "$target" 2>/dev/null || rm -f "$tmp"
    fi
    return 0
}
