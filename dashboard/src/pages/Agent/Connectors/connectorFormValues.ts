import type { ResourceVisibilityMode } from "../../../api/modules/userGroups";
import type {
  ConnectorCatalogEntry,
  ConnectorInstanceDetail,
} from "../../../api/modules/connectors";

export function visibilityFromDetail(
  detail: {
    visibility?: ResourceVisibilityMode | null;
    shared?: boolean;
    group_ids?: string[] | null;
  } | null,
): {
  visibility: ResourceVisibilityMode;
  groupIds: string[];
} {
  if (!detail) return { visibility: "owner", groupIds: [] };
  if (detail.visibility === "groups") {
    return { visibility: "groups", groupIds: detail.group_ids ?? [] };
  }
  if (detail.visibility === "all" || detail.shared) {
    return { visibility: "all", groupIds: [] };
  }
  return { visibility: "owner", groupIds: [] };
}

export function visibilityFields(
  visibility: ResourceVisibilityMode,
  groupIds: string[],
) {
  return {
    visibility,
    group_ids: visibility === "groups" ? groupIds : [],
    shared: visibility !== "owner",
  };
}

export function previewToFormValues(
  entry: ConnectorCatalogEntry,
  detail: ConnectorInstanceDetail | null,
): Record<string, unknown> {
  if (!detail) {
    return {
      display_name: entry.name,
      description: entry.description,
      mail_provider: "qq",
      default_open: false,
    };
  }
  const preview = detail.credentials_preview ?? {};
  const values: Record<string, unknown> = {
    display_name: detail.display_name || entry.name,
    description: detail.description || entry.description,
    default_open:
      detail.default_open === true || detail.config?.default_open === true,
  };
  if (preview.email) values.email = preview.email;
  if (preview.mail_provider) values.mail_provider = preview.mail_provider;
  if (preview.imap_host) values.imap_host = preview.imap_host;
  if (preview.smtp_host) values.smtp_host = preview.smtp_host;
  if (preview.bkn) values.bkn = preview.bkn;
  if (preview.knowledge_base_id)
    values.knowledge_base_id = preview.knowledge_base_id;
  if (preview.app_id) values.app_id = preview.app_id;
  if (preview.bot_id) values.bot_id = preview.bot_id;
  if (preview.cli_config_key) values.cli_config_key = preview.cli_config_key;
  if (preview.default_as === "user") values.default_as = "user";
  if (preview.client_id) values.client_id = preview.client_id;
  if (preview.sdk_id) values.sdk_id = preview.sdk_id;
  if (entry.auth_kind === "oauth2" && preview.oauth_configured) {
    values.access_token = "__configured__";
  }
  if (entry.auth_kind === "custom_fields") {
    for (const field of entry.credential_fields ?? []) {
      if (field.secret) continue;
      const value = preview[field.key];
      if (Array.isArray(value)) {
        values[field.key] = value.join(", ");
      } else if (value !== undefined && value !== null) {
        values[field.key] = value;
      }
    }
  }
  return values;
}
