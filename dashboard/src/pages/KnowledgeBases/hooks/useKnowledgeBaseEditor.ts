import type { App } from "antd";
import { Form } from "antd";
import type { TFunction } from "i18next";
import { useState } from "react";

import type { OctopUser } from "../../../api/modules/auth";
import {
  DEFAULT_KNOWLEDGE_LIMITS,
  knowledgeBasesApi,
  type KnowledgeBase,
  type KnowledgeCapability,
} from "../../../api/modules/knowledgeBases";
import type { ResourceVisibilityMode } from "../../../api/modules/userGroups";
import { apiErrorMessage } from "../../../utils/apiError";
import type { BaseFormValues } from "../components/KnowledgeBaseFormDrawer";

type AppApi = ReturnType<typeof App.useApp>;

export interface UseKnowledgeBaseEditorArgs {
  t: TFunction;
  message: AppApi["message"];
  bases: KnowledgeBase[];
  user: OctopUser | null;
  capability: KnowledgeCapability | null;
  loadBases: () => Promise<void>;
  loadDetail: (id: string, options?: { silent?: boolean }) => Promise<void>;
  isMobile: boolean;
  setMobilePane: (pane: "list" | "detail") => void;
}

/** Create/edit drawer state and save flow for one knowledge base. */
export function useKnowledgeBaseEditor({
  t,
  message,
  bases,
  user,
  capability,
  loadBases,
  loadDetail,
  isMobile,
  setMobilePane,
}: UseKnowledgeBaseEditorArgs) {
  const limits = capability?.limits ?? DEFAULT_KNOWLEDGE_LIMITS;
  const ownedBaseCount = user
    ? bases.filter((base) => base.owner_user_id === user.id).length
    : 0;
  const atBaseLimit = ownedBaseCount >= limits.max_bases_per_owner;
  const [baseDrawerOpen, setBaseDrawerOpen] = useState(false);
  const [editingBaseId, setEditingBaseId] = useState<string | null>(null);

  const [baseForm] = Form.useForm<BaseFormValues>();
  const iconName = Form.useWatch("icon_name", baseForm);
  const iconUrl = Form.useWatch("icon_url", baseForm);
  const [pendingAvatarFile, setPendingAvatarFile] = useState<File | null>(null);
  const [avatarBusy, setAvatarBusy] = useState(false);
  const [defaultOpenChecked, setDefaultOpenChecked] = useState(false);
  const [baseVisibility, setBaseVisibility] =
    useState<ResourceVisibilityMode>("owner");
  const [baseGroupIds, setBaseGroupIds] = useState<string[]>([]);

  const openCreate = () => {
    if (atBaseLimit) {
      message.warning(
        t("knowledgeBases.baseLimitReached", {
          count: limits.max_bases_per_owner,
        }),
      );
      return;
    }
    setPendingAvatarFile(null);
    baseForm.setFieldsValue({
      name: "",
      description: "",
      icon_name: "book-open",
      icon_url: "",
      max_documents: 100,
    });
    setDefaultOpenChecked(false);
    setBaseVisibility("owner");
    setBaseGroupIds([]);
    setEditingBaseId(null);
    setBaseDrawerOpen(true);
  };

  const openEdit = (base: KnowledgeBase) => {
    setPendingAvatarFile(null);
    baseForm.setFieldsValue({
      name: base.name,
      description: base.description,
      icon_name: base.icon_name || undefined,
      icon_url: base.icon_url || "",
      max_documents: base.max_documents,
    });
    setDefaultOpenChecked(base.default_open);
    setBaseVisibility(base.visibility ?? (base.shared ? "all" : "owner"));
    setBaseGroupIds(base.group_ids ?? []);
    setEditingBaseId(base.id);
    setBaseDrawerOpen(true);
  };

  const saveBase = async () => {
    const values = await baseForm.validateFields();
    if (baseVisibility === "groups" && baseGroupIds.length === 0) {
      message.error(t("resourceVisibility.needGroup"));
      return;
    }
    const payload = {
      ...values,
      // Blob previews are local-only; upload runs after create/update.
      icon_url: pendingAvatarFile
        ? ""
        : values.icon_url?.startsWith("blob:")
        ? ""
        : values.icon_url?.trim() || "",
      default_open: defaultOpenChecked,
      shared: baseVisibility !== "owner",
      visibility: baseVisibility,
      group_ids: baseGroupIds,
    };
    try {
      let next = editingBaseId
        ? await knowledgeBasesApi.update(editingBaseId, payload)
        : await knowledgeBasesApi.create(payload);
      if (pendingAvatarFile) {
        try {
          const uploaded = await knowledgeBasesApi.uploadAvatar(
            next.id,
            pendingAvatarFile,
          );
          next = { ...next, icon_url: uploaded.icon_url };
        } catch {
          message.warning(t("knowledgeBases.avatarUploadLater"));
        }
      }
      setBaseDrawerOpen(false);
      setPendingAvatarFile(null);
      await loadBases();
      await loadDetail(next.id);
      if (isMobile) setMobilePane("detail");
      message.success(
        t(editingBaseId ? "knowledgeBases.updated" : "knowledgeBases.created"),
      );
    } catch (error) {
      message.error(apiErrorMessage(error, t("knowledgeBases.saveFailed"), t));
    }
  };
  return {
    baseDrawerOpen,
    setBaseDrawerOpen,
    editingBaseId,
    baseForm,
    iconName,
    iconUrl,
    pendingAvatarFile,
    setPendingAvatarFile,
    avatarBusy,
    setAvatarBusy,
    defaultOpenChecked,
    setDefaultOpenChecked,
    baseVisibility,
    setBaseVisibility,
    baseGroupIds,
    setBaseGroupIds,
    openCreate,
    openEdit,
    saveBase,
  };
}
