import { useQuery } from "@tanstack/react-query";
import { BarChart3 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { PageBody, Topbar } from "@/components/layout/topbar";
import { Alert } from "@/components/ui/alert";
import { Card, CardBody, CardHeader, Stat } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { Segmented } from "@/components/ui/tabs";
import { TD, TH, TBody, THead, TR, Table } from "@/components/ui/table";
import { isTransportFailure } from "@/lib/api/errors";
import { useUiStore } from "@/stores/ui";

import { getUsageReport, type UsageBucket, type UsageWindow } from "./api";

const WINDOWS: UsageWindow[] = ["last_7d", "last_30d", "all"];

export function TokenUsagePage() {
  const { t } = useTranslation("usage");
  const locale = useUiStore((state) => state.locale);
  const [window, setWindow] = useState<UsageWindow>("last_30d");

  const report = useQuery({
    queryKey: ["usage", "report", window],
    queryFn: async () => {
      try {
        return await getUsageReport(window);
      } catch (error) {
        if (isTransportFailure(error)) return null;
        throw error;
      }
    },
  });

  const fmt = (value: number) =>
    new Intl.NumberFormat(locale === "en" ? "en" : "zh", {
      notation: value >= 10_000 ? "compact" : "standard",
      maximumFractionDigits: 1,
    }).format(value);

  const data = report.data ?? null;
  const peak = Math.max(1, ...(data?.buckets ?? []).map((bucket) => bucket.total_tokens));

  return (
    <>
      <Topbar
        title={t("title")}
        subtitle={t("subtitle")}
        actions={
          <Segmented
            ariaLabel={t("window")}
            value={window}
            onChange={setWindow}
            options={WINDOWS.map((value) => ({ value, label: t(`windows.${value}`) }))}
          />
        }
      />
      <PageBody>
        <div className="grid gap-4">
          {report.isSuccess && data === null ? (
            <Alert tone="warning" title={t("unreachable")} />
          ) : null}

          <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {report.isPending ? (
              Array.from({ length: 4 }, (_, index) => (
                <Card key={index} className="p-4">
                  <Skeleton className="h-3 w-20" />
                  <Skeleton className="mt-3 h-6 w-16" />
                </Card>
              ))
            ) : (
              <>
                <Stat label={t("totals.tokens")} value={fmt(data?.total_tokens ?? 0)} />
                <Stat label={t("totals.turns")} value={fmt(data?.turns ?? 0)} />
                <Stat label={t("totals.calls")} value={fmt(data?.model_calls ?? 0)} />
                <Stat
                  label={t("totals.cacheHit")}
                  value={`${(data?.cache_hit_percent ?? 0).toFixed(0)}%`}
                />
              </>
            )}
          </section>

          <Card>
            <CardHeader
              title={t("chart.title")}
              description={t("chart.description")}
              actions={<BarChart3 className="size-4 text-fg-subtle" />}
            />
            <CardBody>
              {report.isPending ? (
                <div className="grid gap-1.5">
                  {Array.from({ length: 8 }, (_, index) => (
                    <Skeleton key={index} className="h-4" />
                  ))}
                </div>
              ) : (data?.buckets.length ?? 0) === 0 ? (
                <EmptyState size="sm" icon={<BarChart3 />} title={t("chart.empty")} />
              ) : (
                <div className="grid gap-1">
                  {(data?.buckets ?? []).map((bucket) => (
                    <Bar key={bucket.key} bucket={bucket} peak={peak} format={fmt} />
                  ))}
                </div>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader title={t("table.title")} description={t("table.description")} />
            <CardBody className="p-0">
              {(data?.buckets.length ?? 0) === 0 ? (
                <EmptyState size="sm" title={t("table.empty")} />
              ) : (
                <Table>
                  <THead>
                    <TR>
                      <TH>{t("table.bucket")}</TH>
                      <TH>{t("table.input")}</TH>
                      <TH>{t("table.output")}</TH>
                      <TH>{t("table.cached")}</TH>
                      <TH>{t("table.total")}</TH>
                      <TH>{t("table.turns")}</TH>
                    </TR>
                  </THead>
                  <TBody>
                    {(data?.buckets ?? []).map((bucket) => (
                      <TR key={bucket.key}>
                        <TD className="font-mono text-xs text-fg">{bucket.label}</TD>
                        <TD className="font-mono text-xs">{fmt(bucket.input_tokens)}</TD>
                        <TD className="font-mono text-xs">{fmt(bucket.output_tokens)}</TD>
                        <TD className="font-mono text-xs">{fmt(bucket.cache_read_tokens)}</TD>
                        <TD className="font-mono text-xs text-fg">{fmt(bucket.total_tokens)}</TD>
                        <TD className="font-mono text-xs">{fmt(bucket.turns)}</TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              )}
            </CardBody>
          </Card>
        </div>
      </PageBody>
    </>
  );
}

function Bar({
  bucket,
  peak,
  format,
}: {
  bucket: UsageBucket;
  peak: number;
  format: (value: number) => string;
}) {
  const width = Math.max(1, Math.round((bucket.total_tokens / peak) * 100));
  return (
    <div className="flex items-center gap-3">
      <span className="w-24 shrink-0 truncate font-mono text-2xs text-fg-subtle">
        {bucket.label}
      </span>
      <span className="relative h-3 flex-1 border border-line-subtle bg-sunken">
        <span
          className="absolute inset-y-0 left-0 bg-fg-muted"
          style={{ width: `${width}%` }}
        />
      </span>
      <span className="w-16 shrink-0 text-right font-mono text-2xs text-fg">
        {format(bucket.total_tokens)}
      </span>
    </div>
  );
}
