import { Folder } from "lucide-react";

import { fileTreeIconSpec } from "../../../utils/fileTreeIcon";
import styles from "../index.module.less";

export const FOLDER_ICON_COLOR = "#d97706";

export function DocumentFormatIcon({
  filename,
  size = 14,
  className,
  isDir = false,
}: {
  filename: string;
  size?: number;
  className?: string;
  isDir?: boolean;
}) {
  const { Icon, color } = isDir
    ? { Icon: Folder, color: FOLDER_ICON_COLOR }
    : fileTreeIconSpec(filename);
  return (
    <span
      className={className ?? styles.docFormatIcon}
      style={{ color, background: `${color}14` }}
      aria-hidden
    >
      <Icon size={size} strokeWidth={2} />
    </span>
  );
}
