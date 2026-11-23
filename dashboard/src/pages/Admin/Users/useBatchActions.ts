/**
 * Batch selection and batch actions for the admin-users screen: the selected
 * row ids, the batch request, its confirmation dialogs, and the two quota
 * modals' form state.
 */

import { Form, Modal } from "antd";
import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";

import { request } from "../../../api/request";
import { apiErrorMessage } from "../../../utils/apiError";
import { message } from "@/utils/antdMessage";
import type {
  BatchAction,
  BatchMaxAgentsFormValues,
  BatchResponse,
  BatchTokenFormValues,
  UserRow,
} from "./usersListTypes";

export function useBatchActions({
  rows,
  refreshUsers,
}: {
  rows: UserRow[];
  refreshUsers: () => Promise<void>;
}) {
  const { t } = useTranslation();
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [batchSubmitting, setBatchSubmitting] = useState(false);
  const [batchTokenOpen, setBatchTokenOpen] = useState(false);
  const [batchTokenForm] = Form.useForm<BatchTokenFormValues>();
  const [batchMaxAgentsOpen, setBatchMaxAgentsOpen] = useState(false);
  const [batchMaxAgentsForm] = Form.useForm<BatchMaxAgentsFormValues>();

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
      const visibleIds = rows.map((row) => row.id);
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
    [rows],
  );

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

  return {
    selectedIds,
    setSelectedIds,
    batchSubmitting,
    batchTokenOpen,
    setBatchTokenOpen,
    batchTokenForm,
    batchMaxAgentsOpen,
    setBatchMaxAgentsOpen,
    batchMaxAgentsForm,
    clearSelection,
    toggleSelectOne,
    setSelectAllVisible,
    confirmBatchAction,
    openBatchToken,
    submitBatchToken,
    openBatchMaxAgents,
    submitBatchMaxAgents,
  };
}
