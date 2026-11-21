import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Info, Languages, Moon, Palette, Server, Sun, User } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "@tanstack/react-router";

import { Topbar } from "@/components/layout/topbar";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Field } from "@/components/ui/field";
import { Skeleton } from "@/components/ui/skeleton";
import { Segmented } from "@/components/ui/tabs";
import { toast } from "@/lib/toast";
import { env } from "@/lib/env";
import { isTransportFailure } from "@/lib/api/errors";
import { useUiStore } from "@/stores/ui";

import { settingsKeys, tryServerSettings, updatePreferences } from "./api";

export function SettingsPage() {
  const { t } = useTranslation("settings");
  const locale = useUiStore((state) => state.locale);
  const setLocale = useUiStore((state) => state.setLocale);
  const theme = useUiStore((state) => state.theme);
  const setTheme = useUiStore((state) => state.setTheme);
  const queryClient = useQueryClient();

  const server = useQuery({
    queryKey: settingsKeys.server,
    queryFn: tryServerSettings,
    staleTime: 60_000,
  });

  const serverData = server.data;
  const backendReachable = Boolean(serverData?.timezone);

  const saveLocale = (next: "zh" | "en") => {
    setLocale(next);
    updatePreferences({ locale: next })
      .then(() => toast.success(t("save.success")))
      .catch((error: unknown) => {
        if (isTransportFailure(error)) return;
        toast.error(t("save.error"));
      })
      .finally(() => {
        void queryClient.invalidateQueries({ queryKey: settingsKeys.server });
      });
  };

  return (
    <>
      <Topbar title={t("title")} subtitle={t("subtitle")} />
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto grid w-full max-w-3xl gap-5 px-4 py-5 md:px-6 md:py-6">
          <Card>
            <CardHeader
              title={t("appearance.title")}
              actions={<Palette className="size-4 text-fg-subtle" />}
            />
            <CardBody className="grid gap-5">
              <Field label={t("appearance.theme")} hint={t("appearance.themeDescription")}>
                <Segmented
                  ariaLabel={t("appearance.theme")}
                  value={theme}
                  onChange={setTheme}
                  className="w-fit"
                  options={[
                    { value: "light", label: t("appearance.light"), icon: <Sun /> },
                    { value: "dark", label: t("appearance.dark"), icon: <Moon /> },
                  ]}
                />
              </Field>
              <Field
                label={t("appearance.language")}
                hint={t("appearance.languageDescription")}
              >
                <Segmented
                  ariaLabel={t("appearance.language")}
                  value={locale}
                  onChange={saveLocale}
                  className="w-fit"
                  options={[
                    { value: "zh", label: t("appearance.zh"), icon: <Languages /> },
                    { value: "en", label: t("appearance.en"), icon: <Languages /> },
                  ]}
                />
              </Field>
            </CardBody>
          </Card>

          <Card>
            <CardHeader
              title={t("server.title")}
              description={t("server.timezoneDescription")}
              actions={<Server className="size-4 text-fg-subtle" />}
            />
            <CardBody className="grid gap-3">
              {server.isPending ? (
                <div className="grid gap-2">
                  <Skeleton className="h-4 w-1/3" />
                  <Skeleton className="h-4 w-2/3" />
                  <Skeleton className="h-4 w-1/2" />
                </div>
              ) : null}

              {!server.isPending && !backendReachable ? (
                <Alert tone="warning" title={t("about.disconnected")}>
                  {t("server.unreachable")}
                </Alert>
              ) : null}

              {serverData ? (
                <dl className="grid gap-0 divide-y divide-line-subtle text-sm">
                  <SettingRow
                    label={t("server.timezone")}
                    value={
                      serverData.timezone ? (
                        <span className="font-mono text-xs">{serverData.timezone}</span>
                      ) : (
                        <Badge tone="warning">{t("about.disconnected")}</Badge>
                      )
                    }
                  />
                  <SettingRow
                    label={t("server.upload")}
                    value={
                      serverData.upload ? (
                        <span>{serverData.upload.max_upload_mb} MB</span>
                      ) : (
                        <span className="text-fg-subtle">{t("profile.none")}</span>
                      )
                    }
                  />
                  <SettingRow
                    label={t("server.hitl")}
                    value={
                      serverData.hitl ? (
                        <Badge tone={serverData.hitl.enabled ? "success" : "neutral"} dot>
                          {serverData.hitl.enabled ? t("server.hitlOn") : t("server.hitlOff")}
                        </Badge>
                      ) : (
                        <span className="text-fg-subtle">{t("profile.none")}</span>
                      )
                    }
                  />
                </dl>
              ) : null}
            </CardBody>
          </Card>

          <Card>
            <CardHeader
              title={t("profile.title")}
              actions={<User className="size-4 text-fg-subtle" />}
            />
            <CardBody className="grid gap-0 divide-y divide-line-subtle text-sm">
              <SettingRow
                label={t("profile.locale")}
                value={
                  <span className="font-mono text-xs">
                    {serverData?.preferences?.locale ?? locale}
                  </span>
                }
              />
              <SettingRow
                label={t("profile.preferredModel")}
                value={
                  serverData?.preferences?.preferred_model ? (
                    <span className="font-mono text-xs">
                      {serverData.preferences.preferred_model}
                    </span>
                  ) : (
                    <span className="text-fg-subtle">{t("profile.none")}</span>
                  )
                }
              />
            </CardBody>
          </Card>

          <Card>
            <CardHeader title={t("about.title")} actions={<Info className="size-4 text-fg-subtle" />} />
            <CardBody className="grid gap-0 divide-y divide-line-subtle text-sm">
              <SettingRow
                label={t("about.version")}
                value={<span className="font-mono text-xs">{env.appVersion}</span>}
              />
              <SettingRow
                label={t("about.backend")}
                value={
                  backendReachable ? (
                    <Badge tone="success" icon={<Check />}>
                      {t("about.connected")}
                    </Badge>
                  ) : (
                    <Badge tone="danger">{t("about.disconnected")}</Badge>
                  )
                }
              />
            </CardBody>
            <CardBody className="border-t border-line-subtle pt-3">
              <Button variant="secondary" size="sm" asChild>
                <Link to="/design">{t("about.openDesign")}</Link>
              </Button>
            </CardBody>
          </Card>
        </div>
      </div>
    </>
  );
}

function SettingRow({
  label,
  value,
}: {
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-4 py-2.5">
      <dt className="text-fg-muted">{label}</dt>
      <dd className="text-right text-fg">{value}</dd>
    </div>
  );
}
