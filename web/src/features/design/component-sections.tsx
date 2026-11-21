import {
  ArrowRight,
  Copy,
  Inbox,
  MoreHorizontal,
  Plus,
  Search,
  Sparkles,
  Trash2,
} from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Alert } from "@/components/ui/alert";
import { Avatar } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardFooter, CardHeader, Stat } from "@/components/ui/card";
import { Checkbox, Switch } from "@/components/ui/checkbox";
import { Dialog } from "@/components/ui/dialog";
import { DropdownMenu } from "@/components/ui/dropdown-menu";
import { EmptyState } from "@/components/ui/empty-state";
import { Field, FieldGroup } from "@/components/ui/field";
import { Input, Textarea } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Segmented, Tabs } from "@/components/ui/tabs";
import { Select } from "@/components/ui/select";
import { Kbd, Separator } from "@/components/ui/separator";
import { SkeletonList, SkeletonText } from "@/components/ui/skeleton";
import { LoadingBlock, Spinner } from "@/components/ui/spinner";
import { TD, TH, TBody, THead, TR, Table } from "@/components/ui/table";
import { toast } from "@/lib/toast";
import { Tooltip } from "@/components/ui/tooltip";

import { Section, SubGrid } from "./section";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-2 md:grid-cols-[128px_1fr] md:items-center">
      <span className="font-mono text-2xs uppercase tracking-wide text-fg-subtle">
        {label}
      </span>
      <div className="flex flex-wrap items-center gap-2">{children}</div>
    </div>
  );
}

export function ComponentSection() {
  const { t } = useTranslation("design");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [tab, setTab] = useState("overview");
  const [view, setView] = useState<"list" | "grid">("list");
  const [checked, setChecked] = useState(true);
  const [enabled, setEnabled] = useState(true);
  const [selectValue, setSelectValue] = useState("fast");

  return (
    <Section
      id="components"
      title={t("sections.components")}
      description="Every component below is built on the tokens above, with no component library behind it."
    >
      <div className="grid gap-8">
        <div className="grid gap-3">
          <Row label="Button">
            <Button variant="primary">Primary</Button>
            <Button variant="secondary">Secondary</Button>
            <Button variant="ghost">Ghost</Button>
            <Button variant="subtle">Subtle</Button>
            <Button variant="danger" leadingIcon={<Trash2 />}>
              Danger
            </Button>
            <Button variant="link">Link</Button>
          </Row>
          <Row label="Button sizes">
            <Button size="xs">Extra small</Button>
            <Button size="sm">Small</Button>
            <Button size="md">Medium</Button>
            <Button size="lg">Large</Button>
            <Button variant="primary" size="icon" aria-label="Add">
              <Plus />
            </Button>
            <Button size="md" loading>
              Loading
            </Button>
            <Button variant="primary" trailingIcon={<ArrowRight />}>
              Continue
            </Button>
          </Row>
        </div>

        <Separator />

        <SubGrid title="Form controls" columns={3}>
          <Field label="Agent name" hint="Shown in the sidebar and chat header." required>
            <Input placeholder="Research helper" />
          </Field>
          <Field label="Search">
            <Input leadingIcon={<Search />} placeholder="Search threads" />
          </Field>
          <Field label="Model" error="Pick a model to continue.">
            <Select
              invalid
              value={selectValue}
              onChange={(event) => setSelectValue(event.target.value)}
              options={[
                { value: "fast", label: "Fast · minimal cost" },
                { value: "balanced", label: "Balanced" },
                { value: "deep", label: "Deep reasoning" },
              ]}
            />
          </Field>
          <Field label="Instructions" className="md:col-span-3" hint="Markdown supported.">
            <Textarea placeholder="You are a careful assistant…" />
          </Field>
        </SubGrid>

        <div className="flex flex-wrap items-center gap-6">
          <Checkbox
            checked={checked}
            onChange={(event) => setChecked(event.target.checked)}
            label="Stream responses"
            description="Show tokens as they arrive."
          />
          <Switch
            id="design-switch"
            checked={enabled}
            onCheckedChange={setEnabled}
            label="Auto-approve safe tools"
            description="Skip the pause for read-only tools."
          />
        </div>

        <Separator />

        <SubGrid title="Badges and avatars" columns={4}>
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge>Neutral</Badge>
            <Badge tone="accent" icon={<Sparkles />}>
              Accent
            </Badge>
            <Badge tone="success" dot>
              Running
            </Badge>
            <Badge tone="warning" dot>
              Pending
            </Badge>
            <Badge tone="danger" dot>
              Failed
            </Badge>
            <Badge tone="info">Info</Badge>
            <Badge tone="outline">Outline</Badge>
          </div>
          <div className="flex items-center gap-2">
            <Avatar name="Happy Claw" size="xs" />
            <Avatar name="Happy Claw" size="sm" />
            <Avatar name="Research Helper" size="md" />
            <Avatar name="Mia Chen" size="lg" />
          </div>
        </SubGrid>

        <div className="grid gap-3 md:grid-cols-3">
          <Stat label="Tokens today" value="128.4k" delta={{ value: "+12% vs yesterday", tone: "up" }} />
          <Stat label="Active threads" value="7" delta={{ value: "2 idle", tone: "flat" }} />
          <Stat label="Failed runs" value="0" delta={{ value: "last 24h", tone: "flat" }} />
        </div>

        <div className="grid gap-3 md:grid-cols-2">
          <Card>
            <CardHeader
              title="Card with actions"
              description="A surface with its own header and footer."
              actions={
                <DropdownMenu
                  trigger={
                    <Button variant="ghost" size="icon-sm" aria-label="More">
                      <MoreHorizontal />
                    </Button>
                  }
                  items={[
                    { key: "copy", label: "Copy id", icon: <Copy /> },
                    { key: "delete", label: "Delete", icon: <Trash2 />, danger: true, separated: true },
                  ]}
                />
              }
            />
            <CardBody className="grid gap-3 text-sm text-fg-muted">
              <p>
                Card bodies are the default container for settings rows, summaries
                and list panels.
              </p>
              <Progress value={62} label="Context usage" />
            </CardBody>
            <CardFooter>
              <Button size="sm" variant="ghost">
                Cancel
              </Button>
              <Button size="sm" variant="primary">
                Save
              </Button>
            </CardFooter>
          </Card>

          <Card>
            <CardHeader title="Tabs and segmented" description="Local navigation controls." />
            <CardBody className="grid gap-4">
              <Tabs
                ariaLabel="Example tabs"
                items={[
                  { value: "overview", label: "Overview" },
                  { value: "usage", label: "Usage", badge: <Badge tone="accent">new</Badge> },
                  { value: "danger", label: "Danger", disabled: true },
                ]}
                value={tab}
                onValueChange={setTab}
              />
              <Segmented
                ariaLabel="View mode"
                value={view}
                onChange={setView}
                options={[
                  { value: "list", label: "List" },
                  { value: "grid", label: "Grid" },
                ]}
              />
              <div className="flex items-center gap-2 text-xs text-fg-subtle">
                <Tooltip content="Open the palette">
                  <Button variant="secondary" size="sm">
                    Tooltip on hover
                  </Button>
                </Tooltip>
                <Kbd>⌘K</Kbd>
              </div>
            </CardBody>
          </Card>
        </div>

        <div className="grid gap-3 md:grid-cols-2">
          <Card>
            <CardHeader title="Table" description="Dense list rows with hover feedback." />
            <CardBody className="p-0">
              <Table>
                <THead>
                  <TR>
                    <TH>Thread</TH>
                    <TH>Agent</TH>
                    <TH>State</TH>
                    <TH>Updated</TH>
                  </TR>
                </THead>
                <TBody>
                  {[
                    ["Design review", "Happy Claw", "Running", "just now"],
                    ["Port gateway", "Helper", "Idle", "12m ago"],
                    ["README sync", "Docs agent", "Failed", "1h ago"],
                  ].map(([thread, agent, state, updated]) => (
                    <TR key={thread}>
                      <TD className="text-fg">{thread}</TD>
                      <TD>{agent}</TD>
                      <TD>
                        <Badge
                          tone={
                            state === "Running"
                              ? "success"
                              : state === "Failed"
                                ? "danger"
                                : "neutral"
                          }
                          dot
                        >
                          {state}
                        </Badge>
                      </TD>
                      <TD className="font-mono text-2xs">{updated}</TD>
                    </TR>
                  ))}
                </TBody>
              </Table>
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Feedback" description="Alerts, toasts and inline errors." />
            <CardBody className="grid gap-2">
              <Alert tone="info" title="Heads up">
                Info alerts carry a soft fill and an icon, never a border.
              </Alert>
              <Alert tone="success" title="Saved">
                Preferences were written to the local server.
              </Alert>
              <Alert tone="warning" title="Approaching the limit">
                92% of the context window is used.
              </Alert>
              <Alert
                tone="danger"
                title="Backend unreachable"
                action={
                  <Button size="xs" variant="secondary">
                    Retry
                  </Button>
                }
              >
                The request never reached the server.
              </Alert>
              <div className="flex gap-2 pt-1">
                <Button size="sm" onClick={() => toast.info("Info toast")}>
                  Info toast
                </Button>
                <Button size="sm" onClick={() => toast.success("Saved", "Preference updated.")}>
                  Success toast
                </Button>
                <Button size="sm" onClick={() => toast.error("Failed", "HTTP 500")}>
                  Error toast
                </Button>
              </div>
            </CardBody>
          </Card>
        </div>

        <div className="grid gap-3 md:grid-cols-3">
          <Card>
            <CardHeader title="Skeleton" description="Shape of the content to come." />
            <CardBody className="grid gap-3">
              <SkeletonText lines={3} />
              <SkeletonList rows={2} />
            </CardBody>
          </Card>
          <Card>
            <CardHeader title="Loading" description="Inline and block spinners." />
            <CardBody className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-xs text-fg-subtle">
                <Spinner size="xs" /> xs
                <Spinner size="sm" /> sm
                <Spinner size="md" /> md
              </div>
              <LoadingBlock label="Loading…" className="min-h-20" />
            </CardBody>
          </Card>
          <Card>
            <CardHeader title="Empty" description="The one empty state." />
            <CardBody>
              <EmptyState
                size="sm"
                icon={<Inbox />}
                title="No conversations"
                description="Start one to begin."
                action={<Button size="xs" variant="primary">New</Button>}
              />
            </CardBody>
          </Card>
        </div>

        <FieldGroup
          title="Dialogs"
          description="Native <dialog>, so focus containment and Escape come from the platform."
        >
          <div>
            <Button variant="secondary" onClick={() => setDialogOpen(true)}>
              Open dialog
            </Button>
            <Dialog
              open={dialogOpen}
              onOpenChange={setDialogOpen}
              title="Delete conversation?"
              description="This removes the thread and its messages."
              size="sm"
              footer={
                <>
                  <Button size="sm" variant="ghost" onClick={() => setDialogOpen(false)}>
                    Cancel
                  </Button>
                  <Button
                    size="sm"
                    variant="danger"
                    onClick={() => {
                      setDialogOpen(false);
                      toast.success("Conversation deleted");
                    }}
                  >
                    Delete
                  </Button>
                </>
              }
            >
              <p className="text-sm text-fg-muted">
                Files in the workspace are kept. This action cannot be undone.
              </p>
            </Dialog>
          </div>
        </FieldGroup>
      </div>
    </Section>
  );
}
