import { createFileRoute, redirect } from "@tanstack/react-router";

/** The shell has no home page yet, so the landing route is Chat. */
export const Route = createFileRoute("/_app/")({
  beforeLoad: () => {
    throw redirect({ to: "/chat" });
  },
});
