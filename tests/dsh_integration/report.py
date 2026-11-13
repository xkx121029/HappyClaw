"""Three-state check results shared by every smoke module."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Status(StrEnum):
    """Acceptance states; ``UNIMPLEMENTED`` is never treated as a pass."""

    PASS = "通过"
    FAIL = "失败"
    UNIMPLEMENTED = "未实现"


@dataclass(frozen=True)
class CheckResult:
    """One smoke check plus the evidence behind its status."""

    name: str
    status: Status
    detail: str = ""
    evidence: tuple[str, ...] = ()

    def render(self) -> list[str]:
        lines = [f"[{self.status.value}] {self.name}"]
        if self.detail:
            lines.append(f"    说明: {self.detail}")
        lines.extend(f"    - {item}" for item in self.evidence)
        return lines


@dataclass
class Report:
    """Collected results of one run."""

    results: list[CheckResult] = field(default_factory=list)

    def add(self, result: CheckResult) -> None:
        self.results.append(result)

    def counts(self) -> dict[Status, int]:
        counts = {status: 0 for status in Status}
        for result in self.results:
            counts[result.status] += 1
        return counts

    def exit_code(self) -> int:
        counts = self.counts()
        if counts[Status.FAIL]:
            return 1
        if counts[Status.UNIMPLEMENTED]:
            return 2
        return 0
