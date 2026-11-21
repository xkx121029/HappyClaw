import { createFileRoute } from "@tanstack/react-router";

import { SetupPage } from "@/features/setup/SetupPage";

/** First-run wizard: outside the app shell, so it renders before any data exists. */
export const Route = createFileRoute("/setup")({
  component: SetupPage,
});
