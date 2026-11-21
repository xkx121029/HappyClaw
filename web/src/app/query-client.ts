import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";

import { isTransportFailure } from "@/lib/api/errors";
import { toast } from "@/lib/toast";

/**
 * Query defaults for a single-user local product: data is cheap to refetch and
 * almost never stale for long, so we do not cache aggressively and we do not
 * burn retries on a request the server already rejected with a 4xx.
 */
export const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError(error) {
      if (!isTransportFailure(error)) return;
      toast.error("Backend unreachable", "Start HappyClaw, then retry.");
    },
  }),
  mutationCache: new MutationCache({
    onError(error) {
      if (!isTransportFailure(error) || !(error instanceof Error)) return;
      toast.error("Request failed", error.message);
    },
  }),
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      gcTime: 5 * 60_000,
      refetchOnWindowFocus: false,
      retry: (failureCount, error) => {
        if (isTransportFailure(error)) return false;
        return failureCount < 1;
      },
    },
    mutations: {
      retry: false,
    },
  },
});
