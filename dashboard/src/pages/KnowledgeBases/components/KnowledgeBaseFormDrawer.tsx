import type { Dispatch, SetStateAction } from "react";
import { App, Button, Drawer, Form, Input, InputNumber, Switch } from "antd";
import type { FormInstance } from "antd";
import { useTranslation } from "react-i18next";

import { knowledgeBasesApi } from "../../../api/modules/knowledgeBases";
import type { ResourceVisibilityMode } from "../../../api/modules/userGroups";
import {
  isUploadedAvatarUrl,
  KNOWLEDGE_AVATAR_PRESETS,
  ResourceAvatarPicker,
  avatarPickerStyles,
} from "../../../components/AvatarPicker";
import {
  ResourceVisibilityFields,
  ResourceVisibilityGate,
} from "../../../components/ResourceVisibilityFields";
import { TextAssistBar } from "../../../components/TextAssistBar";
import { apiErrorMessage } from "../../../utils/apiError";
import styles from "../index.module.less";

export type BaseFormValues = {
  name: string;
  description?: string;
  icon_name?: string;
  icon_url?: string;
  max_documents?: number;
};

export interface KnowledgeBaseFormDrawerProps {
  baseDrawerOpen: boolean;
  setBaseDrawerOpen: Dispatch<SetStateAction<boolean>>;
  editingBaseId: string | null;
  isMobile: boolean;
  baseForm: FormInstance<BaseFormValues>;
  iconName: string | undefined;
  iconUrl: string | undefined;
  pendingAvatarFile: File | null;
  setPendingAvatarFile: Dispatch<SetStateAction<File | null>>;
  avatarBusy: boolean;
  setAvatarBusy: Dispatch<SetStateAction<boolean>>;
  defaultOpenChecked: boolean;
  setDefaultOpenChecked: Dispatch<SetStateAction<boolean>>;
  baseVisibility: ResourceVisibilityMode;
  setBaseVisibility: Dispatch<SetStateAction<ResourceVisibilityMode>>;
  baseGroupIds: string[];
  setBaseGroupIds: Dispatch<SetStateAction<string[]>>;
  saveBase: () => Promise<void>;
}

export function KnowledgeBaseFormDrawer({
  baseDrawerOpen,
  setBaseDrawerOpen,
  editingBaseId,
  isMobile,
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
  saveBase,
}: KnowledgeBaseFormDrawerProps) {
  const { t } = useTranslation();
  const { message } = App.useApp();
  return (
      <Drawer
        title={t(
          editingBaseId ? "knowledgeBases.edit" : "knowledgeBases.create",
        )}
        placement="right"
        open={baseDrawerOpen}
        onClose={() => setBaseDrawerOpen(false)}
        width={isMobile ? "100%" : 480}
        destroyOnHidden
        className={styles.baseDrawer}
        footer={
          <div className={styles.drawerFooter}>
            <Button onClick={() => setBaseDrawerOpen(false)}>
              {t("common.cancel")}
            </Button>
            <Button type="primary" onClick={() => void saveBase()}>
              {t(editingBaseId ? "common.save" : "common.create")}
            </Button>
          </div>
        }
      >
        <Form
          form={baseForm}
          layout="vertical"
          className={styles.baseForm}
          requiredMark={false}
        >
          <Form.Item name="icon_name" hidden>
            <Input />
          </Form.Item>
          <Form.Item name="icon_url" hidden>
            <Input />
          </Form.Item>
          <Form.Item
            label={t("knowledgeBases.icon")}
            className={avatarPickerStyles.formItem}
          >
            <ResourceAvatarPicker
              imageUrl={
                iconUrl?.trim() &&
                (isUploadedAvatarUrl(iconUrl) ||
                  Boolean(pendingAvatarFile) ||
                  iconUrl.startsWith("blob:") ||
                  /^https?:\/\//i.test(iconUrl))
                  ? iconUrl
                  : null
              }
              presetId={iconName || null}
              presets={KNOWLEDGE_AVATAR_PRESETS}
              disabled={avatarBusy}
              onPick={(file) => {
                if (editingBaseId) {
                  void (async () => {
                    setAvatarBusy(true);
                    try {
                      const result = await knowledgeBasesApi.uploadAvatar(
                        editingBaseId,
                        file,
                      );
                      baseForm.setFieldsValue({ icon_url: result.icon_url });
                      setPendingAvatarFile(null);
                    } catch (err) {
                      message.error(
                        apiErrorMessage(
                          err,
                          t("experts.avatarUploadFailed"),
                          t,
                        ),
                      );
                      throw err;
                    } finally {
                      setAvatarBusy(false);
                    }
                  })();
                  return;
                }
                setPendingAvatarFile(file);
                baseForm.setFieldsValue({
                  icon_url: URL.createObjectURL(file),
                });
              }}
              onSelectPreset={(presetId) => {
                void (async () => {
                  setPendingAvatarFile(null);
                  const nextName = presetId ?? "book-open";
                  if (editingBaseId && isUploadedAvatarUrl(iconUrl)) {
                    setAvatarBusy(true);
                    try {
                      await knowledgeBasesApi.deleteAvatar(editingBaseId);
                    } catch {
                      // Preset still applied locally / on save.
                    } finally {
                      setAvatarBusy(false);
                    }
                  }
                  baseForm.setFieldsValue({
                    icon_name: nextName,
                    icon_url: "",
                  });
                })();
              }}
              onRemove={
                iconUrl || pendingAvatarFile
                  ? () => {
                      void (async () => {
                        setPendingAvatarFile(null);
                        if (editingBaseId && isUploadedAvatarUrl(iconUrl)) {
                          setAvatarBusy(true);
                          try {
                            await knowledgeBasesApi.deleteAvatar(editingBaseId);
                          } catch (err) {
                            message.error(
                              apiErrorMessage(
                                err,
                                t("experts.avatarRemoveFailed"),
                                t,
                              ),
                            );
                          } finally {
                            setAvatarBusy(false);
                          }
                        }
                        baseForm.setFieldsValue({ icon_url: "" });
                      })();
                    }
                  : undefined
              }
            />
          </Form.Item>
          <Form.Item
            name="name"
            label={t("knowledgeBases.name")}
            rules={[
              {
                required: true,
                whitespace: true,
                message: t("knowledgeBases.nameRequired"),
              },
            ]}
          >
            <Input autoFocus maxLength={200} />
          </Form.Item>
          <Form.Item
            name="description"
            label={t("knowledgeBases.description")}
            className={styles.textAssistField}
          >
            <Input.TextArea autoSize={{ minRows: 2, maxRows: 5 }} />
          </Form.Item>
          <TextAssistBar
            kind="knowledge_base.description"
            getName={() => String(baseForm.getFieldValue("name") ?? "")}
            getText={() => String(baseForm.getFieldValue("description") ?? "")}
            onApply={(text) =>
              baseForm.setFieldsValue({ description: text.slice(0, 2000) })
            }
          />
          <Form.Item
            name="max_documents"
            label={t("knowledgeBases.maxDocuments")}
            tooltip={t("knowledgeBases.maxDocumentsHint")}
          >
            <InputNumber
              min={0}
              max={10000}
              step={1}
              precision={0}
              style={{ width: "100%" }}
            />
          </Form.Item>
          <div className={styles.formOptions}>
            <div className={styles.formOptionRow}>
              <div className={styles.formOptionCopy}>
                <span className={styles.switchLabel}>
                  {t("knowledgeBases.defaultOpen")}
                </span>
                <span className={styles.formOptionHint}>
                  {t("knowledgeBases.defaultOpenHint")}
                </span>
              </div>
              <Switch
                size="small"
                checked={defaultOpenChecked}
                onChange={setDefaultOpenChecked}
              />
            </div>
            <ResourceVisibilityGate allowOwner visibility={baseVisibility}>
              <div className={styles.formOptionRowVisibility}>
                <div className={styles.formOptionCopy}>
                  <span className={styles.switchLabel}>
                    {t("resourceVisibility.label")}
                  </span>
                </div>
                <ResourceVisibilityFields
                  allowOwner
                  visibility={baseVisibility}
                  groupIds={baseGroupIds}
                  onChange={(next) => {
                    setBaseVisibility(next.visibility);
                    setBaseGroupIds(next.groupIds);
                  }}
                />
              </div>
            </ResourceVisibilityGate>
          </div>
        </Form>
      </Drawer>
  );
}
