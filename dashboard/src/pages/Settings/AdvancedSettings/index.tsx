import { useTranslation } from "react-i18next";
import { Navigate, useSearchParams } from "react-router-dom";
import {
  Archive,
  Lock,
  RefreshCw,
  Smartphone,
  Variable,
  Activity,
} from "lucide-react";
import EnvironmentsPage from "../Environments";
import { ObservabilitySettingsPanel } from "../Observability";
import BackupRestorePanel from "../BackupRestore";
import { HttpsSettingsPanel } from "../HttpsSettings";
import { PhoneAccessPanel } from "../PhoneAccess";
import UpdateConfig from "./UpdateConfig";
import PageShell from "../../../layouts/PageShell";
import TabBar, { type TabBarItem } from "../../../components/TabLabel/TabBar";
import tabStyles from "./tabContent.module.less";
import ForbiddenPage from "../../../components/ForbiddenPage";
import { useGatedSearchTabs } from "../../../hooks/useGatedSearchTabs";
import { ADVANCED_TAB_PERMISSIONS } from "../../../utils/permissions";

type TabKey =
  | "env-vars"
  | "observability"
  | "backup"
  | "https"
  | "phone"
  | "updates";

const TABS: TabBarItem<TabKey>[] = [
  { key: "env-vars", labelKey: "nav.environments", icon: Variable },
  { key: "observability", labelKey: "nav.observability", icon: Activity },
  { key: "backup", labelKey: "nav.backupRestore", icon: Archive },
  { key: "https", labelKey: "nav.https", icon: Lock },
  { key: "phone", labelKey: "nav.phoneAccess", icon: Smartphone },
  { key: "updates", labelKey: "nav.checkUpdates", icon: RefreshCw },
];

function parseTab(raw: string | null): TabKey {
  if (
    raw === "observability" ||
    raw === "backup" ||
    raw === "https" ||
    raw === "phone" ||
    raw === "updates"
  ) {
    return raw;
  }
  // 单人模式不再有登录验证码 / passkey 配置，旧链接回落到环境变量。
  return "env-vars";
}

export default function AdvancedSettingsPage() {
  const { t } = useTranslation();
  const [searchParams] = useSearchParams();
  const { allowedTabs, activeTab, forbidden, selectTab } = useGatedSearchTabs({
    tabs: TABS,
    tabPermissions: ADVANCED_TAB_PERMISSIONS,
    parseTab,
    querylessKey: "env-vars",
  });

  const moved = searchParams.get("tab");
  if (moved === "voice" || moved === "search") {
    return <Navigate to={`/admin/models?tab=${moved}`} replace />;
  }
  if (moved === "bridge") {
    return <Navigate to="/bridge" replace />;
  }

  if (forbidden) return <ForbiddenPage />;

  const renderTab = () => {
    switch (activeTab) {
      case "env-vars":
        return <EnvironmentsPage />;
      case "observability":
        return <ObservabilitySettingsPanel />;
      case "backup":
        return <BackupRestorePanel />;
      case "https":
        return <HttpsSettingsPanel />;
      case "phone":
        return <PhoneAccessPanel />;
      case "updates":
        return <UpdateConfig />;
    }
  };

  return (
    <PageShell.Tabbed
      title={t("pageShell.adminAdvanced.title")}
      subtitle={t("pageShell.adminAdvanced.subtitle")}
      tabBar={
        <TabBar tabs={allowedTabs} activeKey={activeTab} onChange={selectTab} />
      }
    >
      <div className={tabStyles.tabContent}>{renderTab()}</div>
    </PageShell.Tabbed>
  );
}
