/**
 * Untyped translator for the ported chat logic.
 *
 * `web/src/lib/i18n` augments i18next with the keys that exist in
 * `web/src/locales`, which is what makes `t("chat.…")` a compile-time check.
 * The chat namespace being migrated still carries the dashboard's key set
 * (hundreds of entries, `chat.*`, `sessions.*`, `apiErrors.*`), so the ported
 * modules cannot satisfy that check until those bundles move over with the UI
 * layer. This returns the same runtime translator with the generic signature,
 * so behaviour is unchanged and lookups still resolve from the one i18next
 * instance.
 *
 * Delete this in favour of `useTranslation()` once `chat.json` holds the
 * migrated keys — by then every call site is checked again for free.
 */
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";

export function useChatT(): TFunction {
  const { t } = useTranslation();
  return t as unknown as TFunction;
}
