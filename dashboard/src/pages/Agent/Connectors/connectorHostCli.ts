export function isHostCliConnector(kind: string): boolean {
  return [
    "feishu-cli",
    "wecom-cli",
    "agently-cli",
    "obsidian-cli",
    "dingtalk-cli",
  ].includes(kind);
}
