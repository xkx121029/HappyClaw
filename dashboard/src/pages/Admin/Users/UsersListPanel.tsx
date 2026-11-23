/**
 * Admin → Users page (plan §14.7).
 *
 * List all users with role/disabled toggles, password reset, delete.
 * Card and table views (default table). The view switcher + refresh +
 * new-user buttons live in a content-area toolbar (mirrors the Experts
 * page layout). Each row/card shows agent count; click opens a drawer
 * with that user's agents.
 *
 * Endpoints (all require admin role; backend returns 403 otherwise):
 *   GET    /api/users
 *   POST   /api/users
 *   POST   /api/users/batch
 *   PATCH  /api/users/{id}
 *   POST   /api/users/{id}/reset-password
 *   DELETE /api/users/{id}
 */

import { useEffect, useMemo, useState, useCallback } from "react";
import {
  Button,
  Modal,
  Form,
  Input,
  Switch,
  Typography,
  Drawer,
} from "antd";
import { message } from "@/utils/antdMessage";

import {
  CircleHelp,
  IdCard,
  Lock,
  LockOpen,
  ShieldCheck,
  Mail,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import cx from "classnames";
import { request } from "../../../api/request";
import { authApi } from "../../../api/modules/auth";
import {
  userRolesApi,
  userRoleDrift,
  type UserRole,
} from "../../../api/modules/userRoles";
import { useCardTableView } from "../../../hooks/useCardTableView";
import { useSetCurrentUser } from "../../../hooks/useCurrentUser";
import { useIsMobile } from "../../../hooks/useIsMobile";
import { useServerTimezone } from "../../../hooks/useServerTimezone";
import { apiErrorMessage } from "../../../utils/apiError";
import type { OctopAgent } from "../../../context/AgentContext";
import EditAgentDrawer from "../../Experts/components/EditAgentDrawer";
import InviteDrawer from "./InviteDrawer";
import { fetchFilesystemDefaults } from "../../Experts/components/agentBackendForm";
import { HOST_FS_ROOT } from "../../Experts/components/rootDirTree";
import styles from "./index.module.less";
import {
  deleteUserAvatar,
  ProfileAvatarPicker,
  uploadUserAvatar,
} from "./ProfileAvatar";
import {
  DEFAULT_EXPERT_TEMPLATE_ID,
  FIELD_ICON_PROPS,
  permFullLabel,
  type BatchAction,
  type BatchMaxAgentsFormValues,
  type BatchResponse,
  type BatchTokenFormValues,
  type CreateValues,
  type EditValues,
  type ExpertTemplateOption,
  type PermissionCatalogItem,
  type ResetValues,
  type UserRow,
} from "./usersListTypes";
import { policyFieldsFromRole, policyPayload } from "./policyForm";
import { lockRemainingSeconds, useNowSeconds } from "./userTime";
import { MaxAgentsInput, TokenQuotaInput } from "./QuotaInputs";
import { UserRoleField } from "./UserRoleField";
import { ResourcePolicyFields } from "./ResourcePolicyFields";
import {
  CollapsiblePermissionsField,
} from "./PermissionFields";
import { UserCardGrid } from "./UserCardGrid";
import { UsersTable } from "./UsersTable";
import { UsersBatchBar, UsersToolbar } from "./UsersToolbar";
import { UserAgentsDrawer } from "./UserAgentsDrawer";
import { UserCreateDrawer } from "./UserCreateDrawer";

const { Text } = Typography;

export {
  DEFAULT_EXPERT_TEMPLATE_ID,
  FIELD_ICON_PROPS,
  permFullLabel,
  type BatchAction,
  type BatchMaxAgentsFormValues,
  type BatchResponse,
  type BatchTokenFormValues,
  type CreateValues,
  type EditValues,
  type ExpertTemplateOption,
  type PermissionCatalogItem,
  type PolicyFormValues,
  type ResetValues,
  type UserRow,
} from "./usersListTypes";
export {
  policyFieldsFromRole,
  policyPayload,
  rolePoliciesFromForm,
} from "./policyForm";
export {
  formatUserTs,
  lockRemainingSeconds,
  useNowSeconds,
} from "./userTime";
export { MaxAgentsInput, TokenQuotaInput } from "./QuotaInputs";
export { ExpertTemplatePicker } from "./ExpertTemplatePicker";
export { UserRoleField } from "./UserRoleField";
export { RoleLegend, RoleNameMark } from "./RoleDisplay";
export { ResourcePolicyFields } from "./ResourcePolicyFields";
export {
  CollapsiblePermissionsField,
  PermissionCheckboxPicker,
  PermissionSummary,
  type PermissionCheckboxPickerProps,
} from "./PermissionFields";
export { UserCardGrid, type UserCardGridProps } from "./UserCardGrid";
export { UsersTable } from "./UsersTable";
export { UsersBatchBar, UsersToolbar } from "./UsersToolbar";
export { UserAgentsDrawer } from "./UserAgentsDrawer";
export { UserCreateDrawer } from "./UserCreateDrawer";

export default function UsersListPanel() {
  const { t, i18n } = useTranslation();
  const setCurrentUser = useSetCurrentUser();
  const timeZone = useServerTimezone();
  const isMobile = useIsMobile();
  const [agents, setAgents] = useState<OctopAgent[]>([]);
  const [agentsLoading, setAgentsLoading] = useState(true);
  const [rows, setRows] = useState<UserRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [createOpen, setCreateOpen] = useState(false);
  const [expertTemplates, setExpertTemplates] = useState<
    ExpertTemplateOption[]
  >([]);
  const [pendingUserAvatar, setPendingUserAvatar] = useState<File | null>(null);
  const [pendingUserIcon, setPendingUserIcon] = useState<string | null>(null);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [form] = Form.useForm<CreateValues>();
  const [editTarget, setEditTarget] = useState<UserRow | null>(null);
  const [editSubmitting, setEditSubmitting] = useState(false);
  const [editForm] = Form.useForm<EditValues>();
  const [resetTarget, setResetTarget] = useState<UserRow | null>(null);
  const [resetSubmitting, setResetSubmitting] = useState(false);
  const [resetForm] = Form.useForm<ResetValues>();
  const [currentUserId, setCurrentUserId] = useState<number | null>(null);
  const [actorIsAdmin, setActorIsAdmin] = useState(true);
  const [agentDrawerUser, setAgentDrawerUser] = useState<UserRow | null>(null);
  const [editAgent, setEditAgent] = useState<OctopAgent | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [batchSubmitting, setBatchSubmitting] = useState(false);
  const [batchTokenOpen, setBatchTokenOpen] = useState(false);
  const [batchTokenForm] = Form.useForm<BatchTokenFormValues>();
  const [batchMaxAgentsOpen, setBatchMaxAgentsOpen] = useState(false);
  const [batchMaxAgentsForm] = Form.useForm<BatchMaxAgentsFormValues>();
  const { viewMode, setViewMode, showCardView } = useCardTableView("table");
  const [permCatalog, setPermCatalog] = useState<PermissionCatalogItem[]>([]);
  const [userRoles, setUserRoles] = useState<UserRole[]>([]);
  const [fsTreeRoots, setFsTreeRoots] = useState<string[]>([HOST_FS_ROOT]);
  const [workspaceRootAllowed, setWorkspaceRootAllowed] = useState(true);

  const permLabelByKey = useMemo(() => {
    const map = new Map<string, string>();
    for (const item of permCatalog) {
      map.set(item.key, permFullLabel(item));
    }
    return map;
  }, [permCatalog]);

  const baselinePermissions = useMemo(
    () =>
      permCatalog
        .filter((p) => p.category === "settings" || p.category === "nav")
        .map((p) => p.key),
    [permCatalog],
  );

  const syncSelfAvatar = useCallback(
    (
      userId: number,
      avatar: { avatar_url?: string | null; avatar_icon?: string | null },
    ) => {
      setCurrentUser((prev) => {
        if (!prev || prev.id !== userId) return prev;
        return {
          ...prev,
          avatar_url: avatar.avatar_url ?? null,
          avatar_icon:
            avatar.avatar_icon === undefined
              ? prev.avatar_icon
              : avatar.avatar_icon,
        };
      });
    },
    [setCurrentUser],
  );

  const isSelfAdmin = useCallback(
    (row: UserRow) => row.id === currentUserId && row.role === "admin",
    [currentUserId],
  );

  const hasLockedUser = useMemo(
    () => rows.some((row) => row.login_locked),
    [rows],
  );
  const nowSec = useNowSeconds(hasLockedUser);

  const agentsByUserId = useMemo(() => {
    const map = new Map<number, OctopAgent[]>();
    for (const agent of agents) {
      if (agent.user_id == null) continue;
      const list = map.get(agent.user_id) ?? [];
      list.push(agent);
      map.set(agent.user_id, list);
    }
    return map;
  }, [agents]);

  const drawerAgents = agentDrawerUser
    ? agentsByUserId.get(agentDrawerUser.id) ?? []
    : [];

  const filteredRows = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    if (!query) return rows;
    return rows.filter((row) => {
      const username = row.username.toLowerCase();
      const displayName = (row.display_name ?? "").trim().toLowerCase();
      const email = (row.email ?? "").trim().toLowerCase();
      const roleName = (row.role_name ?? "").trim().toLowerCase();
      return (
        username.includes(query) ||
        displayName.includes(query) ||
        email.includes(query) ||
        roleName.includes(query)
      );
    });
  }, [rows, searchQuery]);

  const selectedIdSet = useMemo(() => new Set(selectedIds), [selectedIds]);
  const selectedVisibleCount = useMemo(
    () => filteredRows.filter((row) => selectedIdSet.has(row.id)).length,
    [filteredRows, selectedIdSet],
  );

  const clearSelection = useCallback(() => setSelectedIds([]), []);

  const toggleSelectOne = useCallback((id: number, checked: boolean) => {
    setSelectedIds((prev) => {
      if (checked) {
        return prev.includes(id) ? prev : [...prev, id];
      }
      return prev.filter((item) => item !== id);
    });
  }, []);

  const setSelectAllVisible = useCallback(
    (checked: boolean) => {
      const visibleIds = filteredRows.map((row) => row.id);
      setSelectedIds((prev) => {
        if (checked) {
          const next = new Set(prev);
          for (const id of visibleIds) next.add(id);
          return Array.from(next);
        }
        const drop = new Set(visibleIds);
        return prev.filter((id) => !drop.has(id));
      });
    },
    [filteredRows],
  );

  const refreshUsers = useCallback(async () => {
    setLoading(true);
    try {
      const data = await request<UserRow[]>("/users");
      setRows(data);
    } catch (err) {
      message.error(apiErrorMessage(err, t("adminUsers.loadFailed"), t));
    } finally {
      setLoading(false);
    }
  }, [t]);

  const reportBatchResult = useCallback(
    (body: BatchResponse) => {
      if (body.failed === 0) {
        message.success(
          t("adminUsers.batchSuccess", {
            count: body.succeeded,
            action: t(`adminUsers.batchAction.${body.action}`),
          }),
        );
        return;
      }
      if (body.succeeded === 0) {
        message.error(
          t("adminUsers.batchAllFailed", {
            failed: body.failed,
            action: t(`adminUsers.batchAction.${body.action}`),
          }),
        );
        return;
      }
      message.warning(
        t("adminUsers.batchPartial", {
          succeeded: body.succeeded,
          failed: body.failed,
          action: t(`adminUsers.batchAction.${body.action}`),
        }),
      );
    },
    [t],
  );

  const runBatch = useCallback(
    async (
      action: BatchAction,
      options?: {
        token_quota?: number | null;
        max_agents?: number | null;
      },
    ) => {
      if (selectedIds.length === 0) return;
      setBatchSubmitting(true);
      try {
        const body = await request<BatchResponse>("/users/batch", {
          method: "POST",
          body: JSON.stringify({
            user_ids: selectedIds,
            action,
            ...(action === "set_token_quota"
              ? { token_quota: options?.token_quota ?? null }
              : {}),
            ...(action === "set_max_agents"
              ? { max_agents: options?.max_agents ?? null }
              : {}),
          }),
        });
        reportBatchResult(body);
        clearSelection();
        setBatchTokenOpen(false);
        batchTokenForm.resetFields();
        setBatchMaxAgentsOpen(false);
        batchMaxAgentsForm.resetFields();
        void refreshUsers();
      } catch (err) {
        message.error(apiErrorMessage(err, t("adminUsers.batchFailed"), t));
      } finally {
        setBatchSubmitting(false);
      }
    },
    [
      selectedIds,
      reportBatchResult,
      clearSelection,
      batchTokenForm,
      batchMaxAgentsForm,
      refreshUsers,
      t,
    ],
  );

  const confirmBatchAction = (
    action: Extract<BatchAction, "enable" | "disable" | "delete">,
  ) => {
    if (selectedIds.length === 0) return;
    const titles = {
      enable: "adminUsers.batchEnableConfirm",
      disable: "adminUsers.batchDisableConfirm",
      delete: "adminUsers.batchDeleteConfirm",
    } as const;
    const hints = {
      enable: "adminUsers.batchEnableHint",
      disable: "adminUsers.batchDisableHint",
      delete: "adminUsers.batchDeleteHint",
    } as const;
    const okLabels = {
      enable: t("adminUsers.batchEnable"),
      disable: t("adminUsers.batchDisable"),
      delete: t("common.delete"),
    } as const;
    Modal.confirm({
      title: t(titles[action], { count: selectedIds.length }),
      content: t(hints[action]),
      okType: action === "delete" ? "danger" : "primary",
      okText: okLabels[action],
      cancelText: t("common.cancel"),
      onOk: () => runBatch(action),
    });
  };

  const openBatchToken = () => {
    batchTokenForm.setFieldsValue({
      limit_token_quota: true,
      token_quota: 10_000_000,
    });
    setBatchTokenOpen(true);
  };

  const submitBatchToken = async (values: BatchTokenFormValues) => {
    await runBatch("set_token_quota", {
      token_quota: values.limit_token_quota ? values.token_quota ?? null : null,
    });
  };

  const openBatchMaxAgents = () => {
    batchMaxAgentsForm.setFieldsValue({
      limit_max_agents: true,
      max_agents: 5,
    });
    setBatchMaxAgentsOpen(true);
  };

  const submitBatchMaxAgents = async (values: BatchMaxAgentsFormValues) => {
    await runBatch("set_max_agents", {
      max_agents: values.limit_max_agents ? values.max_agents ?? null : null,
    });
  };
  useEffect(() => {
    if (!hasLockedUser) return;
    const anyExpired = rows.some(
      (row) => row.login_locked && lockRemainingSeconds(row, nowSec) === 0,
    );
    if (anyExpired) void refreshUsers();
  }, [hasLockedUser, nowSec, rows, refreshUsers]);

  const refreshAgents = useCallback(async () => {
    setAgentsLoading(true);
    try {
      const data = await request<OctopAgent[]>("/agents?scope=all");
      setAgents(data);
    } catch (err) {
      message.error(apiErrorMessage(err, t("adminUsers.loadFailed"), t));
      setAgents([]);
    } finally {
      setAgentsLoading(false);
    }
  }, [t]);

  const patchAgent = useCallback(
    (agentId: string, patch: Partial<OctopAgent>) => {
      setAgents((prev) =>
        prev.map((a) => (a.agent_id === agentId ? { ...a, ...patch } : a)),
      );
    },
    [],
  );

  const handleDrawerStateChange = useCallback(
    (agentId: string, newState: string) => {
      patchAgent(agentId, { state: newState });
    },
    [patchAgent],
  );

  const handleDrawerDeleted = useCallback(
    (agentId: string) => {
      setAgents((prev) => prev.filter((a) => a.agent_id !== agentId));
      void refreshAgents();
    },
    [refreshAgents],
  );

  const handleEditSaved = useCallback(
    (
      updated: Pick<
        OctopAgent,
        "agent_id" | "name" | "description" | "default_model"
      >,
    ) => {
      setEditAgent(null);
      patchAgent(updated.agent_id, {
        name: updated.name,
        description: updated.description,
        default_model: updated.default_model,
      });
      void refreshAgents();
    },
    [patchAgent, refreshAgents],
  );

  const refreshAll = useCallback(async () => {
    await Promise.all([refreshUsers(), refreshAgents()]);
  }, [refreshUsers, refreshAgents]);

  useEffect(() => {
    void refreshAll();
    authApi
      .me()
      .then((u) => {
        setCurrentUserId(u.id);
        setActorIsAdmin(u.role === "admin");
      })
      .catch(() => {
        setCurrentUserId(null);
        setActorIsAdmin(false);
      });
    request<PermissionCatalogItem[]>("/users/permissions")
      .then(setPermCatalog)
      .catch(() => setPermCatalog([]));
    userRolesApi
      .list()
      .then(setUserRoles)
      .catch(() => setUserRoles([]));
    fetchFilesystemDefaults()
      .then((defaults) => {
        setFsTreeRoots(
          defaults.browse_roots?.length
            ? defaults.browse_roots
            : [defaults.tree_root],
        );
        setWorkspaceRootAllowed(!defaults.in_container);
      })
      .catch(() => {
        setFsTreeRoots([HOST_FS_ROOT]);
        setWorkspaceRootAllowed(true);
      });
  }, [refreshAll]);

  useEffect(() => {
    if (!createOpen) return;
    let cancelled = false;
    const lang = i18n.language.startsWith("zh") ? "zh" : "en";
    void request<{
      items: Array<{
        slug: string;
        label: { zh: string; en: string };
        description?: { zh?: string; en?: string };
        icon_url?: string | null;
        icon_name?: string | null;
      }>;
    }>("/experts/hub")
      .then((body) => {
        if (cancelled) return;
        const rows = Array.isArray(body.items) ? body.items : [];
        setExpertTemplates(
          rows.map((row) => ({
            id: row.slug,
            label: row.label?.[lang] || row.label?.en || row.slug,
            description:
              row.description?.[lang] || row.description?.en || undefined,
            icon_url: row.icon_url,
            icon_name: row.icon_name,
          })),
        );
        const ids = new Set(rows.map((row) => row.slug));
        const current = form.getFieldValue("expert_template_id");
        if (typeof current !== "string" || !ids.has(current)) {
          const next = ids.has(DEFAULT_EXPERT_TEMPLATE_ID)
            ? DEFAULT_EXPERT_TEMPLATE_ID
            : rows[0]?.slug;
          form.setFieldValue("expert_template_id", next);
        }
      })
      .catch(() => {
        if (!cancelled) setExpertTemplates([]);
      });
    return () => {
      cancelled = true;
    };
  }, [createOpen, form, i18n.language]);

  const onCreate = async (values: CreateValues) => {
    setSubmitting(true);
    try {
      const created = await request<UserRow>("/users", {
        method: "POST",
        body: JSON.stringify({
          username: values.username,
          display_name: values.display_name?.trim() || null,
          email: values.email?.trim() || null,
          ...(values.directory
            ? { directory: true }
            : { password: values.password }),
          role: values.role,
          permissions: values.role === "admin" ? [] : values.permissions ?? [],
          role_name: values.role_name?.trim() || null,
          ...policyPayload(values, { workspaceRootAllowed }),
          create_default_expert: Boolean(values.create_default_expert),
          expert_template_id: values.create_default_expert
            ? values.expert_template_id || DEFAULT_EXPERT_TEMPLATE_ID
            : null,
        }),
      });
      if (pendingUserAvatar) {
        try {
          await uploadUserAvatar(created.id, pendingUserAvatar);
        } catch (err) {
          message.error(
            apiErrorMessage(err, t("experts.avatarUploadFailed"), t),
          );
        }
      } else if (pendingUserIcon) {
        try {
          await request(`/users/${created.id}`, {
            method: "PATCH",
            body: JSON.stringify({ avatar_icon: pendingUserIcon }),
          });
        } catch (err) {
          message.error(
            apiErrorMessage(err, t("experts.avatarUploadFailed"), t),
          );
        }
      }
      setPendingUserAvatar(null);
      setPendingUserIcon(null);
      message.success(
        t("adminUsers.createSuccess", { username: values.username }),
      );
      form.resetFields();
      setCreateOpen(false);
      void refreshUsers();
    } catch (err) {
      message.error(apiErrorMessage(err, t("adminUsers.createFailed"), t));
    } finally {
      setSubmitting(false);
    }
  };

  const openCreate = () => {
    const userRole = userRoles.find((role) => role.user_role_id === "user");
    form.setFieldsValue({
      role: userRole?.user_role_id ?? "user",
      permissions: userRole
        ? [...userRole.permissions]
        : [...baselinePermissions],
      role_name: userRole?.user_role_name,
      username: undefined,
      display_name: undefined,
      email: undefined,
      directory: false,
      password: undefined,
      confirm: undefined,
      limit_workspace_root: false,
      workspace_root_dir: undefined,
      limit_token_quota: false,
      token_quota: undefined,
      limit_max_agents: false,
      max_agents: undefined,
      create_default_expert: true,
      expert_template_id: DEFAULT_EXPERT_TEMPLATE_ID,
      ...(userRole ? policyFieldsFromRole(userRole, workspaceRootAllowed) : {}),
    });
    setPendingUserAvatar(null);
    setPendingUserIcon(null);
    setCreateOpen(true);
  };

  const openEdit = (row: UserRow) => {
    setEditTarget(row);
    const matched =
      userRoles.find((role) => role.user_role_id === row.role) ??
      (row.role_name
        ? userRoles.find((role) => role.user_role_name === row.role_name)
        : undefined);
    editForm.setFieldsValue({
      display_name: row.display_name ?? "",
      email: row.email ?? "",
      role: matched?.user_role_id ?? row.role,
      permissions: [...(row.permissions ?? [])],
      role_name: row.role_name ?? matched?.user_role_name ?? undefined,
      limit_workspace_root: workspaceRootAllowed
        ? Boolean(row.workspace_root_dir)
        : false,
      workspace_root_dir: workspaceRootAllowed
        ? row.workspace_root_dir ?? undefined
        : undefined,
      limit_token_quota: row.token_quota != null,
      token_quota: row.token_quota ?? undefined,
      limit_max_agents: row.max_agents != null,
      max_agents: row.max_agents ?? undefined,
    });
  };

  const togglePatch = async (
    row: UserRow,
    patch: Partial<Pick<UserRow, "role" | "disabled" | "permissions">>,
  ): Promise<boolean> => {
    if (
      patch.role === "user" &&
      row.id === currentUserId &&
      row.role === "admin"
    ) {
      message.warning(t("adminUsers.demoteSelf"));
      return false;
    }
    try {
      await request(`/users/${row.id}`, {
        method: "PATCH",
        body: JSON.stringify(patch),
      });
      void refreshUsers();
      return true;
    } catch (err) {
      message.error(apiErrorMessage(err, t("adminUsers.updateFailed"), t));
      return false;
    }
  };

  const onEditSubmit = async (values: EditValues) => {
    if (!editTarget) return;
    setEditSubmitting(true);
    try {
      await request(`/users/${editTarget.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          display_name: values.display_name?.trim() || null,
          email: values.email?.trim() || null,
          role: values.role,
          permissions: values.role === "admin" ? [] : values.permissions ?? [],
          role_name: values.role_name?.trim() || null,
          ...policyPayload(values, { workspaceRootAllowed }),
        }),
      });
      setEditTarget(null);
      editForm.resetFields();
      void refreshUsers();
    } catch (err) {
      message.error(apiErrorMessage(err, t("adminUsers.updateFailed"), t));
    } finally {
      setEditSubmitting(false);
    }
  };

  const onDelete = async (row: UserRow) => {
    try {
      await request(`/users/${row.id}`, { method: "DELETE" });
      message.success(t("adminUsers.deleteSuccess"));
      void refreshAll();
    } catch (err) {
      message.error(apiErrorMessage(err, t("common.deleteFailed"), t));
    }
  };

  const onResetSubmit = async (values: ResetValues) => {
    if (!resetTarget) return;
    setResetSubmitting(true);
    try {
      await request(`/users/${resetTarget.id}/reset-password`, {
        method: "POST",
        body: JSON.stringify({ new_password: values.password }),
      });
      message.success(t("adminUsers.resetSuccess"));
      setResetTarget(null);
      resetForm.resetFields();
    } catch (err) {
      message.error(apiErrorMessage(err, t("adminUsers.resetFailed"), t));
    } finally {
      setResetSubmitting(false);
    }
  };

  const onResetMfa = async (row: UserRow) => {
    try {
      await authApi.adminResetMfa(row.id);
      message.success(t("adminUsers.mfaResetSuccess"));
      void refreshUsers();
    } catch (err) {
      message.error(apiErrorMessage(err, t("adminUsers.mfaResetFailed"), t));
    }
  };

  const onUnlockLogin = async (row: UserRow) => {
    try {
      await request(`/users/${row.id}/unlock-login`, { method: "POST" });
      message.success(t("adminUsers.unlockLoginSuccess"));
      void refreshUsers();
    } catch (err) {
      message.error(apiErrorMessage(err, t("adminUsers.unlockLoginFailed"), t));
    }
  };

  return (
    <>
      <UsersToolbar
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        showCardView={showCardView}
        visibleCount={filteredRows.length}
        selectedVisibleCount={selectedVisibleCount}
        onSelectAllVisible={setSelectAllVisible}
        viewMode={viewMode}
        onViewModeChange={setViewMode}
        onRefresh={() => void refreshAll()}
        onInvite={() => setInviteOpen(true)}
        onCreate={openCreate}
      />

      {selectedIds.length > 0 ? (
        <UsersBatchBar
          count={selectedIds.length}
          submitting={batchSubmitting}
          onEnable={() => confirmBatchAction("enable")}
          onDisable={() => confirmBatchAction("disable")}
          onOpenToken={openBatchToken}
          onOpenMaxAgents={openBatchMaxAgents}
          onDelete={() => confirmBatchAction("delete")}
          onClear={clearSelection}
        />
      ) : null}

      {showCardView ? (
        <UserCardGrid
          rows={filteredRows}
          loading={loading}
          agentsByUserId={agentsByUserId}
          agentsLoading={agentsLoading}
          currentUserId={currentUserId}
          permLabelByKey={permLabelByKey}
          selectedIds={selectedIds}
          onToggleSelect={toggleSelectOne}
          onTogglePatch={togglePatch}
          onEdit={openEdit}
          onShowAgents={setAgentDrawerUser}
          onResetPassword={(row) => {
            setResetTarget(row);
            resetForm.resetFields();
          }}
          onResetMfa={onResetMfa}
          onDelete={onDelete}
          onUnlockLogin={onUnlockLogin}
          nowSec={nowSec}
          userRoles={userRoles}
        />
      ) : (
        <UsersTable
          rows={filteredRows}
          loading={loading}
          selectedIds={selectedIds}
          onSelectionChange={setSelectedIds}
          currentUserId={currentUserId}
          agentsByUserId={agentsByUserId}
          agentsLoading={agentsLoading}
          permLabelByKey={permLabelByKey}
          userRoles={userRoles}
          nowSec={nowSec}
          timeZone={timeZone}
          isMobile={isMobile}
          onShowAgents={setAgentDrawerUser}
          onTogglePatch={togglePatch}
          onEdit={openEdit}
          onResetPassword={(row) => {
            setResetTarget(row);
            resetForm.resetFields();
          }}
          onResetMfa={onResetMfa}
          onDelete={onDelete}
          onUnlockLogin={onUnlockLogin}
        />
      )}

      <UserAgentsDrawer
        user={agentDrawerUser}
        agents={drawerAgents}
        loading={agentsLoading}
        onClose={() => setAgentDrawerUser(null)}
        onEditAgent={setEditAgent}
        onDeleted={handleDrawerDeleted}
        onStateChange={handleDrawerStateChange}
        onRefreshAgents={() => void refreshAgents()}
      />

      <EditAgentDrawer
        open={editAgent !== null}
        agent={editAgent}
        onClose={() => setEditAgent(null)}
        onSaved={handleEditSaved}
      />

      <InviteDrawer open={inviteOpen} onClose={() => setInviteOpen(false)} />

      <UserCreateDrawer
        open={createOpen}
        onClose={() => {
          setCreateOpen(false);
          form.resetFields();
        }}
        form={form}
        submitting={submitting}
        onSubmit={onCreate}
        expertTemplates={expertTemplates}
        userRoles={userRoles}
        workspaceRootAllowed={workspaceRootAllowed}
        actorIsAdmin={actorIsAdmin}
        permCatalog={permCatalog}
        fsTreeRoots={fsTreeRoots}
        pendingUserIcon={pendingUserIcon}
        onPickAvatar={setPendingUserAvatar}
        onSelectIcon={(icon) => {
          setPendingUserIcon(icon);
          setPendingUserAvatar(null);
        }}
        onRemoveAvatar={() => setPendingUserAvatar(null)}
      />

      <Drawer
        title={
          editTarget
            ? t("adminUsers.modalEditTitle", {
                username: editTarget.username,
              })
            : t("common.edit")
        }
        placement="right"
        open={editTarget !== null}
        onClose={() => {
          setEditTarget(null);
          editForm.resetFields();
        }}
        width={Math.min(
          520,
          typeof window !== "undefined" ? window.innerWidth - 24 : 520,
        )}
        destroyOnHidden
        className={styles.createUserDrawer}
        styles={{ body: { paddingTop: 12, paddingBottom: 24 } }}
        footer={
          <div className={styles.createUserFooter}>
            <Button
              onClick={() => {
                setEditTarget(null);
                editForm.resetFields();
              }}
            >
              {t("common.cancel")}
            </Button>
            <Button
              type="primary"
              loading={editSubmitting}
              onClick={() => editForm.submit()}
            >
              {t("common.save")}
            </Button>
          </div>
        }
      >
        <Form<EditValues>
          form={editForm}
          layout="vertical"
          requiredMark={false}
          onFinish={onEditSubmit}
          className={styles.createUserForm}
        >
          <div className={styles.createSection}>
            <div className={styles.createSectionTitle}>
              {t("adminUsers.createSectionAccount")}
            </div>
            {editTarget ? (
              <ProfileAvatarPicker
                kind="user"
                avatarUrl={editTarget.avatar_url}
                icon={editTarget.avatar_icon}
                onSelectIcon={async (icon) => {
                  try {
                    const updated = await request<UserRow>(
                      `/users/${editTarget.id}`,
                      {
                        method: "PATCH",
                        body: JSON.stringify({ avatar_icon: icon }),
                      },
                    );
                    setEditTarget({
                      ...editTarget,
                      avatar_url: updated.avatar_url,
                      avatar_icon: updated.avatar_icon,
                    });
                    syncSelfAvatar(editTarget.id, updated);
                    void refreshUsers();
                  } catch (err) {
                    message.error(
                      apiErrorMessage(err, t("experts.avatarUploadFailed"), t),
                    );
                    throw err;
                  }
                }}
                onPick={async (file) => {
                  try {
                    const result = await uploadUserAvatar(editTarget.id, file);
                    setEditTarget({
                      ...editTarget,
                      avatar_url: result.avatar_url,
                    });
                    syncSelfAvatar(editTarget.id, {
                      avatar_url: result.avatar_url,
                    });
                    void refreshUsers();
                  } catch (err) {
                    message.error(
                      apiErrorMessage(err, t("experts.avatarUploadFailed"), t),
                    );
                    throw err;
                  }
                }}
                onRemove={async () => {
                  try {
                    await deleteUserAvatar(editTarget.id);
                    setEditTarget({ ...editTarget, avatar_url: null });
                    syncSelfAvatar(editTarget.id, { avatar_url: null });
                    void refreshUsers();
                  } catch (err) {
                    message.error(
                      apiErrorMessage(err, t("experts.avatarRemoveFailed"), t),
                    );
                    throw err;
                  }
                }}
              />
            ) : null}
            <Form.Item
              label={t("adminUsers.formDisplayName")}
              name="display_name"
            >
              <Input prefix={<IdCard {...FIELD_ICON_PROPS} />} />
            </Form.Item>
            <Form.Item
              label={t("adminUsers.formEmail")}
              name="email"
              rules={[
                {
                  type: "email",
                  message: t("adminUsers.formEmailInvalid"),
                },
              ]}
            >
              <Input
                prefix={<Mail {...FIELD_ICON_PROPS} />}
                type="email"
                autoComplete="email"
              />
            </Form.Item>
          </div>

          <div className={styles.createSection}>
            <div className={styles.createSectionTitle}>
              {t("adminUsers.createSectionAccess")}
            </div>
            <div className={cx(styles.permAdminHint, styles.permSectionHint)}>
              <CircleHelp size={15} strokeWidth={2} />
              <span>{t("adminUsers.permEditHint")}</span>
            </div>
            <UserRoleField
              roles={userRoles}
              workspaceRootAllowed={workspaceRootAllowed}
              confirmOverwrite
              actorIsAdmin={actorIsAdmin}
              disabled={Boolean(editTarget && isSelfAdmin(editTarget))}
              diverged={
                Boolean(editTarget) &&
                userRoleDrift(editTarget as UserRow, userRoles) === "changed"
              }
              snapshotName={editTarget?.role_name}
              staleName={
                editTarget?.role_name &&
                !userRoles.some(
                  (role) =>
                    role.user_role_id === editTarget.role ||
                    role.user_role_name === editTarget.role_name,
                )
                  ? editTarget.role_name
                  : null
              }
            />
            {editTarget && isSelfAdmin(editTarget) ? (
              <div className={styles.permAdminHint}>
                <span>{t("adminUsers.demoteSelf")}</span>
              </div>
            ) : null}
            <Form.Item
              noStyle
              shouldUpdate={(prev, cur) => prev.role !== cur.role}
            >
              {({ getFieldValue }) => {
                const isAdminRole = getFieldValue("role") === "admin";
                if (isAdminRole) {
                  return (
                    <div className={styles.permAdminHint}>
                      <ShieldCheck size={15} strokeWidth={2} />
                      <span>{t("adminUsers.permAllHint")}</span>
                    </div>
                  );
                }
                return <CollapsiblePermissionsField catalog={permCatalog} />;
              }}
            </Form.Item>
          </div>

          <ResourcePolicyFields
            fsTreeRoots={fsTreeRoots}
            workspaceRootAllowed={workspaceRootAllowed}
          />
        </Form>
      </Drawer>

      <Modal
        title={
          resetTarget
            ? t("adminUsers.modalResetTitle", {
                username: resetTarget.username,
              })
            : ""
        }
        open={resetTarget !== null}
        onCancel={() => {
          setResetTarget(null);
          resetForm.resetFields();
        }}
        onOk={() => resetForm.submit()}
        okText={t("common.reset")}
        cancelText={t("common.cancel")}
        confirmLoading={resetSubmitting}
      >
        <Text type="secondary" style={{ display: "block", marginBottom: 8 }}>
          {t("adminUsers.resetHint")}
        </Text>
        <Form<ResetValues>
          form={resetForm}
          layout="vertical"
          onFinish={onResetSubmit}
        >
          <Form.Item
            label={t("adminUsers.newPassword")}
            name="password"
            rules={[
              { required: true, message: t("adminUsers.newPasswordRequired") },
            ]}
          >
            <Input.Password
              autoComplete="new-password"
              prefix={
                <Lock size={14} style={{ color: "var(--fn-text-tertiary)" }} />
              }
            />
          </Form.Item>
          <Form.Item
            label={t("adminUsers.formPasswordConfirm")}
            name="confirm"
            dependencies={["password"]}
            rules={[
              { required: true, message: t("adminUsers.formPasswordConfirm") },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || getFieldValue("password") === value) {
                    return Promise.resolve();
                  }
                  return Promise.reject(
                    new Error(t("wizard.admin.passwordMismatch")),
                  );
                },
              }),
            ]}
          >
            <Input.Password
              autoComplete="new-password"
              prefix={
                <LockOpen
                  size={14}
                  style={{ color: "var(--fn-text-tertiary)" }}
                />
              }
            />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={t("adminUsers.batchSetTokenTitle", {
          count: selectedIds.length,
        })}
        open={batchTokenOpen}
        onCancel={() => {
          setBatchTokenOpen(false);
          batchTokenForm.resetFields();
        }}
        onOk={() => batchTokenForm.submit()}
        okText={t("common.confirm")}
        cancelText={t("common.cancel")}
        confirmLoading={batchSubmitting}
        destroyOnHidden
      >
        <Text type="secondary" style={{ display: "block", marginBottom: 12 }}>
          {t("adminUsers.batchSetTokenHint")}
        </Text>
        <Form<BatchTokenFormValues>
          form={batchTokenForm}
          layout="vertical"
          onFinish={(values) => void submitBatchToken(values)}
        >
          <Form.Item
            label={t("adminUsers.policyTokenQuota")}
            extra={t("adminUsers.policyTokenQuotaHint")}
          >
            <Form.Item name="limit_token_quota" valuePropName="checked" noStyle>
              <Switch />
            </Form.Item>
          </Form.Item>
          <Form.Item
            noStyle
            shouldUpdate={(prev, cur) =>
              prev.limit_token_quota !== cur.limit_token_quota
            }
          >
            {({ getFieldValue }) =>
              getFieldValue("limit_token_quota") ? (
                <Form.Item
                  name="token_quota"
                  rules={[
                    {
                      required: true,
                      message: t("adminUsers.policyTokenQuotaRequired"),
                    },
                  ]}
                >
                  <TokenQuotaInput />
                </Form.Item>
              ) : null
            }
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={t("adminUsers.batchSetMaxAgentsTitle", {
          count: selectedIds.length,
        })}
        open={batchMaxAgentsOpen}
        onCancel={() => {
          setBatchMaxAgentsOpen(false);
          batchMaxAgentsForm.resetFields();
        }}
        onOk={() => batchMaxAgentsForm.submit()}
        okText={t("common.confirm")}
        cancelText={t("common.cancel")}
        confirmLoading={batchSubmitting}
        destroyOnHidden
      >
        <Text type="secondary" style={{ display: "block", marginBottom: 12 }}>
          {t("adminUsers.batchSetMaxAgentsHint")}
        </Text>
        <Form<BatchMaxAgentsFormValues>
          form={batchMaxAgentsForm}
          layout="vertical"
          onFinish={(values) => void submitBatchMaxAgents(values)}
        >
          <Form.Item
            label={t("adminUsers.policyMaxAgents")}
            extra={t("adminUsers.policyMaxAgentsHint")}
          >
            <Form.Item name="limit_max_agents" valuePropName="checked" noStyle>
              <Switch />
            </Form.Item>
          </Form.Item>
          <Form.Item
            noStyle
            shouldUpdate={(prev, cur) =>
              prev.limit_max_agents !== cur.limit_max_agents
            }
          >
            {({ getFieldValue }) =>
              getFieldValue("limit_max_agents") ? (
                <Form.Item
                  name="max_agents"
                  rules={[
                    {
                      required: true,
                      message: t("adminUsers.policyMaxAgentsRequired"),
                    },
                  ]}
                >
                  <MaxAgentsInput />
                </Form.Item>
              ) : null
            }
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}