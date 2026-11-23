/**
 * Create, edit, delete, password-reset, MFA-reset and unlock mutations for the
 * admin-users screen, together with the forms and drawer state they drive.
 */

import { Form } from "antd";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { authApi } from "../../../api/modules/auth";
import type { UserRole } from "../../../api/modules/userRoles";
import { request } from "../../../api/request";
import { apiErrorMessage } from "../../../utils/apiError";
import { useSetCurrentUser } from "../../../hooks/useCurrentUser";
import { message } from "@/utils/antdMessage";
import { policyFieldsFromRole, policyPayload } from "./policyForm";
import { deleteUserAvatar, uploadUserAvatar } from "./ProfileAvatar";
import {
  DEFAULT_EXPERT_TEMPLATE_ID,
  type CreateValues,
  type EditValues,
  type ExpertTemplateOption,
  type ResetValues,
  type UserRow,
} from "./usersListTypes";

export function useUserMutations({
  refreshUsers,
  refreshAll,
  workspaceRootAllowed,
  userRoles,
  baselinePermissions,
  currentUserId,
  setCurrentUser,
}: {
  refreshUsers: () => Promise<void>;
  refreshAll: () => Promise<void>;
  workspaceRootAllowed: boolean;
  userRoles: UserRole[];
  baselinePermissions: string[];
  currentUserId: number | null;
  setCurrentUser: ReturnType<typeof useSetCurrentUser>;
}) {
  const { t, i18n } = useTranslation();
  const [createOpen, setCreateOpen] = useState(false);
  const [expertTemplates, setExpertTemplates] = useState<
    ExpertTemplateOption[]
  >([]);
  const [pendingUserAvatar, setPendingUserAvatar] = useState<File | null>(null);
  const [pendingUserIcon, setPendingUserIcon] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [form] = Form.useForm<CreateValues>();
  const [editTarget, setEditTarget] = useState<UserRow | null>(null);
  const [editSubmitting, setEditSubmitting] = useState(false);
  const [editForm] = Form.useForm<EditValues>();
  const [resetTarget, setResetTarget] = useState<UserRow | null>(null);
  const [resetSubmitting, setResetSubmitting] = useState(false);
  const [resetForm] = Form.useForm<ResetValues>();

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

  const onEditAvatarIcon = async (target: UserRow, icon: string | null) => {
    try {
      const updated = await request<UserRow>(`/users/${target.id}`, {
        method: "PATCH",
        body: JSON.stringify({ avatar_icon: icon }),
      });
      setEditTarget({
        ...target,
        avatar_url: updated.avatar_url,
        avatar_icon: updated.avatar_icon,
      });
      syncSelfAvatar(target.id, updated);
      void refreshUsers();
    } catch (err) {
      message.error(apiErrorMessage(err, t("experts.avatarUploadFailed"), t));
      throw err;
    }
  };

  const onEditAvatarPick = async (target: UserRow, file: File) => {
    try {
      const result = await uploadUserAvatar(target.id, file);
      setEditTarget({ ...target, avatar_url: result.avatar_url });
      syncSelfAvatar(target.id, { avatar_url: result.avatar_url });
      void refreshUsers();
    } catch (err) {
      message.error(apiErrorMessage(err, t("experts.avatarUploadFailed"), t));
      throw err;
    }
  };

  const onEditAvatarRemove = async (target: UserRow) => {
    try {
      await deleteUserAvatar(target.id);
      setEditTarget({ ...target, avatar_url: null });
      syncSelfAvatar(target.id, { avatar_url: null });
      void refreshUsers();
    } catch (err) {
      message.error(apiErrorMessage(err, t("experts.avatarRemoveFailed"), t));
      throw err;
    }
  };

  return {
    createOpen,
    setCreateOpen,
    expertTemplates,
    pendingUserAvatar,
    setPendingUserAvatar,
    pendingUserIcon,
    setPendingUserIcon,
    submitting,
    form,
    editTarget,
    setEditTarget,
    editSubmitting,
    editForm,
    resetTarget,
    setResetTarget,
    resetSubmitting,
    resetForm,
    isSelfAdmin,
    onCreate,
    openCreate,
    openEdit,
    togglePatch,
    onEditSubmit,
    onDelete,
    onResetSubmit,
    onResetMfa,
    onUnlockLogin,
    onEditAvatarIcon,
    onEditAvatarPick,
    onEditAvatarRemove,
  };
}
