import { createFileRoute } from "@tanstack/react-router";

import { TokenUsagePage } from "@/features/usage/TokenUsagePage";

export const Route = createFileRoute("/_app/token-usage")({
  component: TokenUsagePage,
});
