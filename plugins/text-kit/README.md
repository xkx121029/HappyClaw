# 文本工具箱 (text-kit)

四个纯本地小工具，不联网、不落盘。

| 工具 | 参数 | 说明 |
|---|---|---|
| `json_format` | `text`、`indent=2` | 校验并格式化 JSON，失败时给出行列号 |
| `yaml_check` | `text` | 校验 YAML 并列出顶层键（依赖 Octop 自带的 PyYAML） |
| `timestamp_convert` | `value`、`tz="Asia/Shanghai"` | Unix 秒/毫秒时间戳转可读时间，自动识别量级 |
| `base64_text` | `text`、`mode="encode"` | Base64 编解码，UTF-8 文本 |

安装：`octop plugin install ./plugins/text-kit`
