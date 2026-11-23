"""Batch scheduling for DSH tool calls.

Only calls whose ``isConcurrencySafe(arguments)`` returns exactly ``true`` run
in parallel; every other call is an exclusive barrier. Results settle in the
model's input order, and calls that never started (because the batch was
cancelled) still produce a paired ``tool/result`` with
``TOOL_ABORTED_BEFORE_DISPATCH``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from happyclaw.infra.plugins.bridge.contract_types import AbortSignal
from happyclaw.infra.plugins.bridge.pipeline import (
    ToolCall,
    ToolInvocation,
    ToolPipeline,
)


class ToolBatcher:
    """Runs a batch of calls with DSH concurrency rules."""

    def __init__(self, pipeline: ToolPipeline, *, max_parallel: int = 10) -> None:
        if max_parallel < 1:
            raise ValueError("max_parallel must be at least 1")
        self.pipeline = pipeline
        self.max_parallel = max_parallel

    async def execute(
        self,
        calls: Sequence[ToolCall],
        *,
        signal: AbortSignal | None = None,
    ) -> list[ToolInvocation]:
        if not calls:
            return []

        groups = self._group(calls)
        results: list[ToolInvocation | None] = [None] * len(calls)
        semaphore = asyncio.Semaphore(self.max_parallel)

        for parallel, indices in groups:
            if signal is not None and signal.is_set():
                for index in indices:
                    results[index] = self.pipeline.abort_before_dispatch(calls[index])
                continue

            if parallel and len(indices) > 1:

                async def run(index: int) -> ToolInvocation:
                    async with semaphore:
                        return await self.pipeline.invoke(calls[index], signal=signal)

                settled = await asyncio.gather(*(run(index) for index in indices))
                for index, invocation in zip(indices, settled, strict=True):
                    results[index] = invocation
            else:
                for index in indices:
                    results[index] = await self.pipeline.invoke(calls[index], signal=signal)

        return [invocation for invocation in results if invocation is not None]

    def _group(self, calls: Sequence[ToolCall]) -> list[tuple[bool, list[int]]]:
        groups: list[tuple[bool, list[int]]] = []
        for index, call in enumerate(calls):
            definition = self.pipeline.lookup(call.name)
            safe = definition is not None and definition.classify_concurrency(call.arguments)
            if safe and groups and groups[-1][0]:
                groups[-1][1].append(index)
            else:
                groups.append((safe, [index]))
        return groups


__all__ = ["ToolBatcher"]
