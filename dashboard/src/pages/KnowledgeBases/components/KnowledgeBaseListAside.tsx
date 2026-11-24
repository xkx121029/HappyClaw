import type { MenuProps } from "antd";
import { Button, Dropdown, Empty, List, Spin, Tag, Tooltip } from "antd";
import {
  MessageSquarePlus,
  MoreHorizontal,
  Pencil,
  Plus,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import cx from "classnames";

import type { OctopUser } from "../../../api/modules/auth";
import type { KnowledgeBase } from "../../../api/modules/knowledgeBases";
import { CopyableResourceId } from "../../../components/CopyableResourceId";
import {
  SharedAvatarMark,
  SharedResourceBadge,
} from "../../../components/SharedResourceBadge";
import { KnowledgeBaseAvatar } from "../knowledgeIcons";
import {
  canManageKnowledgeBase,
  formatKnowledgeOwner,
  isKnowledgeOwner,
} from "../knowledgePermissions";
import styles from "../index.module.less";

export interface KnowledgeBaseListAsideProps {
  bases: KnowledgeBase[];
  selectedId: string | null;
  user: OctopUser | null;
  loading: boolean;
  refreshing: boolean;
  usable: boolean;
  atBaseLimit: boolean;
  onRefresh: () => void;
  onCreate: () => void;
  onSelect: (base: KnowledgeBase) => void;
  addBaseToChat: (base: KnowledgeBase) => void;
  openEdit: (base: KnowledgeBase) => void;
  confirmDeleteBase: (base: KnowledgeBase) => void;
}

export function KnowledgeBaseListAside({
  bases,
  selectedId,
  user,
  loading,
  refreshing,
  usable,
  atBaseLimit,
  onRefresh,
  onCreate,
  onSelect,
  addBaseToChat,
  openEdit,
  confirmDeleteBase,
}: KnowledgeBaseListAsideProps) {
  const { t } = useTranslation();

  const baseMenuItems = (base: KnowledgeBase): MenuProps["items"] => {
    const canManage = canManageKnowledgeBase(base, user);
    const items: MenuProps["items"] = [];
    if (usable) {
      items.push({
        key: "addToChat",
        icon: <MessageSquarePlus size={14} />,
        label: t("knowledgeBases.addToChat"),
        onClick: ({ domEvent }) => {
          domEvent.stopPropagation();
          addBaseToChat(base);
        },
      });
    }
    if (canManage) {
      if (items.length > 0) {
        items.push({ type: "divider" });
      }
      items.push(
        {
          key: "edit",
          icon: <Pencil size={14} />,
          label: t("common.edit"),
          onClick: ({ domEvent }) => {
    domEvent.stopPropagation();
    openEdit(base);
          },
        },
        {
          key: "delete",
          icon: <Trash2 size={14} />,
          label: t("common.delete"),
          danger: true,
          onClick: ({ domEvent }) => {
    domEvent.stopPropagation();
    confirmDeleteBase(base);
          },
        },
      );
    }
    return items;
  };
  return (
    <aside className={styles.baseList}>
      <div className={styles.listPanelHeader}>
        <span className={styles.listPanelTitle}>
          {t("knowledgeBases.title")}
        </span>
      </div>
      <div className={styles.listActions}>
        <Button
          type="primary"
          icon={<Plus size={15} />}
          disabled={!usable || atBaseLimit}
          onClick={onCreate}
        >
          {t("knowledgeBases.create")}
        </Button>
        <Tooltip title={t("common.refresh")}>
          <Button
            icon={<RefreshCw size={15} />}
            loading={refreshing}
            onClick={() => onRefresh()}
          />
        </Tooltip>
      </div>
      {loading ? (
        <div className={styles.centered}>
          <Spin />
        </div>
      ) : (
        <List
          className={styles.list}
          split={false}
          dataSource={bases}
          locale={{
            emptyText: (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={t("knowledgeBases.empty")}
              />
            ),
          }}
          renderItem={(base) => (
            <List.Item
              className={styles.listRow}
              onClick={() => onSelect(base)}
            >
              <div
                className={cx(
                  styles.listItem,
                  base.id === selectedId && styles.active,
                )}
              >
                <div className={styles.listName}>
                  <SharedAvatarMark
                    shared={base.shared}
                    owned={isKnowledgeOwner(base, user)}
                    ownerName={formatKnowledgeOwner(base)}
                  >
                    <span className={styles.listIcon}>
                      <KnowledgeBaseAvatar
                        iconUrl={base.icon_url}
                        iconName={base.icon_name}
                        size={18}
                      />
                    </span>
                  </SharedAvatarMark>
                  <Tooltip title={base.name} placement="topLeft">
                    <span className={styles.listNameText}>
                      {base.name}
                    </span>
                  </Tooltip>
                  <SharedResourceBadge
                    shared={base.shared && isKnowledgeOwner(base, user)}
                    owned
                    ownerName={formatKnowledgeOwner(base)}
                  />
                  <div
                    className={styles.listId}
                    onClick={(event) => event.stopPropagation()}
                  >
                    <CopyableResourceId
                      inline
                      valueOnly
                      className={styles.listIdButton}
                      label={t("knowledgeBases.baseId")}
                      value={base.id}
                      copyTitle={t("knowledgeBases.copyBaseId")}
                    />
                  </div>
                  {canManageKnowledgeBase(base, user) || usable ? (
                    <Dropdown
                      menu={{ items: baseMenuItems(base) }}
                      trigger={["click"]}
                      placement="bottomRight"
                    >
                      <button
                        type="button"
                        className={styles.listMoreBtn}
                        aria-label={t("common.more")}
                        onClick={(event) => event.stopPropagation()}
                      >
                        <MoreHorizontal size={15} />
                      </button>
                    </Dropdown>
                  ) : null}
                </div>
                <Tooltip
                  title={
                    base.description ||
                    t("knowledgeBases.noDescription")
                  }
                  placement="topLeft"
                >
                  <div className={styles.listDescription}>
                    {base.description ||
                      t("knowledgeBases.noDescription")}
                  </div>
                </Tooltip>
                <div className={styles.listMeta}>
                  <span
                    className={styles.listCreator}
                    title={t("knowledgeBases.createdBy", {
                      name: formatKnowledgeOwner(base),
                    })}
                  >
                    {t("knowledgeBases.createdBy", {
                      name: formatKnowledgeOwner(base),
                    })}
                  </span>
                  <div className={styles.listMetaEnd}>
                    <Tag className={styles.listCountTag}>
                      {t("knowledgeBases.documentCount", {
                        count: base.doc_count,
                      })}
                    </Tag>
                    {base.default_open ? (
                      <div className={styles.listMetaBadges}>
                        <span
                          className={cx(
                            styles.listBadge,
                            styles.listBadgeDefaultOpen,
                          )}
                        >
                          {t("knowledgeBases.defaultOpenBadge")}
                        </span>
                      </div>
                    ) : null}
                  </div>
                </div>
              </div>
            </List.Item>
          )}
        />
      )}
    </aside>
  );
}
