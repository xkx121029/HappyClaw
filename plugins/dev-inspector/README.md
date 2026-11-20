# 开发状态速览 (dev-inspector)

给"同时盯着好几个仓库和服务"用的只读检查工具。

## 工具

| 工具 | 参数 | 说明 |
|---|---|---|
| `repo_status` | `path="."` | 输出仓库根路径、分支、最近一条提交、未提交变更按类型和顶层目录的统计 |
| `listening_ports` | `port=0` | 列出本机 TCP 监听端口，传具体端口则只显示该端口 |

## 安全

- 只执行固定参数的只读 git 命令（`rev-parse` / `branch` / `log` / `status`）。
- `subprocess.run(..., shell=False)`，用户输入的路径只作为 `cwd`，不拼进命令。
- 端口读取用 Windows `netstat -ano` 或 Linux `ss -ltn`。

安装：`octop plugin install ./plugins/dev-inspector`
