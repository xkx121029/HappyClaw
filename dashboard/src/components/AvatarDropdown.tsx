import { useEffect, useState } from "react";
import { Drawer, Form, Input, Button, Segmented, Tooltip, Popover } from "antd";
import { message } from "@/utils/antdMessage";

import {
  ChevronDown,
  ChevronUp,
  Settings,
  Palette,
  CircleHelp,
  Github,
  RefreshCw,
  SlidersHorizontal,
  DatabaseBackup,
  HardDrive,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useCurrentUser, updateLocalProfile } from "../hooks/useCurrentUser";
import { applyUserLocale } from "../utils/locale";
import { useIsMobile } from "../hooks/useIsMobile";
import ThemeSwitcher from "./ThemeSwitcher";
import PaletteSwitcher from "./PaletteSwitcher";
import { useLayoutMode } from "../context/LayoutModeContext";
import type { LayoutMode } from "../layouts/layoutModeStorage";
import { ProfileAvatar, ProfileAvatarPicker } from "../pages/Admin/Users/ProfileAvatar";
import styles from "./AvatarDropdown.module.less";

const GITHUB_URL = "https://github.com/TencentCloud/Octop";
const HELP_FEEDBACK_URL = "https://octop.cloud";
const LOCAL_PROFILE_NAME_MAX = 32;

interface AvatarDropdownProps {
  /**
   * ``sidebar`` — brand-rail footer trigger (avatar [+ name when expanded]).
   * Default keeps a plain avatar button (legacy header style).
   */
  placement?: "default" | "sidebar";
  /** When placement is sidebar and true, show avatar only (collapsed rail). */
  compact?: boolean;
  /** Called before opening settings (e.g. close mobile nav drawer). */
  onBeforeOpenSettings?: () => void;
  /** Opens the sidebar layout editor. Omitted when that editor is unavailable. */
  onCustomizeNav?: () => void;
}

/**
 * 本机设置入口。
 *
 * 单人模式下这里不再有账号、角色、SSO 绑定与退出登录：只保留
 * 外观、语言、布局、本机头像 / 显示名，以及数据备份和更新入口。
 */
export default function AvatarDropdown({
  placement = "default",
  compact = false,
  onBeforeOpenSettings,
  onCustomizeNav,
}: AvatarDropdownProps) {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const profile = useCurrentUser();
  const isMobile = useIsMobile();
  const { layoutMode, setLayoutMode } = useLayoutMode();
  const [menuOpen, setMenuOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [profileForm] = Form.useForm<{ display_name: string }>();

  const currentLang = i18n.language?.startsWith("zh") ? "zh" : "en";
  const displayName = profile.display_name || t("account.me", "我");

  const deferOpen = (open: () => void) => {
    window.setTimeout(open, 0);
  };

  const openSettings = () => {
    setMenuOpen(false);
    onBeforeOpenSettings?.();
    profileForm.setFieldsValue({ display_name: profile.display_name || "" });
    deferOpen(() => setSettingsOpen(true));
  };

  // 全局快捷键 Ctrl/Cmd + , 由聊天页广播，本组件始终挂载在侧边栏。
  useEffect(() => {
    const onOpenSettings = () => openSettings();
    window.addEventListener("octop:open-settings", onOpenSettings);
    return () =>
      window.removeEventListener("octop:open-settings", onOpenSettings);
    // 设置入口只依赖稳定的表单实例与 prop，挂载一次即可。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const openCustomizeNav = () => {
    setMenuOpen(false);
    onBeforeOpenSettings?.();
    deferOpen(() => onCustomizeNav?.());
  };

  const goBackup = () => {
    setMenuOpen(false);
    navigate("/admin/advanced?tab=backup");
  };

  const handleSaveProfile = (values: { display_name: string }) => {
    const name = values.display_name?.trim().slice(0, LOCAL_PROFILE_NAME_MAX);
    updateLocalProfile({ display_name: name || t("account.me", "我") });
    message.success(t("account.savedLocal", "已保存到本机"));
  };

  const handleLocaleChange = (val: string) => {
    void applyUserLocale(val).catch(() => {
      message.error(t("account.localeFailed", "语言切换失败，请重试"));
    });
  };

  const avatar = (
    <ProfileAvatar
      key={`${profile.avatar_icon ?? ""}:${profile.avatar_url ?? ""}`}
      url={profile.avatar_url}
      icon={profile.avatar_icon}
      kind="user"
      className={styles.accountAvatar}
    />
  );

  const menuContent = (
    <div className={styles.menu}>
      <div className={styles.menuHeader}>
        <div className={styles.menuHeaderTop}>
          <span className={styles.menuDisplayName}>{displayName}</span>
        </div>
        <span className={styles.menuHandle}>
          {t("account.localOnly", "本机 · 单人模式")}
        </span>
      </div>

      <div className={styles.menuItemRow}>
        <div className={styles.menuItemLabel}>
          <Palette size={16} strokeWidth={1.8} />
          <span>{t("account.appearance")}</span>
        </div>
        <ThemeSwitcher compact />
      </div>

      <button type="button" className={styles.menuItem} onClick={openSettings}>
        <Settings size={16} strokeWidth={1.8} />
        <span>{t("account.settings")}</span>
      </button>

      <button type="button" className={styles.menuItem} onClick={goBackup}>
        <DatabaseBackup size={16} strokeWidth={1.8} />
        <span>{t("account.backup", "本机数据备份与恢复")}</span>
      </button>

      {onCustomizeNav ? (
        <button
          type="button"
          className={styles.menuItem}
          onClick={openCustomizeNav}
        >
          <SlidersHorizontal size={16} strokeWidth={1.8} />
          <span>{t("nav.customize")}</span>
        </button>
      ) : null}

      <button
        type="button"
        className={styles.menuItem}
        onClick={() => {
          setMenuOpen(false);
          navigate("/admin/advanced?tab=updates");
        }}
      >
        <RefreshCw size={16} strokeWidth={1.8} />
        <span>{t("account.checkUpdates")}</span>
      </button>

      <a
        className={styles.menuItem}
        href={HELP_FEEDBACK_URL}
        target="_blank"
        rel="noopener noreferrer"
        onClick={() => setMenuOpen(false)}
      >
        <CircleHelp size={16} strokeWidth={1.8} />
        <span>{t("account.helpFeedback")}</span>
      </a>

      <a
        className={styles.menuItem}
        href={GITHUB_URL}
        target="_blank"
        rel="noopener noreferrer"
        onClick={() => setMenuOpen(false)}
      >
        <Github size={16} strokeWidth={1.8} />
        <span>{t("account.projectUrl")}</span>
      </a>
    </div>
  );

  const triggerButton =
    placement === "sidebar" && !compact ? (
      <button type="button" className={styles.triggerExpanded}>
        {avatar}
        <span className={styles.triggerName}>{displayName}</span>
        {menuOpen ? (
          <ChevronUp
            size={14}
            strokeWidth={1.8}
            className={styles.triggerChevron}
          />
        ) : (
          <ChevronDown
            size={14}
            strokeWidth={1.8}
            className={styles.triggerChevron}
          />
        )}
      </button>
    ) : (
      <Tooltip
        title={placement === "sidebar" ? displayName : undefined}
        placement="right"
        mouseEnterDelay={0.3}
      >
        <span role="button" tabIndex={0} className={styles.triggerCompact}>
          {avatar}
        </span>
      </Tooltip>
    );

  const settingsBody = (
    <div className={styles.settingsBody}>
      <div className={styles.settingsIdentity}>
        <span className={styles.settingsIdentityName}>{displayName}</span>
        <span className={styles.settingsIdentityHandle}>
          {t("account.localOnly", "本机 · 单人模式")}
        </span>
      </div>

      <section className={styles.settingsSection}>
        <div className={styles.settingsSectionHead}>
          <h3 className={styles.settingsSectionTitle}>{t("account.avatar")}</h3>
          <p className={styles.settingsSectionDesc}>
            {t("account.avatarLocalHint", "头像只保存在本机浏览器。")}
          </p>
        </div>
        <div className={styles.settingsAvatarPicker}>
          <ProfileAvatarPicker
            kind="user"
            avatarUrl={profile.avatar_url}
            icon={profile.avatar_icon}
            onSelectIcon={(icon) => {
              updateLocalProfile({ avatar_icon: icon, avatar_url: null });
            }}
            onPick={() => {
              message.info(
                t(
                  "account.avatarUploadLocalOnly",
                  "单人模式暂不支持上传图片，请选择一个内置头像。",
                ),
              );
            }}
            onRemove={() => {
              updateLocalProfile({ avatar_icon: null, avatar_url: null });
            }}
          />
        </div>
      </section>

      <div className={styles.settingsDivider} />

      <section className={styles.settingsSection}>
        <div className={styles.settingsSectionHead}>
          <h3 className={styles.settingsSectionTitle}>
            {t("account.displayName")}
          </h3>
          <p className={styles.settingsSectionDesc}>
            {t("account.displayNameLocalHint", "只影响这台设备上的显示，不涉及账号。")}
          </p>
        </div>
        <Form
          form={profileForm}
          onFinish={handleSaveProfile}
          layout="vertical"
          requiredMark={false}
          initialValues={{ display_name: profile.display_name || "" }}
          className={styles.settingsForm}
        >
          <Form.Item
            name="display_name"
            style={{ marginBottom: 0 }}
            rules={[
              {
                max: LOCAL_PROFILE_NAME_MAX,
                message: t("account.displayNameTooLong"),
              },
            ]}
          >
            <Input
              placeholder={t("account.displayNamePlaceholder")}
              maxLength={LOCAL_PROFILE_NAME_MAX}
            />
          </Form.Item>
        </Form>
      </section>

      <div className={styles.settingsDivider} />

      <section className={styles.settingsSection}>
        <div className={styles.settingsSectionHead}>
          <h3 className={styles.settingsSectionTitle}>
            {t("account.layoutMode")}
          </h3>
          <p className={styles.settingsSectionDesc}>
            {t("account.layoutModeHint")}
          </p>
        </div>
        <Segmented
          block
          value={layoutMode}
          options={[
            { label: t("account.layoutClassic"), value: "classic" },
            { label: t("account.layoutMinimal"), value: "minimal" },
          ]}
          onChange={(val) => setLayoutMode(val as LayoutMode)}
        />
      </section>

      <div className={styles.settingsDivider} />

      <section className={styles.settingsSection}>
        <div className={styles.settingsSectionHead}>
          <h3 className={styles.settingsSectionTitle}>
            {t("account.language")}
          </h3>
          <p className={styles.settingsSectionDesc}>
            {t("account.languageHint")}
          </p>
        </div>
        <Segmented
          block
          value={currentLang}
          options={[
            { label: t("account.langZh"), value: "zh" },
            { label: t("account.langEn"), value: "en" },
          ]}
          onChange={(val) => handleLocaleChange(val as string)}
        />
      </section>

      <div className={styles.settingsDivider} />

      <section className={styles.settingsSection}>
        <div className={styles.settingsSectionHead}>
          <h3 className={styles.settingsSectionTitle}>
            {t("account.palette")}
          </h3>
          <p className={styles.settingsSectionDesc}>
            {t("account.paletteHint")}
          </p>
        </div>
        <PaletteSwitcher />
      </section>

      <div className={styles.settingsDivider} />

      <section className={styles.settingsSection}>
        <div className={styles.settingsSectionHead}>
          <h3 className={styles.settingsSectionTitle}>
            {t("account.localData", "本机数据")}
          </h3>
          <p className={styles.settingsSectionDesc}>
            {t(
              "account.localDataHint",
              "导出或导入会话、配置与进度；数据只在这台设备上流转。",
            )}
          </p>
        </div>
        <Button icon={<HardDrive size={16} strokeWidth={1.8} />} onClick={goBackup}>
          {t("account.openBackup", "打开备份与恢复")}
        </Button>
      </section>
    </div>
  );

  return (
    <>
      <Popover
        content={menuContent}
        trigger="click"
        open={menuOpen}
        onOpenChange={setMenuOpen}
        placement="topLeft"
        arrow={false}
        overlayClassName={styles.menuPopover}
        destroyOnHidden
        getPopupContainer={() => document.body}
      >
        {triggerButton}
      </Popover>

      <Drawer
        title={t("account.settings")}
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        placement="right"
        width={isMobile ? "100%" : 480}
        destroyOnHidden
        className={styles.settingsDrawer}
        footer={
          <div className={styles.settingsDrawerFooter}>
            <Button onClick={() => setSettingsOpen(false)}>
              {t("common.close", "关闭")}
            </Button>
            <Button type="primary" onClick={() => profileForm.submit()}>
              {t("common.save")}
            </Button>
          </div>
        }
      >
        {settingsBody}
      </Drawer>
    </>
  );
}
