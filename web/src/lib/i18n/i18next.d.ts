import "i18next";

import type enCommon from "@/locales/en/common.json";
import type enChat from "@/locales/en/chat.json";
import type enDesign from "@/locales/en/design.json";
import type enAgentConfig from "@/locales/en/agentConfig.json";
import type enHome from "@/locales/en/home.json";
import type enUsage from "@/locales/en/usage.json";
import type enSettings from "@/locales/en/settings.json";
import type enSetup from "@/locales/en/setup.json";

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
      home: typeof enHome;
      usage: typeof enUsage;
      agentConfig: typeof enAgentConfig;
      settings: typeof enSettings;
      setup: typeof enSetup;
      design: typeof enDesign;
    };
  }
}
