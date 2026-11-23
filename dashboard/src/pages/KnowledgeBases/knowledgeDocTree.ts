import type { TreeDataNode } from "antd";

export type DocTreeNode = TreeDataNode & { path: string; isDir: boolean };
