import { useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import cx from "classnames";

import { MobileIcon, type MobileIconName } from "./MobileIcon";
import { TAB_ITEMS, activeTabKey } from "../mobileNav";

const ICONS: Record<string, MobileIconName> = {
  home: "home",
  quick: "zap",
  chat: "chat",
  bao: "bao",
  experts: "experts",
  more: "more",
};

export function MobileTabBar() {
  const navigate = useNavigate();
  const location = useLocation();
  const { t } = useTranslation();
  const active = activeTabKey(location.pathname);

  return (
    <nav
      className="m-tabbar"
      data-testid="m-tabbar"
      aria-label={t("mobile.tabs.mainNav", "主导航")}
      style={{ gridTemplateColumns: `repeat(${TAB_ITEMS.length}, 1fr)` }}
    >
      {TAB_ITEMS.map((item) => {
        const isActive = active === item.key;
        return (
          <button
            key={item.key}
            type="button"
            className={cx("m-tab", isActive && "is-active")}
            aria-current={isActive ? "page" : undefined}
            onClick={() => {
              if (isActive) {
                document
                  .querySelector(".m-page-scroll")
                  ?.scrollTo({ top: 0, behavior: "smooth" });
                return;
              }
              navigate(item.path);
            }}
          >
            <span className="m-tab-inner">
              <MobileIcon name={ICONS[item.key]} size={23} />
              <span>{t(item.labelKey, item.label)}</span>
            </span>
          </button>
        );
      })}
    </nav>
  );
}
