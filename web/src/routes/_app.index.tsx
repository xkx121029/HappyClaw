import { createFileRoute, redirect } from "@tanstack/react-router";

/** Landing route: Home. */
export const Route = createFileRoute("/_app/")({
  beforeLoad: () => {
    throw redirect({ to: "/home" });
  },
});
