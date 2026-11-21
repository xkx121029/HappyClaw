/**
 * The local-owner profile the chat logic reads, split out of
 * `dashboard/src/api/modules/auth.ts` (which pulls the whole login surface).
 * Only the fields `useCurrentUser` and the message author stamp use.
 */
export interface OctopUser {
  id: number;
  username: string;
  /** Role-template public id: admin | user | custom ULID. */
  role: string;
  display_name: string | null;
  locale: string;
  permissions?: string[];
  sso_linked?: boolean;
  sso_kind?: string | null;
  has_password?: boolean;
  /** Preset character id. Empty means the built-in default portrait. */
  avatar_icon?: string | null;
  /** Uploaded portrait. Shown ahead of the preset when present. */
  avatar_url?: string | null;
}
