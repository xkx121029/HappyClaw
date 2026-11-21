import "i18next";

import type enCommon from "@/locales/en/common.json";
import type enChat from "@/locales/en/chat.json";
import type enDesign from "@/locales/en/design.json";
import type enSettings from "@/locales/en/settings.json";

/**
 * Typed i18n keys: `t("chat.composer.placeholder")` is checked at compile time
 * and a misspelled key is a build error, not a string rendered at runtime.
 */
declare module "i18next" {
  interface CustomTypeOptions {
    defaultNS: "common";
    resources: {
      common: typeof enCommon;
      chat: typeof enChat;
      settings: typeof enSettings;
      design: typeof enDesign;
    };
  }
}
