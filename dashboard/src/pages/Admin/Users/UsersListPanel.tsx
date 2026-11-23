/**
 * Admin → Users page (plan §14.7).
 *
 * List all users with role/disabled toggles, password reset, delete.
 * Card and table views (default table). The view switcher + refresh +
 * new-user buttons live in a content-area toolbar (mirrors the Experts
 * page layout). Each row/card shows agent count; click opens a drawer
 * with that user's agents.
 *
 * Endpoints (all require admin role; backend returns 403 otherwise):
 *   GET    /api/users
 *   POST   /api/users
 *   POST   /api/users/batch
 *   PATCH  /api/users/{id}
 *   POST   /api/users/{id}/reset-password
 *   DELETE /api/users/{id}
 *
 * The screen's parts live in sibling modules — see `usersListTypes.ts`,
 * `policyForm.ts`, `userTime.ts`, the component files and the `use*` hooks in
 * this directory. Everything they own is re-exported below so imports from
 * this path keep working.
 */

import { useCallback, useMemo, useState } from "react";

import type { OctopAgent } from "../../../context/AgentContext";
import { useCardTableView } from "../../../hooks/useCardTableView";
import { useSetCurrentUser } from "../../../hooks/useCurrentUser";
import { useIsMobile } from "../../../hooks/useIsMobile";
import { useServerTimezone } from "../../../hooks/useServerTimezone";
import EditAgentDrawer from "../../Experts/components/EditAgentDrawer";
import { BatchMaxAgentsModal, BatchTokenQuotaModal } from "./BatchQuotaModals";
import InviteDrawer from "./InviteDrawer";
import { UserAgentsDrawer } from "./UserAgentsDrawer";
import { UserCardGrid } from "./UserCardGrid";
import { UserCreateDrawer } from "./UserCreateDrawer";
import { UserEditDrawer } from "./UserEditDrawer";
import { UserResetPasswordModal } from "./UserResetPasswordModal";
import { UsersBatchBar, UsersToolbar } from "./UsersToolbar";
import { UsersTable } from "./UsersTable";
import { useBatchActions } from "./useBatchActions";
import { useUserMutations } from "./useUserMutations";
import { useUsersData } from "./useUsersData";
import type { UserRow } from "./usersListTypes";

export {
  DEFAULT_EXPERT_TEMPLATE_ID,
  FIELD_ICON_PROPS,
  permFullLabel,
  type BatchAction,
  type BatchMaxAgentsFormValues,
  type BatchResponse,
  type BatchTokenFormValues,
  type CreateValues,
  type EditValues,
  type ExpertTemplateOption,
  type PermissionCatalogItem,
  type PolicyFormValues,
  type ResetValues,
  type UserRow,
} from "./usersListTypes";
export {
  policyFieldsFromRole,
  policyPayload,
  rolePoliciesFromForm,
} from "./policyForm";
export {
  formatUserTs,
  lockRemainingSeconds,
  useNowSeconds,
} from "./userTime";
export { MaxAgentsInput, TokenQuotaInput } from "./QuotaInputs";
export { ExpertTemplatePicker } from "./ExpertTemplatePicker";
export { UserRoleField } from "./UserRoleField";
export { RoleLegend, RoleNameMark } from "./RoleDisplay";
export { ResourcePolicyFields } from "./ResourcePolicyFields";
export {
  CollapsiblePermissionsField,
  PermissionCheckboxPicker,
  PermissionSummary,
  type PermissionCheckboxPickerProps,
} from "./PermissionFields";
export { UserCardGrid, type UserCardGridProps } from "./UserCardGrid";
export { UsersTable } from "./UsersTable";
export { UsersBatchBar, UsersToolbar } from "./UsersToolbar";
export { UserAgentsDrawer } from "./UserAgentsDrawer";
export { UserCreateDrawer } from "./UserCreateDrawer";
export { UserEditDrawer } from "./UserEditDrawer";
export { UserResetPasswordModal } from "./UserResetPasswordModal";
export { BatchMaxAgentsModal, BatchTokenQuotaModal } from "./BatchQuotaModals";

export default function UsersListPanel() {
  const setCurrentUser = useSetCurrentUser();
  const timeZone = useServerTimezone();
  const isMobile = useIsMobile();
  const { viewMode, setViewMode, showCardView } = useCardTableView("table");
  const [searchQuery, setSearchQuery] = useState("");
  const [inviteOpen, setInviteOpen] = useState(false);
  const [agentDrawerUser, setAgentDrawerUser] = useState<UserRow | null>(null);
  const [editAgent, setEditAgent] = useState<OctopAgent | null>(null);

  const {
    rows,
    loading,
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
    nowSec,
    refreshUsers,
    refreshAgents,
    patchAgent,
    refreshAll,
    handleDrawerStateChange,
    handleDrawerDeleted,
  } = useUsersData();

  const filteredRows = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    if (!query) return rows;
    return rows.filter((row) => {
      const username = row.username.toLowerCase();
      const displayName = (row.display_name ?? "").trim().toLowerCase();
      const email = (row.email ?? "").trim().toLowerCase();
      const roleName = (row.role_name ?? "").trim().toLowerCase();
      return (
        username.includes(query) ||
        displayName.includes(query) ||
        email.includes(query) ||
        roleName.includes(query)
      );
    });
  }, [rows, searchQuery]);

  const {
    selectedIds,
    setSelectedIds,
    batchSubmitting,
    batchTokenOpen,
    setBatchTokenOpen,
    batchTokenForm,
    batchMaxAgentsOpen,
    setBatchMaxAgentsOpen,
    batchMaxAgentsForm,
    clearSelection,
    toggleSelectOne,
    setSelectAllVisible,
    confirmBatchAction,
    openBatchToken,
    submitBatchToken,
    openBatchMaxAgents,
    submitBatchMaxAgents,
  } = useBatchActions({ rows: filteredRows, refreshUsers });

  const selectedIdSet = useMemo(() => new Set(selectedIds), [selectedIds]);
  const selectedVisibleCount = useMemo(
    () => filteredRows.filter((row) => selectedIdSet.has(row.id)).length,
    [filteredRows, selectedIdSet],
  );

  const {
    createOpen,
    setCreateOpen,
    expertTemplates,
    setPendingUserAvatar,
    pendingUserIcon,
    setPendingUserIcon,
    submitting,
    form,
    editTarget,
    setEditTarget,
    editSubmitting,
    editForm,
    resetTarget,
    setResetTarget,
    resetSubmitting,
    resetForm,
    isSelfAdmin,
    onCreate,
    openCreate,
    openEdit,
    togglePatch,
    onEditSubmit,
    onDelete,
    onResetSubmit,
    onResetMfa,
    onUnlockLogin,
    onEditAvatarIcon,
    onEditAvatarPick,
    onEditAvatarRemove,
  } = useUserMutations({
    refreshUsers,
    refreshAll,
    workspaceRootAllowed,
    userRoles,
    baselinePermissions,
    currentUserId,
    setCurrentUser,
  });

  const drawerAgents = agentDrawerUser
    ? agentsByUserId.get(agentDrawerUser.id) ?? []
    : [];

  const handleEditSaved = useCallback(
    (
      updated: Pick<
        OctopAgent,
        "agent_id" | "name" | "description" | "default_model"
      >,
    ) => {
      setEditAgent(null);
      patchAgent(updated.agent_id, {
        name: updated.name,
        description: updated.description,
        default_model: updated.default_model,
      });
      void refreshAgents();
    },
    [patchAgent, refreshAgents],
  );

  return (
    <>
      <UsersToolbar
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        showCardView={showCardView}
        visibleCount={filteredRows.length}
        selectedVisibleCount={selectedVisibleCount}
        onSelectAllVisible={setSelectAllVisible}
        viewMode={viewMode}
        onViewModeChange={setViewMode}
        onRefresh={() => void refreshAll()}
        onInvite={() => setInviteOpen(true)}
        onCreate={openCreate}
      />

      {selectedIds.length > 0 ? (
        <UsersBatchBar
          count={selectedIds.length}
          submitting={batchSubmitting}
          onEnable={() => confirmBatchAction("enable")}
          onDisable={() => confirmBatchAction("disable")}
          onOpenToken={openBatchToken}
          onOpenMaxAgents={openBatchMaxAgents}
          onDelete={() => confirmBatchAction("delete")}
          onClear={clearSelection}
        />
      ) : null}

      {showCardView ? (
        <UserCardGrid
          rows={filteredRows}
          loading={loading}
          agentsByUserId={agentsByUserId}
          agentsLoading={agentsLoading}
          currentUserId={currentUserId}
          permLabelByKey={permLabelByKey}
          selectedIds={selectedIds}
          onToggleSelect={toggleSelectOne}
          onTogglePatch={togglePatch}
          onEdit={openEdit}
          onShowAgents={setAgentDrawerUser}
          onResetPassword={(row) => {
            setResetTarget(row);
            resetForm.resetFields();
          }}
          onResetMfa={onResetMfa}
          onDelete={onDelete}
          onUnlockLogin={onUnlockLogin}
          nowSec={nowSec}
          userRoles={userRoles}
        />
      ) : (
        <UsersTable
          rows={filteredRows}
          loading={loading}
          selectedIds={selectedIds}
          onSelectionChange={setSelectedIds}
          currentUserId={currentUserId}
          agentsByUserId={agentsByUserId}
          agentsLoading={agentsLoading}
          permLabelByKey={permLabelByKey}
          userRoles={userRoles}
          nowSec={nowSec}
          timeZone={timeZone}
          isMobile={isMobile}
          onShowAgents={setAgentDrawerUser}
          onTogglePatch={togglePatch}
          onEdit={openEdit}
          onResetPassword={(row) => {
            setResetTarget(row);
            resetForm.resetFields();
          }}
          onResetMfa={onResetMfa}
          onDelete={onDelete}
          onUnlockLogin={onUnlockLogin}
        />
      )}

      <UserAgentsDrawer
        user={agentDrawerUser}
        agents={drawerAgents}
        loading={agentsLoading}
        onClose={() => setAgentDrawerUser(null)}
        onEditAgent={setEditAgent}
        onDeleted={handleDrawerDeleted}
        onStateChange={handleDrawerStateChange}
        onRefreshAgents={() => void refreshAgents()}
      />

      <EditAgentDrawer
        open={editAgent !== null}
        agent={editAgent}
        onClose={() => setEditAgent(null)}
        onSaved={handleEditSaved}
      />

      <InviteDrawer open={inviteOpen} onClose={() => setInviteOpen(false)} />

      <UserCreateDrawer
        open={createOpen}
        onClose={() => {
          setCreateOpen(false);
          form.resetFields();
        }}
        form={form}
        submitting={submitting}
        onSubmit={onCreate}
        expertTemplates={expertTemplates}
        userRoles={userRoles}
        workspaceRootAllowed={workspaceRootAllowed}
        actorIsAdmin={actorIsAdmin}
        permCatalog={permCatalog}
        fsTreeRoots={fsTreeRoots}
        pendingUserIcon={pendingUserIcon}
        onPickAvatar={setPendingUserAvatar}
        onSelectIcon={(icon) => {
          setPendingUserIcon(icon);
          setPendingUserAvatar(null);
        }}
        onRemoveAvatar={() => setPendingUserAvatar(null)}
      />

      <UserEditDrawer
        open={editTarget !== null}
        target={editTarget}
        onClose={() => {
          setEditTarget(null);
          editForm.resetFields();
        }}
        form={editForm}
        submitting={editSubmitting}
        onSubmit={onEditSubmit}
        userRoles={userRoles}
        workspaceRootAllowed={workspaceRootAllowed}
        actorIsAdmin={actorIsAdmin}
        permCatalog={permCatalog}
        fsTreeRoots={fsTreeRoots}
        isSelfAdmin={Boolean(editTarget && isSelfAdmin(editTarget))}
        onSelectIcon={onEditAvatarIcon}
        onPickAvatar={onEditAvatarPick}
        onRemoveAvatar={onEditAvatarRemove}
      />

      <UserResetPasswordModal
        username={resetTarget?.username ?? null}
        open={resetTarget !== null}
        onCancel={() => {
          setResetTarget(null);
          resetForm.resetFields();
        }}
        form={resetForm}
        submitting={resetSubmitting}
        onSubmit={onResetSubmit}
      />

      <BatchTokenQuotaModal
        open={batchTokenOpen}
        count={selectedIds.length}
        submitting={batchSubmitting}
        onCancel={() => {
          setBatchTokenOpen(false);
          batchTokenForm.resetFields();
        }}
        form={batchTokenForm}
        onSubmit={submitBatchToken}
      />

      <BatchMaxAgentsModal
        open={batchMaxAgentsOpen}
        count={selectedIds.length}
        submitting={batchSubmitting}
        onCancel={() => {
          setBatchMaxAgentsOpen(false);
          batchMaxAgentsForm.resetFields();
        }}
        form={batchMaxAgentsForm}
        onSubmit={submitBatchMaxAgents}
      />
    </>
  );
}
