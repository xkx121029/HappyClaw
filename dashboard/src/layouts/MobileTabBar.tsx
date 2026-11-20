import { lazy, Suspense, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";
import { CircleUserRound, House, MessagesSquare } from "lucide-react";
import cx from "classnames";
import { Mascot } from "../components/Mascot";
import styles from "./MobileTabBar.module.less";

// The "mine" sheet is a modal, so its markup and styles only matter while it
// is open; a static import shipped it with every phone page.
const MobileMoreSheet = lazy(() => import("./MobileMoreSheet"));

/**
 * Bottom app navigation for phones.
 *
 * Deliberately a flex sibling of the page column (not `position: fixed`): the
 * content area then genuinely ends above the bar, so no page has to reserve
 * space for it and the iOS home-indicator inset is paid exactly once.
 *
 * "Mine" is a bottom sheet rather than a route: the destinations it lists are
 * the sidebar catalog, and pulling the sheet down returns to the current page.
 */
export default function MobileTabBar() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [mineOpen, setMineOpen] = useState(false);

  const tabs = [
    {
      key: "home",
      label: t("nav.home", "主页"),
      active: pathname === "/home" || pathname === "/",
      icon: <House size={21} strokeWidth={1.8} />,
      onSelect: () => navigate("/home"),
    },
    {
      key: "chat",
      label: t("nav.chat", "对话"),
      active: pathname === "/chat" || pathname.startsWith("/chat/"),
      icon: <MessagesSquare size={21} strokeWidth={1.8} />,
      onSelect: () => navigate("/chat"),
    },
    {
      key: "bao",
      label: t("bao.title", "宝"),
      active: pathname === "/bao",
      icon: (
        <Mascot
          size={21}
          state="idle"
          surface="var(--fn-bg-elevated)"
          className={styles.mascot}
        />
      ),
      onSelect: () => navigate("/bao"),
    },
  ];

  return (
    <>
      <nav className={styles.bar} aria-label={t("nav.mobileTabs", "主导航")}>
        {tabs.map((tab) => (
          <button
            key={tab.key}
            type="button"
            className={cx(styles.tab, tab.active && styles.tabActive)}
            aria-current={tab.active ? "page" : undefined}
            onClick={tab.onSelect}
          >
            <span className={styles.icon} aria-hidden>
              {tab.icon}
            </span>
            <span className={styles.label}>{tab.label}</span>
          </button>
        ))}
        <button
          type="button"
          className={cx(styles.tab, mineOpen && styles.tabActive)}
          aria-expanded={mineOpen}
          aria-haspopup="dialog"
          onClick={() => setMineOpen(true)}
        >
          <span className={styles.icon} aria-hidden>
            <CircleUserRound size={21} strokeWidth={1.8} />
          </span>
          <span className={styles.label}>{t("nav.mine", "我的")}</span>
        </button>
      </nav>

      {mineOpen && (
        <Suspense fallback={null}>
          <MobileMoreSheet open onClose={() => setMineOpen(false)} />
        </Suspense>
      )}
    </>
  );
}
