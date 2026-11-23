import type { ConnectorCredentialsPreview } from "../../../api/modules/connectors";

export function secretFieldRules(required: boolean) {
  const trimRule = {
    validator: (_: unknown, value: unknown) => {
      const text = String(value ?? "").trim();
      if (required && !text) {
        return Promise.reject(new Error(""));
      }
      return Promise.resolve();
    },
  };
  return required ? [{ required: true, message: "" }, trimRule] : [trimRule];
}

export function configuredExtra(
  preview: ConnectorCredentialsPreview | undefined,
  key: string,
  t: (key: string, fallback: string) => string,
) {
  if (!preview?.[key]) return undefined;
  return t("connectors.secretConfigured", "已配置，留空表示不修改");
}
