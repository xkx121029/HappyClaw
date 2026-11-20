import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";
import {
  Check,
  ChevronRight,
  Copy,
  Monitor,
  Moon,
  Sun,
  Trash2,
} from "lucide-react";
import cx from "classnames";
import type { ThemePreference } from "../context/ThemeContext";
import { useTheme } from "../context/ThemeContext";
import { preferencesApi } from "../api/modules/preferences";
import { applyUserLocale } from "../utils/locale";
import { message } from "@/utils/antdMessage";
import { clearConnection, readConnection } from "../utils/mobileEndpoint";
import { buildNavSections, navSectionLabel } from "./sidebarNav";
import styles from "./MobileMoreSheet.module.less";

interface MobileMoreSheetProps {
  open: boolean;
  onClose: () => void;
}

const DISMISS_AFTER_DRAG_PX = 90;

const THEME_OPTIONS: {
  key: ThemePreference;
  icon: typeof Monitor;
  labelKey: string;
  fallback: string;
}[] = [
  {
    key: "system",
    icon: Monitor,
    labelKey: "header.themeSystem",
    fallback: "跟随系统",
  },
  { key: "light", icon: Sun, labelKey: "header.themeLight", fallback: "浅色" },
  { key: "dark", icon: Moon, labelKey: "header.themeDark", fallback: "深色" },
];

const LANGUAGE_OPTIONS = [
  { key: "zh", label: "简体中文", short: "中" },
  { key: "en", label: "English", short: "EN" },
];

/** Exact path, or a nested route under it (never a sibling prefix match). */
function isActivePath(pathname: string, path: string): boolean {
  return pathname === path || pathname.startsWith(`${path}/`);
}

/**
 * "Mine" bottom sheet for phones.
 *
 * It replaces the old action that merely toggled the desktop drawer: the sheet
 * reuses the canonical sidebar navigation catalog, so every destination and
 * group the sidebar knows is reachable here, and it hosts the two settings a
 * phone user changes most often — theme and language.
 */
export default function MobileMoreSheet({
  open,
  onClose,
}: MobileMoreSheetProps) {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const { preference, setPreference } = useTheme();
  const panelRef = useRef<HTMLDivElement>(null);
  const restoreFocusRef = useRef<Element | null>(null);
  const [dragY, setDragY] = useState(0);
  const [savingLocale, setSavingLocale] = useState(false);
  const [connection] = useState(() => readConnection());
  const [confirmForget, setConfirmForget] = useState(false);
  const drag = useRef({ startY: 0, active: false });

  // 快速对话 已是底部一级 Tab，避免在这里出现第二个入口。
  const sections = useMemo(
    () =>
      buildNavSections()
        .map((section) => ({
          ...section,
          items: section.items.filter((item) => item.key !== "quick-chat"),
        }))
        .filter((section) => section.items.length > 0),
    [],
  );
  const currentLanguage = i18n.language?.startsWith("zh") ? "zh" : "en";
  const connectionAddress = connection?.baseUrl ?? window.location.origin;

  const handleClose = useCallback(() => {
    setDragY(0);
    onClose();
  }, [onClose]);

  useEffect(() => {
    if (!open) return;
    restoreFocusRef.current = document.activeElement;
    panelRef.current?.focus();
    setConfirmForget(false);

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !event.defaultPrevented) {
        event.preventDefault();
        handleClose();
      }
    };
    window.addEventListener("keydown", onKeyDown);

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    return () => {
      window.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      const target = restoreFocusRef.current;
      if (target instanceof HTMLElement) target.focus();
    };
  }, [handleClose, open]);

  const copyAddress = async () => {
    if (!connection) return;
    try {
      await navigator.clipboard.writeText(connection.baseUrl);
      message.success(t("mobileConnect.copied", "连接地址已复制"));
    } catch {
      message.error(
        t("mobileConnect.copyFailed", "复制失败，请长按地址手动复制"),
      );
    }
  };

  // Drop a saved address so the app goes back to same-origin.
  const forgetServer = () => {
    clearConnection();
    window.location.reload();
  };

  const changeLanguage = async (lang: string) => {
    if (lang === currentLanguage || savingLocale) return;
    setSavingLocale(true);
    try {
      const prefs = await preferencesApi.setLocale(lang);
      await applyUserLocale(prefs.locale);
    } catch {
      message.error(t("language.saveFailed", "保存语言偏好失败"));
    } finally {
      setSavingLocale(false);
    }
  };

  if (!open) return null;

  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    drag.current = { startY: event.clientY, active: true };
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!drag.current.active) return;
    setDragY(Math.max(0, event.clientY - drag.current.startY));
  };

  const endDrag = () => {
    if (!drag.current.active) return;
    drag.current.active = false;
    if (dragY > DISMISS_AFTER_DRAG_PX) {
      handleClose();
      return;
    }
    setDragY(0);
  };

  return createPortal(
    <div className={styles.root} role="presentation">
      <div
        className={styles.backdrop}
        role="presentation"
        style={{ opacity: Math.max(0.2, 1 - dragY / 320) }}
        onClick={handleClose}
      />
      <div
        ref={panelRef}
        className={cx(
          styles.panel,
          drag.current.active && styles.panelDragging,
        )}
        style={{ transform: `translateY(${dragY}px)` }}
        role="dialog"
        aria-modal="true"
        aria-label={t("nav.mine", "我的")}
        tabIndex={-1}
      >
        <div
          className={styles.grabZone}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
        >
          <span className={styles.grabber} aria-hidden />
        </div>

        <div className={styles.head}>
          <p className={styles.title}>{t("nav.mine", "我的")}</p>
        </div>

        <div className={styles.body}>
          <section className={styles.block}>
            <h2 className={styles.blockTitle}>
              {t("mobileConnect.sectionTitle", "连接")}
            </h2>
            <div className={styles.connCard}>
              <div className={styles.connTop}>
                <span
                  className={cx(
                    styles.connDot,
                    connection && styles.connDotLive,
                  )}
                  aria-hidden
                />
                <span className={styles.connState}>
                  {connection
                    ? t("mobileConnect.connected", "已连接")
                    : t("mobileConnect.sameOrigin", "本机直连")}
                </span>
                {connection?.serverVersion ? (
                  <span className={styles.connVersion}>
                    {connection.serverVersion}
                  </span>
                ) : null}
              </div>
              <p className={styles.connAddress}>{connectionAddress}</p>
              {connection?.token ? (
                <p className={styles.connMeta}>
                  {t("mobileConnect.credentialSaved", "已保存访问凭据")}
                </p>
              ) : null}
              <div className={styles.connActions}>
                <button
                  type="button"
                  className={styles.connBtn}
                  onClick={() => void copyAddress()}
                >
                  <Copy size={15} strokeWidth={1.8} aria-hidden />
                  <span>{t("mobileConnect.copy", "复制")}</span>
                </button>
                {connection ? (
                  <button
                    type="button"
                    className={cx(styles.connBtn, styles.connDanger)}
                    onClick={() => {
                      if (confirmForget) {
                        forgetServer();
                        return;
                      }
                      setConfirmForget(true);
                    }}
                  >
                    <Trash2 size={15} strokeWidth={1.8} aria-hidden />
                    <span>
                      {confirmForget
                        ? t("mobileConnect.forgetConfirm", "确认断开")
                        : t("mobileConnect.forget", "恢复本机直连")}
                    </span>
                  </button>
                ) : null}
              </div>
            </div>
          </section>

          <section className={styles.block}>
            <h2 className={styles.blockTitle}>
              {t("theme.title", "外观主题")}
            </h2>
            <div className={styles.segment} role="group">
              {THEME_OPTIONS.map(({ key, icon: Icon, labelKey, fallback }) => {
                const active = preference === key;
                return (
                  <button
                    key={key}
                    type="button"
                    className={cx(
                      styles.segmentBtn,
                      active && styles.segmentActive,
                    )}
                    aria-pressed={active}
                    onClick={() => setPreference(key)}
                  >
                    <Icon size={16} strokeWidth={1.8} aria-hidden />
                    <span>{t(labelKey, fallback)}</span>
                  </button>
                );
              })}
            </div>
          </section>

          <section className={styles.block}>
            <h2 className={styles.blockTitle}>{t("language.title", "语言")}</h2>
            <div className={styles.segment} role="group">
              {LANGUAGE_OPTIONS.map(({ key, label, short }) => {
                const active = currentLanguage === key;
                return (
                  <button
                    key={key}
                    type="button"
                    className={cx(
                      styles.segmentBtn,
                      active && styles.segmentActive,
                    )}
                    aria-pressed={active}
                    disabled={savingLocale}
                    onClick={() => void changeLanguage(key)}
                  >
                    <span className={styles.langBadge} aria-hidden>
                      {short}
                    </span>
                    <span>{label}</span>
                  </button>
                );
              })}
            </div>
          </section>

          {sections.map((section, index) => {
            const label = navSectionLabel(section, t);
            return (
              <section
                key={section.id ?? `section-${index}`}
                className={styles.block}
              >
                {label ? <h2 className={styles.blockTitle}>{label}</h2> : null}
                <div className={styles.list}>
                  {section.items.map((item) => {
                    const active = isActivePath(pathname, item.path);
                    return (
                      <button
                        key={item.key}
                        type="button"
                        className={cx(styles.item, active && styles.itemActive)}
                        aria-current={active ? "page" : undefined}
                        onClick={() => {
                          handleClose();
                          navigate(item.path);
                        }}
                      >
                        <span className={styles.itemIcon} aria-hidden>
                          {item.icon}
                        </span>
                        <span className={styles.itemLabel}>
                          {t(item.labelKey)}
                        </span>
                        {active ? (
                          <Check
                            size={16}
                            strokeWidth={2}
                            className={styles.itemCheck}
                            aria-hidden
                          />
                        ) : (
                          <ChevronRight
                            size={16}
                            strokeWidth={1.8}
                            className={styles.itemChevron}
                            aria-hidden
                          />
                        )}
                      </button>
                    );
                  })}
                </div>
              </section>
            );
          })}
        </div>

        <div className={styles.safeBottom} />
      </div>
    </div>,
    document.body,
  );
}
