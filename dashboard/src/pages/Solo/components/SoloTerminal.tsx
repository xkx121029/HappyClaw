import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Spin } from "antd";
import { RefreshCw } from "lucide-react";
import { useTheme } from "../../../context/ThemeContext";
import TerminalView, {
  type TerminalViewHandle,
} from "../../Control/Terminal/components/TerminalView";
import {
  useTerminal,
  type TerminalCallbacks,
  type TerminalConnState,
} from "../../Control/Terminal/useTerminal";
import { getTerminalTheme } from "../../Control/Terminal/terminalThemes";
import styles from "../solo.module.less";

interface SoloToolTerminalProps {
  agentId: string | null;
  agentReady: boolean;
}

/**
 * SOLO 页终端。复用 Workbench 的进程级终端 store（同一个 PTY 模型），
 * 用稳定 session id ``solo-<agentId>`` 避免重复起 shell。
 */
export default function SoloToolTerminal({
  agentId,
  agentReady,
}: SoloToolTerminalProps) {
  const { t } = useTranslation();
  const { isDark } = useTheme();
  const {
    sessionIds,
    createSession,
    connect,
    unbind,
    reconnect,
    sendInput,
    sendResize,
  } = useTerminal();

  const sessionId = agentId ? `solo-${agentId}` : null;
  const sessionExists = Boolean(sessionId && sessionIds.includes(sessionId));

  const [connState, setConnState] = useState<TerminalConnState>("disconnected");
  const termRef = useRef<TerminalViewHandle | null>(null);
  const callbacksRef = useRef<TerminalCallbacks | null>(null);

  const themeDefinition = useMemo(
    () => getTerminalTheme(null, isDark),
    [isDark],
  );

  useEffect(() => {
    if (!sessionId || sessionExists) return;
    createSession(sessionId);
  }, [createSession, sessionId, sessionExists]);

  const handleReady = useCallback(() => {
    if (!sessionId || !agentId) return;
    const callbacks: TerminalCallbacks = {
      onOutput: (data) => termRef.current?.write(data),
      onHistory: (data) => {
        termRef.current?.reset();
        termRef.current?.write(data);
      },
      onStateChange: (state) => setConnState(state),
      onExit: (code) => {
        termRef.current?.write(
          `\r\n\x1b[90m[${t("terminal.processExited")} (${code})]\x1b[0m\r\n`,
        );
      },
    };
    callbacksRef.current = callbacks;
    connect(sessionId, agentId, callbacks);
  }, [agentId, connect, sessionId, t]);

  useEffect(() => {
    return () => {
      const callbacks = callbacksRef.current;
      if (sessionId && callbacks) unbind(sessionId, callbacks);
    };
  }, [sessionId, unbind]);

  const handleData = useCallback(
    (data: string) => {
      if (sessionId) sendInput(sessionId, data);
    },
    [sendInput, sessionId],
  );

  const handleResize = useCallback(
    (cols: number, rows: number) => {
      if (sessionId) sendResize(sessionId, cols, rows);
    },
    [sendResize, sessionId],
  );

  const lost = connState === "disconnected" || connState === "error";

  if (!sessionId) {
    return (
      <div className={styles.panePlaceholder}>{t("solo.noAgentHint")}</div>
    );
  }

  return (
    <div className={styles.terminalWrap}>
      {sessionExists ? (
        <TerminalView
          key={sessionId}
          terminalRef={termRef}
          onData={handleData}
          onResize={handleResize}
          onReady={handleReady}
          themeDefinition={themeDefinition}
        />
      ) : (
        <div className={styles.panePlaceholder}>
          <Spin size="small" />
        </div>
      )}
      {lost && sessionExists ? (
        <div className={styles.terminalOverlay}>
          <span>
            {agentReady
              ? t("solo.terminalUnavailable")
              : t("solo.terminalNeedsAgent")}
          </span>
          <Button
            size="small"
            icon={<RefreshCw size={13} />}
            onClick={() => {
              setConnState("connecting");
              reconnect(sessionId);
            }}
          >
            {t("terminal.reconnect")}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
