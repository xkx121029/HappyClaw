import { useEffect, useState } from "react";
import { Button, Modal, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { request } from "@/api/request";
import RootDirSelect from "../../Experts/components/RootDirSelect";

interface WorkspaceFolderPickerProps {
  open: boolean;
  submitting?: boolean;
  /** "project": the folder becomes this conversation's project root. */
  mode?: "agent" | "project";
  onCancel: () => void;
  onConfirm: (path: string) => void;
}

/** A drive root is never a sane agent home; require a concrete folder. */
export function isWorkspaceRootPath(path: string): boolean {
  const trimmed = path.trim().replace(/\\/g, "/");
  return trimmed === "/" || /^[a-zA-Z]:\/?$/.test(trimmed);
}

export default function WorkspaceFolderPicker({
  open,
  submitting = false,
  mode = "agent",
  onCancel,
  onConfirm,
}: WorkspaceFolderPickerProps) {
  const isProject = mode === "project";
  const { t } = useTranslation();
  const [roots, setRoots] = useState<string[]>([]);
  const [value, setValue] = useState("");
  const [loadingRoots, setLoadingRoots] = useState(false);

  useEffect(() => {
    if (!open || roots.length > 0) return;
    let cancelled = false;
    setLoadingRoots(true);
    void request<{ roots?: string[] }>("/filesystem/roots")
      .then((res) => {
        if (!cancelled) setRoots(res.roots ?? []);
      })
      .catch(() => undefined)
      .finally(() => {
        if (!cancelled) setLoadingRoots(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, roots.length]);

  useEffect(() => {
    if (!open) setValue("");
  }, [open]);

  const blocked = !value.trim() || isWorkspaceRootPath(value);

  return (
    <Modal
      open={open}
      title={
        isProject
          ? t("chat.projectPickTitle", { defaultValue: "选择项目文件夹" })
          : t("chat.workspacePickTitle", { defaultValue: "选择工作区" })
      }
      onCancel={onCancel}
      destroyOnHidden
      footer={[
        <Button key="cancel" onClick={onCancel}>
          {t("common.cancel", { defaultValue: "取消" })}
        </Button>,
        <Button
          key="confirm"
          type="primary"
          disabled={blocked}
          loading={submitting}
          onClick={() => onConfirm(value.trim())}
        >
          {isProject
            ? t("chat.projectPickConfirm", { defaultValue: "用此文件夹建立项目" })
            : t("chat.workspacePickConfirm", {
                defaultValue: "使用此文件夹",
              })}
        </Button>,
      ]}
    >
      {loadingRoots ? (
        <div style={{ padding: "24px 0", textAlign: "center" }}>
          <Spin size="small" />
        </div>
      ) : (
        <RootDirSelect value={value} onChange={setValue} treeRoots={roots} />
      )}
      <p
        style={{
          margin: "12px 0 0",
          fontSize: 12,
          color: "var(--fn-text-tertiary)",
        }}
      >
        {isProject
          ? t("chat.projectPickHint", {
              defaultValue:
                "该目录会成为本对话所属项目的根目录，已有的对话历史和文件都保留在原处。",
            })
          : t("chat.workspacePickHint", {
              defaultValue:
                "该目录会成为新专家的工作区：文件、终端和工具都在这里执行。目录内会创建 .octop 与专家说明文件。",
            })}
      </p>
      {value.trim() && isWorkspaceRootPath(value) ? (
        <p style={{ margin: "6px 0 0", fontSize: 12, color: "#d48806" }}>
          {t("chat.workspaceRootBlocked", {
            defaultValue:
              "不能直接用盘符根目录作为工作区，请选择具体文件夹。",
          })}
        </p>
      ) : null}
    </Modal>
  );
}
