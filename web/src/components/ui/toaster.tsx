import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { useToastStore } from "@/lib/toast";

export function Toaster() {
  const toasts = useToastStore((state) => state.toasts);
  const dismiss = useToastStore((state) => state.dismiss);

  return (
    <div
      aria-live="polite"
      aria-atomic="false"
      className="pointer-events-none fixed bottom-4 right-4 z-(--hc-z-toast) flex w-80 flex-col gap-2"
    >
      {toasts.map((item) => (
        <div
          key={item.id}
          role="status"
          className={cn(
            "pointer-events-auto flex items-start gap-3 rounded-md border border-line bg-raised p-3 shadow-overlay",
            "animate-[hc-pop-in_var(--hc-duration-base)_var(--hc-ease-out)]",
            item.tone === "danger" && "border-danger/40",
            item.tone === "success" && "border-success/40",
          )}
        >
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-fg">{item.title}</p>
            {item.description ? (
              <p className="mt-0.5 text-xs text-fg-subtle">{item.description}</p>
            ) : null}
          </div>
          {item.action ? (
            <Button
              variant="link"
              size="xs"
              onClick={item.action.onClick}
              className="shrink-0 text-xs"
            >
              {item.action.label}
            </Button>
          ) : null}
          <Button
            variant="ghost"
            size="xs"
            aria-label="Dismiss"
            onClick={() => dismiss(item.id)}
            className="shrink-0 px-1 text-fg-subtle"
          >
            ✕
          </Button>
        </div>
      ))}
    </div>
  );
}
