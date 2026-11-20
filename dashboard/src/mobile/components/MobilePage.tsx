import { useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import cx from "classnames";
import { useTranslation } from "react-i18next";

import { MobileIcon } from "./MobileIcon";
import { useSwipeBack } from "../hooks/useSwipeBack";

interface MobilePageProps {
  title?: string;
  subtitle?: ReactNode;
  eyebrow?: ReactNode;
  back?: boolean;
  onBack?: () => void;
  actions?: ReactNode;
  /** Disable the inner scroll container (chat-style pages own it). */
  scroll?: boolean;
  padded?: boolean;
  children: ReactNode;
}

/**
 * Standard mobile page scaffold: translucent top bar with back, a large title
 * on root pages, and a dedicated scroll container that resets per page.
 */
export function MobilePage({
  title,
  subtitle,
  eyebrow,
  back = false,
  onBack,
  actions,
  scroll = true,
  padded = true,
  children,
}: MobilePageProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const scrollRef = useRef<HTMLDivElement>(null);
  const [scrolled, setScrolled] = useState(false);
  const goBack = onBack ?? (() => navigate(-1));

  useSwipeBack({ enabled: back, onBack: goBack });

  const handleScroll = () => {
    const next = (scrollRef.current?.scrollTop ?? 0) > 4;
    if (next !== scrolled) setScrolled(next);
  };

  return (
    <div
      className="m-page-scroll"
      ref={scrollRef}
      onScroll={scroll ? handleScroll : undefined}
      style={scroll ? undefined : { overflow: "hidden" }}
    >
      {back ? (
        <header className={cx("m-topbar", scrolled && "is-scrolled")}>
          <div className="m-topbar-side">
            <button
              type="button"
              className="m-iconbtn"
              aria-label={t("common.back", "返回")}
              onClick={goBack}
            >
              <MobileIcon name="back" />
            </button>
          </div>
          <div className="m-topbar-title">{title}</div>
          <div className="m-topbar-side m-topbar-side--right">{actions}</div>
        </header>
      ) : null}

      <div className={cx("m-page", !padded && "m-page--flush")}>
        {!back && (title || eyebrow || subtitle || actions) ? (
          <header className="m-pagehead">
            <div className="m-pagehead-main">
              {eyebrow ? <div className="m-eyebrow">{eyebrow}</div> : null}
              {title ? <h1 className="m-pagehead-title">{title}</h1> : null}
              {subtitle ? (
                <div className="m-pagehead-sub">{subtitle}</div>
              ) : null}
            </div>
            {actions ? (
              <div className="m-pagehead-actions">{actions}</div>
            ) : null}
          </header>
        ) : null}
        {children}
      </div>
    </div>
  );
}
