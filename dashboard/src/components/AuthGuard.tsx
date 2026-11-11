import { useEffect, useState } from "react";
import { getApiUrl } from "../api/config";
import { isNetworkFetchError } from "../utils/networkError";
import BootOfflinePanel from "./BootOfflinePanel";
import BrandLoading from "./BrandLoading";

interface AuthGuardProps {
  children: React.ReactNode;
}

/**
 * 单人本机模式的入口关卡。
 *
 * 不再校验登录态、不再请求 ``/auth/me``：只要能连上本机后端就直接进入
 * 控制台。唯一保留的检查是「后端能不能连上」，连不上时给出可重试的
 * 离线面板，而不是白屏。
 */
export default function AuthGuard({ children }: AuthGuardProps) {
  const [checking, setChecking] = useState(true);
  const [offline, setOffline] = useState(false);
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const probe = async () => {
      setOffline(false);
      try {
        const response = await fetch(getApiUrl("/health"), {
          headers: { Accept: "application/json" },
        });
        // 任何 HTTP 响应都说明本机后端在线；404 也算（旧版本可能没有 /health）。
        void response;
        if (!cancelled) setChecking(false);
      } catch (err) {
        if (cancelled) return;
        if (isNetworkFetchError(err)) {
          setOffline(true);
          setChecking(false);
          return;
        }
        // 其他异常不阻断进入，交给具体页面报错。
        setChecking(false);
      }
    };
    void probe();
    return () => {
      cancelled = true;
    };
  }, [retryKey]);

  if (offline) {
    return (
      <BootOfflinePanel
        onRetry={() => {
          setChecking(true);
          setOffline(false);
          setRetryKey((key) => key + 1);
        }}
      />
    );
  }

  if (checking) {
    return <BrandLoading viewport />;
  }

  return <>{children}</>;
}
