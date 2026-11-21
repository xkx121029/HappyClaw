import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowRight, CheckCircle2, Database, Plug, ServerCog } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "@tanstack/react-router";

import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardFooter, CardHeader } from "@/components/ui/card";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { LoadingBlock } from "@/components/ui/spinner";
import { isTransportFailure } from "@/lib/api/errors";

import {
  getSetupStatus,
  listPresets,
  probeDatabase,
  probeProvider,
  type DatabaseProbeInput,
  type ProbeResult,
  type ProviderProbeInput,
} from "./api";

/**
 * First-run page. In this build a single-user instance binds its database and
 * creates its owner at boot, so there is nothing to *write* here: the page
 * reports the state the server actually has and lets an operator prove that a
 * database and a provider are reachable before the first conversation.
 */
export function SetupPage() {
  const { t } = useTranslation("setup");
  const navigate = useNavigate();

  const [database, setDatabase] = useState<DatabaseProbeInput>({ driver: "sqlite" });
  const [provider, setProvider] = useState<ProviderProbeInput>({
    name: "",
    type: "openai",
    api_key: "",
    model_id: "",
  });
  const [dbResult, setDbResult] = useState<ProbeResult | null>(null);
  const [provResult, setProvResult] = useState<ProbeResult | null>(null);

  const status = useQuery({ queryKey: ["setup", "status"], queryFn: getSetupStatus });
  const presets = useQuery({ queryKey: ["setup", "presets"], queryFn: listPresets });

  const probeDb = useMutation({
    mutationFn: probeDatabase,
    onSuccess: setDbResult,
    onError: (error: unknown) => setDbResult(toResult(error)),
  });
  const probeProv = useMutation({
    mutationFn: probeProvider,
    onSuccess: setProvResult,
    onError: (error: unknown) => setProvResult(toResult(error)),
  });

  if (status.isPending) {
    return (
      <SetupFrame subtitle={t("subtitle")}>
        <LoadingBlock label={t("loading")} />
      </SetupFrame>
    );
  }

  const data = status.data;
  if (!data) {
    return (
      <SetupFrame subtitle={t("subtitle")}>
        <Alert tone="warning" title={t("unreachable")} />
      </SetupFrame>
    );
  }

  return (
    <SetupFrame subtitle={t("subtitle")}>
      <div className="grid gap-3">
        <Card>
          <CardHeader
            title={t("state.heading")}
            description={t("state.body")}
            actions={<ServerCog className="size-4 text-fg-subtle" />}
          />
          <CardBody className="grid gap-2">
            <Row
              label={t("state.driver")}
              value={<span className="font-mono text-xs">{data.database_driver}</span>}
            />
            <Row
              label={t("state.bound")}
              value={
                <Badge tone={data.database_bound ? "success" : "warning"} dot>
                  {data.database_bound ? t("state.yes") : t("state.no")}
                </Badge>
              }
            />
            <Row
              label={t("state.owner")}
              value={
                <Badge tone={data.local_account ? "success" : "warning"} dot>
                  {data.local_account ? t("state.ownerLocal") : t("state.ownerMissing")}
                </Badge>
              }
            />
            <Row
              label={t("state.mode")}
              value={data.single_user ? t("state.singleUser") : t("state.multiUser")}
            />
            {data.setup_required ? (
              <Alert tone="info" title={t("state.required")}>
                {t("state.requiredBody")}
              </Alert>
            ) : (
              <p className="flex items-center gap-1.5 text-2xs text-fg-subtle">
                <CheckCircle2 className="size-3 text-success" />
                {t("state.ready")}
              </p>
            )}
          </CardBody>
          <CardFooter>
            <Button
              variant="primary"
              trailingIcon={<ArrowRight />}
              onClick={() => void navigate({ to: "/home" })}
            >
              {t("state.enter")}
            </Button>
          </CardFooter>
        </Card>

        <Card>
          <CardHeader
            title={t("database.heading")}
            description={t("database.body")}
            actions={<Database className="size-4 text-fg-subtle" />}
          />
          <CardBody className="grid gap-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label={t("database.driver")}>
                <Select
                  value={database.driver}
                  onChange={(event) =>
                    setDatabase({
                      driver: event.target.value === "postgresql" ? "postgresql" : "sqlite",
                    })
                  }
                  options={[
                    { value: "sqlite", label: "SQLite" },
                    { value: "postgresql", label: "PostgreSQL" },
                  ]}
                />
              </Field>
              {database.driver === "sqlite" ? (
                <Field label={t("database.sqlitePath")} hint={t("database.sqlitePathHint")}>
                  <Input
                    value={database.sqlite_path ?? ""}
                    onChange={(event) =>
                      setDatabase({ ...database, sqlite_path: event.target.value || undefined })
                    }
                  />
                </Field>
              ) : (
                <Field label={t("database.host")}>
                  <Input
                    value={database.host ?? ""}
                    placeholder="127.0.0.1"
                    onChange={(event) =>
                      setDatabase({ ...database, host: event.target.value || undefined })
                    }
                  />
                </Field>
              )}
            </div>
            {database.driver === "postgresql" ? (
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label={t("database.database")}>
                  <Input
                    value={database.database ?? ""}
                    onChange={(event) =>
                      setDatabase({ ...database, database: event.target.value || undefined })
                    }
                  />
                </Field>
                <Field label={t("database.user")}>
                  <Input
                    value={database.user ?? ""}
                    onChange={(event) =>
                      setDatabase({ ...database, user: event.target.value || undefined })
                    }
                  />
                </Field>
              </div>
            ) : null}
            {dbResult ? (
              <Alert
                tone={dbResult.ok ? "success" : "danger"}
                title={dbResult.ok ? t("database.ok") : t("database.failed")}
              >
                {dbResult.message}
              </Alert>
            ) : null}
          </CardBody>
          <CardFooter>
            <Button
              variant="secondary"
              size="sm"
              loading={probeDb.isPending}
              onClick={() => probeDb.mutate(database)}
            >
              {probeDb.isPending ? t("database.probing") : t("database.probe")}
            </Button>
          </CardFooter>
        </Card>

        <Card>
          <CardHeader
            title={t("provider.heading")}
            description={t("provider.body")}
            actions={<Plug className="size-4 text-fg-subtle" />}
          />
          <CardBody className="grid gap-4">
            <Field label={t("provider.preset")}>
              <Select
                value={provider.name}
                onChange={(event) => {
                  const preset = (presets.data ?? []).find(
                    (item) => item.name === event.target.value,
                  );
                  setProvider({
                    name: preset?.name ?? "",
                    type: preset?.protocol ?? "openai",
                    api_key: provider.api_key,
                    base_url: preset?.base_url ?? undefined,
                    model_id: preset?.models?.[0]?.id ?? provider.model_id,
                  });
                  setProvResult(null);
                }}
                options={[
                  { value: "", label: "—" },
                  ...(presets.data ?? []).map((preset) => ({
                    value: preset.name,
                    label: preset.name,
                  })),
                ]}
              />
            </Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label={t("provider.modelId")} required>
                <Input
                  value={provider.model_id}
                  onChange={(event) =>
                    setProvider({ ...provider, model_id: event.target.value })
                  }
                />
              </Field>
              <Field label={t("provider.apiKey")}>
                <Input
                  type="password"
                  value={provider.api_key}
                  onChange={(event) =>
                    setProvider({ ...provider, api_key: event.target.value })
                  }
                />
              </Field>
              <Field label={t("provider.baseUrl")} className="sm:col-span-2">
                <Input
                  value={provider.base_url ?? ""}
                  onChange={(event) =>
                    setProvider({ ...provider, base_url: event.target.value || undefined })
                  }
                />
              </Field>
            </div>
            {provResult ? (
              <Alert
                tone={provResult.ok ? "success" : "danger"}
                title={provResult.ok ? t("provider.ok") : t("provider.failed")}
              >
                {provResult.message}
              </Alert>
            ) : null}
          </CardBody>
          <CardFooter>
            <Button
              variant="secondary"
              size="sm"
              loading={probeProv.isPending}
              disabled={!provider.model_id}
              onClick={() => probeProv.mutate(provider)}
            >
              {probeProv.isPending ? t("provider.probing") : t("provider.probe")}
            </Button>
          </CardFooter>
        </Card>
      </div>
    </SetupFrame>
  );
}

function toResult(error: unknown): ProbeResult {
  if (isTransportFailure(error)) {
    return { ok: false, message: "The backend did not answer." };
  }
  return { ok: false, message: error instanceof Error ? error.message : "Request failed" };
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 text-sm">
      <span className="text-fg-muted">{label}</span>
      <span className="text-fg">{value}</span>
    </div>
  );
}

function SetupFrame({
  subtitle,
  children,
}: {
  subtitle: string;
  children: React.ReactNode;
}) {
  const { t } = useTranslation("setup");
  return (
    <div className="flex min-h-full items-start justify-center bg-canvas px-4 py-10">
      <div className="w-full max-w-xl">
        <header className="mb-5 flex items-center gap-3">
          <img src="/brand/happyclaw-icon.svg" alt="" className="size-10 rounded-md" />
          <div>
            <h1 className="text-xl font-semibold tracking-tight text-fg">{t("title")}</h1>
            <p className="text-xs text-fg-subtle">{subtitle}</p>
          </div>
        </header>
        {children}
      </div>
    </div>
  );
}
