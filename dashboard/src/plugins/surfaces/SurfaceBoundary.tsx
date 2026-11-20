import { Component, type ReactNode } from "react";

interface SurfaceBoundaryProps {
  pluginId: string;
  surfaceId: string;
  children: ReactNode;
}

interface SurfaceBoundaryState {
  error: Error | null;
}

/**
 * Keep one broken plugin from taking down the host page or another surface.
 * The fallback is intentionally visible: a plugin that cannot render should
 * not look like it silently works.
 */
export class SurfaceBoundary extends Component<
  SurfaceBoundaryProps,
  SurfaceBoundaryState
> {
  state: SurfaceBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): SurfaceBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error): void {
    console.warn(
      `[plugin-ui] surface ${this.props.pluginId}:${this.props.surfaceId} failed:`,
      error,
    );
  }

  render(): ReactNode {
    if (this.state.error) {
      return (
        <div
          role="alert"
          style={{
            border: "1px solid rgba(220, 38, 38, 0.45)",
            borderRadius: 12,
            padding: "10px 12px",
            fontSize: 12,
            lineHeight: 1.5,
            color: "inherit",
            background: "rgba(220, 38, 38, 0.06)",
          }}
        >
          插件界面渲染失败：{this.props.pluginId} / {this.props.surfaceId}
        </div>
      );
    }
    return this.props.children;
  }
}
