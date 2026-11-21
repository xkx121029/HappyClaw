import { Link, createFileRoute } from "@tanstack/react-router";

import { directionMeta } from "@/directions/meta";

export const Route = createFileRoute("/directions/")({
  component: DirectionsIndex,
});

const ids = ["a", "b", "c"] as const;
const pages = [
  { id: "chat", label: "会话页" },
  { id: "design", label: "设计系统页" },
] as const;

function DirectionsIndex() {
  return (
    <div className="min-h-dvh bg-neutral-950 p-6 text-neutral-100">
      <div className="mx-auto max-w-3xl">
        <p className="font-mono text-xs tracking-widest text-neutral-500">HAPPYCLAW · FRONTEND</p>
        <h1 className="mt-2 text-2xl font-semibold">三个视觉方向 · 对照入口</h1>
        <p className="mt-2 text-sm leading-relaxed text-neutral-400">
          每方向两页，深浅两套。截图在
          <code className="mx-1 font-mono text-neutral-300">renders/HAPA-20/</code>
          。先看，再选。
        </p>

        <div className="mt-8 grid gap-4">
          {ids.map((id) => {
            const meta = directionMeta[id];
            return (
              <section key={id} className="rounded-xl border border-neutral-800 bg-neutral-900 p-4">
                <h2 className="text-base font-semibold">{meta.name}</h2>
                <p className="mt-0.5 text-sm text-neutral-300">{meta.subtitle}</p>
                <p className="mt-1 text-xs leading-relaxed text-neutral-500">{meta.note}</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  {pages.map((page) => (
                    <Link
                      key={page.id}
                      to="/directions/$dir/$page"
                      params={{ dir: id, page: page.id }}
                      className="rounded-md border border-neutral-700 px-3 py-1.5 text-xs text-neutral-200 hover:border-neutral-500 hover:bg-neutral-800"
                    >
                      {meta.name.slice(0, 5)} · {page.label}
                    </Link>
                  ))}
                </div>
              </section>
            );
          })}
        </div>
      </div>
    </div>
  );
}
