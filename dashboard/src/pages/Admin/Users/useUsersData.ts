/**
 * Data layer for the admin-users screen: loads user rows, agents, the
 * permission catalog, role templates and filesystem defaults, and keeps the
 * derived lookups the card and table views need.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { authApi } from "../../../api/modules/auth";
import { userRolesApi, type UserRole } from "../../../api/modules/userRoles";
import { request } from "../../../api/request";
import type { OctopAgent } from "../../../context/AgentContext";
import { apiErrorMessage } from "../../../utils/apiError";
import { message } from "@/utils/antdMessage";
import { HOST_FS_ROOT } from "../../Experts/components/rootDirTree";
import { fetchFilesystemDefaults } from "../../Experts/components/agentBackendForm";
import { lockRemainingSeconds, useNowSeconds } from "./userTime";
import {
  permFullLabel,
  type PermissionCatalogItem,
  type UserRow,
} from "./usersListTypes";

export function useUsersData() {
  const { t } = useTranslation();
  const [agents, setAgents] = useState<OctopAgent[]>([]);
  const [agentsLoading, setAgentsLoading] = useState(true);
  const [rows, setRows] = useState<UserRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [permCatalog, setPermCatalog] = useState<PermissionCatalogItem[]>([]);
  const [userRoles, setUserRoles] = useState<UserRole[]>([]);
  const [fsTreeRoots, setFsTreeRoots] = useState<string[]>([HOST_FS_ROOT]);
  const [workspaceRootAllowed, setWorkspaceRootAllowed] = useState(true);
  const [currentUserId, setCurrentUserId] = useState<number | null>(null);
  const [actorIsAdmin, setActorIsAdmin] = useState(true);

  const permLabelByKey = useMemo(() => {
    const map = new Map<string, string>();
    for (const item of permCatalog) {
      map.set(item.key, permFullLabel(item));
    }
    return map;
  }, [permCatalog]);

  const baselinePermissions = useMemo(
    () =>
      permCatalog
        .filter((p) => p.category === "settings" || p.category === "nav")
        .map((p) => p.key),
    [permCatalog],
  );

  const hasLockedUser = useMemo(
    () => rows.some((row) => row.login_locked),
    [rows],
  );
  const nowSec = useNowSeconds(hasLockedUser);

  const agentsByUserId = useMemo(() => {
    const map = new Map<number, OctopAgent[]>();
    for (const agent of agents) {
      if (agent.user_id == null) continue;
      const list = map.get(agent.user_id) ?? [];
      list.push(agent);
      map.set(agent.user_id, list);
    }
    return map;
  }, [agents]);

  const refreshUsers = useCallback(async () => {
    setLoading(true);
    try {
      const data = await request<UserRow[]>("/users");
      setRows(data);
    } catch (err) {
      message.error(apiErrorMessage(err, t("adminUsers.loadFailed"), t));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    if (!hasLockedUser) return;
    const anyExpired = rows.some(
      (row) => row.login_locked && lockRemainingSeconds(row, nowSec) === 0,
    );
    if (anyExpired) void refreshUsers();
  }, [hasLockedUser, nowSec, rows, refreshUsers]);

  const refreshAgents = useCallback(async () => {
    setAgentsLoading(true);
    try {
      const data = await request<OctopAgent[]>("/agents?scope=all");
      setAgents(data);
    } catch (err) {
      message.error(apiErrorMessage(err, t("adminUsers.loadFailed"), t));
      setAgents([]);
    } finally {
      setAgentsLoading(false);
    }
  }, [t]);

  const patchAgent = useCallback(
    (agentId: string, patch: Partial<OctopAgent>) => {
      setAgents((prev) =>
        prev.map((a) => (a.agent_id === agentId ? { ...a, ...patch } : a)),
      );
    },
    [],
  );

  const handleDrawerStateChange = useCallback(
    (agentId: string, newState: string) => {
      patchAgent(agentId, { state: newState });
    },
    [patchAgent],
  );

  const handleDrawerDeleted = useCallback(
    (agentId: string) => {
      setAgents((prev) => prev.filter((a) => a.agent_id !== agentId));
      void refreshAgents();
    },
    [refreshAgents],
  );

  const refreshAll = useCallback(async () => {
    await Promise.all([refreshUsers(), refreshAgents()]);
  }, [refreshUsers, refreshAgents]);

  useEffect(() => {
    void refreshAll();
    authApi
      .me()
      .then((u) => {
        setCurrentUserId(u.id);
        setActorIsAdmin(u.role === "admin");
      })
      .catch(() => {
        setCurrentUserId(null);
        setActorIsAdmin(false);
      });
    request<PermissionCatalogItem[]>("/users/permissions")
      .then(setPermCatalog)
      .catch(() => setPermCatalog([]));
    userRolesApi
      .list()
      .then(setUserRoles)
      .catch(() => setUserRoles([]));
    fetchFilesystemDefaults()
      .then((defaults) => {
        setFsTreeRoots(
          defaults.browse_roots?.length
            ? defaults.browse_roots
            : [defaults.tree_root],
        );
        setWorkspaceRootAllowed(!defaults.in_container);
      })
      .catch(() => {
        setFsTreeRoots([HOST_FS_ROOT]);
        setWorkspaceRootAllowed(true);
      });
  }, [refreshAll]);

  return {
    rows,
    loading,
    agents,
    agentsLoading,
    permCatalog,
    userRoles,
    fsTreeRoots,
    workspaceRootAllowed,
    currentUserId,
    actorIsAdmin,
    permLabelByKey,
    baselinePermissions,
    agentsByUserId,
    hasLockedUser,
    nowSec,
    refreshUsers,
    refreshAgents,
    patchAgent,
    refreshAll,
    handleDrawerStateChange,
    handleDrawerDeleted,
  };
}
