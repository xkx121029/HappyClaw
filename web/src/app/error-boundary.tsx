import { AlertTriangle, RotateCw } from "lucide-react";
import { Component, type ErrorInfo, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import i18n from "@/lib/i18n";

interface State {
  error: Error | null;
}

/**
 * Last line of defence: a render error anywhere below this boundary shows a
 * recoverable panel instead of a blank page, and the failing component tree is
 * logged once with its component stack for the console.
 */
export class ErrorBoundary extends Component<
  { children: ReactNode },
  State
> {
  override state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("[happyclaw] render error", error, info.componentStack);
  }

  private reset = () => {
    this.setState({ error: null });
    window.location.reload();
  };

  override render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <div className="flex h-full items-center justify-center bg-canvas p-6">
        <EmptyState
          size="lg"
          icon={<AlertTriangle />}
          title={i18n.t("state.errorTitle")}
          description={
            <span className="grid gap-1">
              <span>{i18n.t("state.errorDescription")}</span>
              <code className="mt-1 block max-w-full overflow-x-auto rounded-sm bg-sunken px-2 py-1 text-left font-mono text-2xs text-fg-subtle">
                {error.message}
              </code>
            </span>
          }
          action={
            <Button
              variant="secondary"
              size="sm"
              leadingIcon={<RotateCw />}
              onClick={this.reset}
            >
              {i18n.t("actions.retry")}
            </Button>
          }
        />
      </div>
    );
  }
}
