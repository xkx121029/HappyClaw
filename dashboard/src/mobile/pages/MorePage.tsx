import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { updateApi } from "../../api/modules/update";
import { useAgent } from "../../context/AgentContext";
import { useCurrentUser } from "../../hooks/useCurrentUser";
import { MobileAvatar } from "../components/MobileAvatar";
import { MobileChip } from "../components/MobileChip";
import { MobileListRow } from "../components/MobileListRow";
import { MobilePage } from "../components/MobilePage";

export function MorePage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const user = useCurrentUser();
  const { activeAgent } = useAgent();
  const [version, setVersion] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    updateApi
      .getUpdateStatus()
      .then((status) => {
        if (alive) setVersion(status.current_version);
      })
      .catch(() => {
        /* 版本号取不到时留空 */
      });
    return () => {
      alive = false;
    };
  }, []);

  const displayName = user.display_name || t("mobile.more.me", "我");

  return (
    <MobilePage title={t("mobile.more.title", "我的")}>
      <div className="m-card">
        <div className="m-rowflex">
          <MobileAvatar name={displayName} src={user.avatar_url} size={52} />
          <div className="m-grow" style={{ minWidth: 0 }}>
            <div className="m-card-title">{displayName}</div>
            <div className="m-card-desc">
              {t("mobile.more.localMode", "单人本机模式 · 数据保存在本地")}
            </div>
          </div>
          <MobileChip tone="accent">
            {t("mobile.more.localChip", "本机")}
          </MobileChip>
        </div>
      </div>

      <div className="m-section">
        <div className="m-section-head">
          <div className="m-section-title">
            {t("mobile.more.groupContent", "对话与资料")}
          </div>
        </div>
        <div className="m-group">
          <MobileListRow
            icon="clock"
            title={t("mobile.nav.tasks", "任务")}
            subtitle={t("mobile.more.tasksSub", "定时任务与运行记录")}
            chevron
            onClick={() => navigate("/m/tasks")}
          />
          <MobileListRow
            icon="book"
            title={t("mobile.nav.knowledgeBases", "知识库")}
            subtitle={t("mobile.more.knowledgeSub", "资料与文档")}
            chevron
            onClick={() => navigate("/m/knowledge-bases")}
          />
          <MobileListRow
            icon="plug"
            title={t("mobile.nav.connectors", "连接器")}
            subtitle={t("mobile.more.connectorsSub", "工具与外部服务")}
            chevron
            onClick={() => navigate("/m/connectors")}
          />
          <MobileListRow
            icon="chart"
            title={t("mobile.more.usage", "用量统计")}
            subtitle={t("mobile.more.usageSub", "近 7 / 30 天 Token 消耗")}
            chevron
            onClick={() => navigate("/m/token-usage")}
          />
        </div>
      </div>

      <div className="m-section">
        <div className="m-section-head">
          <div className="m-section-title">
            {t("mobile.more.groupSettings", "设置")}
          </div>
        </div>
        <div className="m-group">
          <MobileListRow
            icon="spark"
            title={t("mobile.more.personalization", "个性化")}
            subtitle={t("mobile.more.personalizationSub", {
              name: activeAgent?.name ?? t("mobile.more.noExpert", "未选专家"),
              defaultValue: "外观、主题色、语言 · {{name}}",
            })}
            chevron
            onClick={() => navigate("/m/personalization")}
          />
          <MobileListRow
            icon="shield"
            title={t("mobile.more.admin", "管理")}
            subtitle={t("mobile.more.adminSub", "模型、安全、高级、插件")}
            chevron
            onClick={() => navigate("/m/admin")}
          />
          <MobileListRow
            icon="experts"
            title={t("mobile.more.switchExpert", "切换专家")}
            subtitle={
              activeAgent?.name ??
              t("mobile.more.chooseDefaultExpert", "选择默认专家")
            }
            chevron
            onClick={() => navigate("/m/experts")}
          />
        </div>
      </div>

      <div className="m-section">
        <div className="m-section-head">
          <div className="m-section-title">
            {t("mobile.more.groupAbout", "关于")}
          </div>
        </div>
        <div className="m-group">
          <MobileListRow
            title={t("mobile.more.version", "版本")}
            meta={version ?? "—"}
          />
          <MobileListRow
            title={t("mobile.more.baoAppearance", "宝的外观")}
            subtitle={t("mobile.more.baoAppearanceSub", "全站统一配置")}
            chevron
            onClick={() => navigate("/m/bao")}
          />
        </div>
      </div>
    </MobilePage>
  );
}
