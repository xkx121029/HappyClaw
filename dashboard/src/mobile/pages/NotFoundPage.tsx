import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { MobilePage } from "../components/MobilePage";
import { MobileEmpty } from "../components/MobileEmpty";

export function NotFoundPage() {
  const { t } = useTranslation();
  return (
    <MobilePage title={t("mobile.notFound.title", "页面不存在")}>
      <MobileEmpty
        icon="alert"
        title={t("mobile.notFound.headline", "找不到这个页面")}
        description={t(
          "mobile.notFound.description",
          "路径可能已变更，回到首页继续。",
        )}
        action={
          <Link className="m-btn m-btn--primary" to="/m/home">
            {t("mobile.notFound.backHome", "回到首页")}
          </Link>
        }
      />
    </MobilePage>
  );
}
