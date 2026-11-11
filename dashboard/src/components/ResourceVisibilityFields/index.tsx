import type { ReactNode } from "react";
import { Form } from "antd";
import { useTranslation } from "react-i18next";
import cx from "classnames";
import type { ResourceVisibilityMode } from "../../api/modules/userGroups";
import styles from "./ResourceVisibilityFields.module.less";

export type { ResourceVisibilityMode };

export type ResourceVisibilityValue = {
  visibility: ResourceVisibilityMode;
  groupIds: string[];
};

type FieldsProps = {
  /** Kept for call-site compatibility; single-user mode has no other owners. */
  allowOwner: boolean;
  visibility: ResourceVisibilityMode;
  groupIds: string[];
  onChange: (next: ResourceVisibilityValue) => void;
  disabled?: boolean;
  className?: string;
};

/**
 * 单人本机模式下已经没有「其他用户 / 分组 / 管理员」，
 * 可见性选择器只保留一句说明，避免让人误以为还需要配共享范围。
 */
export function ResourceVisibilityFields({ className }: FieldsProps) {
  const { t } = useTranslation();
  return (
    <p className={cx(styles.localOnly, className)}>
      {t(
        "resourceVisibility.localOnlyHint",
        "本机只有你一个使用者，资源始终在本机可见。",
      )}
    </p>
  );
}

type FormItemProps = {
  allowOwner: boolean;
  visibility: ResourceVisibilityMode;
  groupIds: string[];
  onChange: (next: ResourceVisibilityValue) => void;
  disabled?: boolean;
  /** Override default ``resourceVisibility.label``. */
  label?: string;
  /** Hint under the control (e.g. skill package / connector copy). */
  extra?: string;
  className?: string;
};

/** Drawer-friendly Form.Item wrapping ``ResourceVisibilityFields``. */
export function ResourceVisibilityFormItem({
  allowOwner,
  visibility,
  groupIds,
  onChange,
  disabled,
  label,
  extra,
  className,
}: FormItemProps) {
  const { t } = useTranslation();
  return (
    <Form.Item
      label={label ?? t("resourceVisibility.label")}
      extra={extra}
      className={cx(styles.formItem, className)}
      required={false}
    >
      <ResourceVisibilityFields
        allowOwner={allowOwner}
        visibility={visibility}
        groupIds={groupIds}
        onChange={onChange}
        disabled={disabled}
      />
    </Form.Item>
  );
}

type CollapseProps = {
  allowOwner?: boolean;
  visibility: ResourceVisibilityMode;
  groupIds: string[];
  onChange: (next: ResourceVisibilityValue) => void;
  disabled?: boolean;
  title?: string;
  hideTitle?: string;
  hint?: string;
  defaultOpen?: boolean;
  className?: string;
};

/** 分组授权已随单人模式下线，整块折叠面板不再渲染。 */
export function ResourceVisibilityCollapse(_props: CollapseProps) {
  return null;
}

/** 保留外层容器语义：内部字段自己已简化，不再整块隐藏。 */
export function ResourceVisibilityGate({
  children,
}: {
  allowOwner: boolean;
  visibility: ResourceVisibilityMode;
  children: ReactNode;
}) {
  return <>{children}</>;
}

export default ResourceVisibilityFields;
