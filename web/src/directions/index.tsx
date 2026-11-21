import { ChatDirectionA, DesignDirectionA } from "@/directions/dir-a";
import { ChatDirectionB, DesignDirectionB } from "@/directions/dir-b";
import { ChatDirectionC, DesignDirectionC } from "@/directions/dir-c";
import type { DirectionId, DirectionPageId } from "@/directions/scope";

const pages: Record<
  DirectionId,
  Record<DirectionPageId, () => React.ReactElement>
> = {
  a: { chat: ChatDirectionA, design: DesignDirectionA },
  b: { chat: ChatDirectionB, design: DesignDirectionB },
  c: { chat: ChatDirectionC, design: DesignDirectionC },
};

export function DirectionPage({
  dir,
  page,
}: {
  dir: DirectionId;
  page: DirectionPageId;
}) {
  const Page = pages[dir][page];
  return <Page />;
}
