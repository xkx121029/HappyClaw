import { useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { octopThreadsApi } from "../../../api/modules/octopThreads";
import * as chatStore from "./chatStore";
import { EMPTY_CHAT_SESSION_KEY } from "../constants";
import {
  markPendingThread,
  pickPreferredSession,
  toSession,
  type Session,
} from "./useSessions";

interface UseChatSessionActionsParams {
  resolvedAgentId: string | null | undefined;
  activeThreadId: string | null;
  sessions: Session[];
  isMobile: boolean;
  setActiveAgent: (id: string) => void;
  setSidebarOpen: (open: boolean) => void;
  setSelectedModel: (model: string | null) => void;
  setHasBrowserTool: (value: boolean) => void;
  deleteSession: (id: string, compact: boolean) => Promise<boolean | null>;
  clearMessages: () => void;
  resetNavForAgentSwitch: () => void;
  markInitialNavDone: (agentId: string) => void;
  /** Refresh the sidebar after a quick thread was created. */
  fetchSessions?: (activeThreadId?: string) => Promise<unknown>;
  /** Surface quick-chat creation failures (hook stays i18n-free). */
  notifyError?: (message: string) => void;
}

export function useChatSessionActions({
  resolvedAgentId,
  activeThreadId,
  sessions,
  isMobile,
  setActiveAgent,
  setSidebarOpen,
  setSelectedModel,
  setHasBrowserTool,
  deleteSession,
  clearMessages,
  resetNavForAgentSwitch,
  markInitialNavDone,
  fetchSessions,
  notifyError,
}: UseChatSessionActionsParams) {
  const navigate = useNavigate();

  const handleNewChat = useCallback(() => {
    setSelectedModel(null);
    setHasBrowserTool(false);
    const agent = resolvedAgentId;
    if (!agent) return;
    navigate(`/chat/${agent}`);
  }, [navigate, resolvedAgentId, setSelectedModel, setHasBrowserTool]);

  /**
   * New chat with an arbitrary expert. Unlike {@link navigateToAgent} this stays
   * on the empty-chat view instead of jumping to that expert's latest thread.
   * With ``projectId`` the conversation is created inside that project so it
   * starts in the project folder instead of the expert's default workspace.
   */
  const handleNewChatWithAgent = useCallback(
    (agentId: string, projectId?: string | null) => {
      if (!agentId) return;
      setSelectedModel(null);
      setHasBrowserTool(false);
      if (agentId !== resolvedAgentId) {
        resetNavForAgentSwitch();
        setActiveAgent(agentId);
      }
      markInitialNavDone(agentId);
      if (projectId) {
        void octopThreadsApi
          .create(agentId, { projectId })
          .then((created) => navigate(`/chat/${agentId}/${created.thread_id}`))
          // 建不出来就退回空对话，至少还能继续聊
          .catch(() => navigate(`/chat/${agentId}`));
      } else {
        navigate(`/chat/${agentId}`);
      }
      chatStore.clearMessages(EMPTY_CHAT_SESSION_KEY);
      if (isMobile) setSidebarOpen(false);
    },
    [
      navigate,
      resolvedAgentId,
      isMobile,
      setActiveAgent,
      setSidebarOpen,
      setSelectedModel,
      setHasBrowserTool,
      resetNavForAgentSwitch,
      markInitialNavDone,
    ],
  );

  /**
   * Quick chat: a sidebar-level entry that lands on a brand-new no-workspace
   * conversation with the given expert (HappyClaw). The server tags the thread
   * as ``quick`` so it never gets a directory and never rebinds the normal
   * dashboard session.
   */
  const handleQuickChat = useCallback(
    async (agentId: string) => {
      if (!agentId) return;
      setSelectedModel(null);
      setHasBrowserTool(false);
      if (agentId !== resolvedAgentId) {
        resetNavForAgentSwitch();
        setActiveAgent(agentId);
      }
      markInitialNavDone(agentId);
      chatStore.clearMessages(EMPTY_CHAT_SESSION_KEY);
      if (isMobile) setSidebarOpen(false);
      try {
        const created = await octopThreadsApi.createQuick(agentId);
        markPendingThread(created.thread_id);
        // Keep ``quick=1`` on the thread URL so the quick identity survives
        // reloads and the sidebar keeps 快速对话 selected.
        navigate(`/chat/${agentId}/${created.thread_id}?quick=1`);
        void fetchSessions?.(created.thread_id);
      } catch (error) {
        notifyError?.(error instanceof Error ? error.message : String(error));
        navigate(`/chat/${agentId}`);
      }
    },
    [
      navigate,
      resolvedAgentId,
      isMobile,
      setActiveAgent,
      setSidebarOpen,
      setSelectedModel,
      setHasBrowserTool,
      resetNavForAgentSwitch,
      markInitialNavDone,
      fetchSessions,
      notifyError,
    ],
  );

  // Keep the quick flag on the URL when switching into a quick conversation,
  // so the sidebar highlight and the "no workspace" chip stay correct.
  const handleSelectSession = useCallback(
    (id: string, quick = false) => {
      const agent = resolvedAgentId;
      if (!agent) return;
      if (id === activeThreadId) return;
      setSelectedModel(null);
      void octopThreadsApi.rebind(agent, id).catch(() => {});
      navigate(`/chat/${agent}/${id}${quick ? "?quick=1" : ""}`);
      if (isMobile) setSidebarOpen(false);
    },
    [
      activeThreadId,
      navigate,
      isMobile,
      resolvedAgentId,
      setSidebarOpen,
      setSelectedModel,
    ],
  );

  const navigateToAgent = useCallback(
    (agentId: string) => {
      if (!agentId) return;
      resetNavForAgentSwitch();
      navigate(`/chat/${agentId}`, { replace: true });
      setActiveAgent(agentId);
      // We land on the new-chat view, so only that session is stale here.
      // Clearing the thread we are leaving would drop an in-flight turn.
      chatStore.clearMessages(EMPTY_CHAT_SESSION_KEY);
      if (isMobile) setSidebarOpen(false);

      void (async () => {
        try {
          const rows = await octopThreadsApi.list(agentId);
          const preferred = pickPreferredSession(rows.map(toSession));
          if (preferred) {
            markInitialNavDone(agentId);
            void octopThreadsApi.rebind(agentId, preferred.id).catch(() => {});
            navigate(`/chat/${agentId}/${preferred.id}`, { replace: true });
          } else {
            markInitialNavDone(agentId);
          }
        } catch {
          /* initialNav effect picks thread once sessions load */
        }
      })();
    },
    [
      setActiveAgent,
      navigate,
      isMobile,
      setSidebarOpen,
      resetNavForAgentSwitch,
      markInitialNavDone,
    ],
  );

  const handleDeleteSession = useCallback(
    async (id: string, compact: boolean) => {
      const deleted = await deleteSession(id, compact);
      if (deleted !== true) return deleted;
      const agent = resolvedAgentId;
      if (id === activeThreadId && agent) {
        const remaining = sessions.filter((s) => s.id !== id);
        const preferred = pickPreferredSession(remaining);
        if (preferred) {
          navigate(`/chat/${agent}/${preferred.id}`, { replace: true });
        } else {
          navigate(`/chat/${agent}`, { replace: true });
          clearMessages();
        }
      }
      return true;
    },
    [
      activeThreadId,
      sessions,
      deleteSession,
      navigate,
      clearMessages,
      resolvedAgentId,
    ],
  );

  return {
    handleNewChat,
    handleNewChatWithAgent,
    handleQuickChat,
    handleSelectSession,
    navigateToAgent,
    handleDeleteSession,
  };
}
