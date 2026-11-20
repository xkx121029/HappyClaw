import { useSyncExternalStore } from "react";
import {
  getSurfaceVersion,
  listPluginSurfaces,
  subscribeSurfaces,
} from "./registry";
import { SurfaceBoundary } from "./SurfaceBoundary";
import type { SurfaceContext, SurfaceSlot } from "./types";

/**
 * Renders every plugin surface registered for one slot.
 *
 * Nothing is rendered when no plugin targets the slot, so the host layout is
 * unchanged for users who have not installed a visual plugin. ``context`` is
 * forwarded to each component; ``conversation.view`` uses it for the message
 * that is being decorated.
 */
export function PluginSurfaceSlot({
  slot,
  context,
}: {
  slot: SurfaceSlot;
  context?: SurfaceContext;
}) {
  useSyncExternalStore(subscribeSurfaces, getSurfaceVersion, getSurfaceVersion);
  const surfaces = listPluginSurfaces(slot);
  if (surfaces.length === 0) return null;
  return (
    <>
      {surfaces.map((surface) => {
        const Component = surface.component;
        return (
          <SurfaceBoundary
            key={`${surface.pluginId}:${surface.id}`}
            pluginId={surface.pluginId}
            surfaceId={surface.id}
          >
            <div
              data-plugin-surface={`${surface.pluginId}:${surface.id}`}
              data-plugin-surface-slot={slot}
              style={{ display: "contents" }}
            >
              <Component
                host={surface.host}
                pluginId={surface.pluginId}
                surfaceId={surface.id}
                title={surface.title}
                context={context}
              />
            </div>
          </SurfaceBoundary>
        );
      })}
    </>
  );
}
