export function openAuthorizeLabel(
  kind: string,
  t: (key: string, fallback: string) => string,
): string {
  if (kind === "tencent-ima") {
    return t("connectors.openAuthorizePage", "打开授权页");
  }
  return t("connectors.openTokenPage", "打开授权页");
}

export function authCodeGuideLabel(
  kind: string,
  t: (key: string, fallback: string) => string,
): string {
  if (kind === "tencent-news") {
    return t("connectors.newsAuthGuide", "如何获取腾讯新闻 API Key");
  }
  return t("connectors.authCodeDoc", "查看如何获取授权码");
}
