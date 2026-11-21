import { RotateCcw, Save } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { PageBody, Topbar } from "@/components/layout/topbar";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardFooter, CardHeader } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Field, FieldGroup } from "@/components/ui/field";
import { Input, Textarea } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { LoadingBlock } from "@/components/ui/spinner";
import { toast } from "@/lib/toast";

import {
  isDirty,
  toConfig,
  useAgentRows,
  useSaveAgentConfig,
  type AgentRuntimeConfig,
} from "./api";

export function AgentConfigPage() {
  const { t } = useTranslation("agentConfig");
  const rows = useAgentRows();
  const [pickedId, setPickedId] = useState<string | undefined>();

  const agents = rows.data ?? [];
  const activeId =
    pickedId && agents.some((agent) => agent.agent_id === pickedId)
      ? pickedId
      : agents[0]?.agent_id;
  const active = agents.find((agent) => agent.agent_id === activeId);

  return (
    <>
      <Topbar
        title={t("title")}
        subtitle={t("subtitle")}
        actions={
          agents.length > 0 ? (
            <Select
              aria-label={t("agent")}
              value={activeId ?? ""}
              onChange={(event) => setPickedId(event.target.value)}
              options={agents.map((agent) => ({
                value: agent.agent_id,
                label: `${agent.name} · ${agent.state}`,
              }))}
              className="w-56"
            />
          ) : null
        }
      />
      <PageBody width="reading">
        {rows.isPending ? <LoadingBlock label={t("loading")} /> : null}

        {rows.isSuccess && rows.data === null ? (
          <Alert tone="warning" title={t("unreachable")} />
        ) : null}

        {rows.isSuccess && agents.length === 0 ? (
          <EmptyState size="lg" title={t("noAgents")} description={t("noAgentsHint")} />
        ) : null}

        {active ? (
          <ConfigForm
            key={`${active.agent_id}:${JSON.stringify(toConfig(active))}`}
            agentId={active.agent_id}
            agentName={active.name}
            state={active.state}
            initial={toConfig(active)}
          />
        ) : null}
      </PageBody>
    </>
  );
}

function ConfigForm({
  agentId,
  agentName,
  state,
  initial,
}: {
  agentId: string;
  agentName: string;
  state: string;
  initial: AgentRuntimeConfig;
}) {
  const { t } = useTranslation("agentConfig");
  const [draft, setDraft] = useState<AgentRuntimeConfig>(initial);
  const save = useSaveAgentConfig(agentId);
  const dirty = isDirty(initial, draft);

  const set = <K extends keyof AgentRuntimeConfig>(
    key: K,
    value: AgentRuntimeConfig[K],
  ) => setDraft((current) => ({ ...current, [key]: value }));

  const numberField = (
    key: "max_iters" | "max_input_length" | "temperature" | "top_p" | "max_tokens",
    label: string,
    hint: string,
    step?: string,
  ) => (
    <Field key={key} label={label} hint={hint}>
      <Input
        type="number"
        step={step}
        value={draft[key] ?? ""}
        placeholder={t("serverDefault")}
        onChange={(event) =>
          set(key, event.target.value === "" ? null : Number(event.target.value))
        }
      />
    </Field>
  );

  return (
    <Card>
      <CardHeader
        title={agentName}
        description={t("desc")}
        actions={<Badge tone={state === "running" ? "success" : "neutral"} dot>{state}</Badge>}
      />
      <CardBody className="grid gap-6">
        <FieldGroup title={t("identity")}>
          <Field label={t("fields.name")} required>
            <Input value={draft.name} onChange={(event) => set("name", event.target.value)} />
          </Field>
          <Field label={t("fields.description")}>
            <Input
              value={draft.description}
              onChange={(event) => set("description", event.target.value)}
            />
          </Field>
          <Field label={t("fields.model")} hint={t("fields.modelHint")}>
            <Input
              value={draft.default_model}
              placeholder={t("serverDefault")}
              onChange={(event) => set("default_model", event.target.value)}
            />
          </Field>
        </FieldGroup>

        <FieldGroup title={t("prompt")} description={t("promptHint")}>
          <Field label={t("fields.systemPrompt")}>
            <Textarea
              value={draft.system_prompt}
              rows={6}
              className="font-mono text-xs"
              onChange={(event) => set("system_prompt", event.target.value)}
            />
          </Field>
        </FieldGroup>

        <FieldGroup title={t("runtime")} description={t("runtimeHint")}>
          <div className="grid gap-3 sm:grid-cols-2">
            {numberField("max_iters", t("fields.maxIters"), t("hints.maxIters"))}
            {numberField("max_input_length", t("fields.maxInput"), t("hints.maxInput"))}
            {numberField("temperature", t("fields.temperature"), t("hints.temperature"), "0.1")}
            {numberField("top_p", t("fields.topP"), t("hints.topP"), "0.05")}
            {numberField("max_tokens", t("fields.maxTokens"), t("hints.maxTokens"))}
          </div>
        </FieldGroup>

        {save.isError ? (
          <Alert tone="danger" title={t("saveFailed")}>
            {save.error instanceof Error ? save.error.message : t("saveFailed")}
          </Alert>
        ) : null}
      </CardBody>
      <CardFooter>
        {dirty ? <Badge tone="warning">{t("unsaved")}</Badge> : null}
        <Button
          variant="ghost"
          size="sm"
          leadingIcon={<RotateCcw />}
          disabled={!dirty || save.isPending}
          onClick={() => setDraft(initial)}
        >
          {t("reset")}
        </Button>
        <Button
          variant="primary"
          size="sm"
          leadingIcon={<Save />}
          loading={save.isPending}
          disabled={!dirty || !draft.name.trim()}
          onClick={() =>
            save.mutate(draft, {
              onSuccess: () => toast.success(t("saved")),
            })
          }
        >
          {save.isPending ? t("saving") : t("save")}
        </Button>
      </CardFooter>
    </Card>
  );
}
