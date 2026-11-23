import { useState, useEffect, useCallback } from "react";
import api from "../../../api";
import type { EnvVar } from "../../../api/types";

export function useEnvVars() {
  const [envVars, setEnvVars] = useState<EnvVar[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.listEnvs();
      if (data) setEnvVars(data);
    } catch (err) {
      // 具体报错由 API 层本地化；非 Error 抛出交给页面用 i18n 兜底文案。
      const msg = err instanceof Error ? err.message : "";
      console.error("Failed to load env vars:", err);
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  return { envVars, loading, error, fetchAll };
}
