import { createFileRoute, notFound } from "@tanstack/react-router";

import { DirectionPage } from "@/directions";
import { isDirectionId, isDirectionPageId } from "@/directions/scope";

export const Route = createFileRoute("/directions/$dir/$page")({
  component: DirectionRoute,
});

function DirectionRoute() {
  const { dir, page } = Route.useParams();
  if (!isDirectionId(dir) || !isDirectionPageId(page)) throw notFound();
  return <DirectionPage dir={dir} page={page} />;
}
