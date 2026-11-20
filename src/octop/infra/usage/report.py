"""Usage report service — query and present the ``usage_log`` ledger.

The router stays thin: it parses HTTP query params, asks
:class:`UsageReportService` for the summary or the Excel payload, and maps the
result to a response.  Scope resolution (``as_user``, agent existence), bucket
labeling (agent names, user display names), and xlsx assembly live here so the
same operations can be reused by CLI or cron without copying code.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from io import BytesIO
from typing import TYPE_CHECKING, Any, cast

from octop.i18n import tr
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.usage.xlsx import build_usage_xlsx
from octop.infra.utils.locale import normalize_locale

if TYPE_CHECKING:
    from octop.infra.db.repos.agents import AgentRepo
    from octop.infra.db.repos.usage import UsageRepo
    from octop.infra.users.manager import UserManager

_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_DAY_WINDOW_RE = re.compile(r"^day:(\d{4}-\d{2}-\d{2})$")
_MONTH_WINDOW_RE = re.compile(r"^month:(\d{4}-\d{2})$")
_RANGE_WINDOW_RE = re.compile(r"^range:(\d{4}-\d{2}-\d{2}):(\d{4}-\d{2}-\d{2})$")


class UsageReportService:
    """Query usage data and present it with human-readable labels."""

    def __init__(
        self,
        *,
        usage_repo: "UsageRepo",
        agent_repo: "AgentRepo",
        user_manager: "UserManager",
        agent_exists: Callable[[str], bool],
        timezone: str,
    ) -> None:
        self._usage_repo = usage_repo
        self._agent_repo = agent_repo
        self._user_manager = user_manager
        self._agent_exists = agent_exists
        self._timezone = timezone

    # -- scope ------------------------------------------------------------

    def assert_agent_exists(self, agent_id: str | None) -> None:
        if agent_id is None:
            return
        if not self._agent_exists(agent_id):
            raise OctopError(ErrorCode.AGENT_NOT_FOUND, f"agent {agent_id!r} not found")

    # -- summary ----------------------------------------------------------

    def summary(
        self,
        *,
        user_id: int | None,
        agent_id: str | None,
        window: str,
        granularity: str,
    ) -> dict[str, Any]:
        """Query the usage ledger and label agent/user buckets for display."""
        try:
            payload = cast(
                "dict[str, Any]",
                self._usage_repo.summary(
                    user_id=user_id,
                    agent_id=agent_id,
                    window=window,
                    granularity=granularity,
                    timezone=self._timezone,
                ),
            )
        except ValueError as exc:
            raise OctopError(ErrorCode.INTERNAL_ERROR, str(exc), status=400) from exc
        return self._present_summary(payload)

    # -- export -----------------------------------------------------------

    def export_xlsx(
        self,
        *,
        user_id: int | None,
        agent_id: str | None,
        window: str,
        locale: str,
    ) -> tuple[bytes, str]:
        """Return ``(xlsx_bytes, filename)`` for the given scope."""
        try:
            rows = self._usage_repo.list_detail(
                user_id=user_id,
                agent_id=agent_id,
                window=window,
                timezone=self._timezone,
            )
        except ValueError as exc:
            raise OctopError(ErrorCode.INTERNAL_ERROR, str(exc), status=400) from exc

        by_day = self._summary_buckets(user_id, agent_id, window, "by_day")
        by_agent = self._summary_buckets(user_id, agent_id, window, "by_agent")
        by_model = self._summary_buckets(user_id, agent_id, window, "by_model")

        payload = build_usage_xlsx(
            rows=rows,
            by_day=by_day,
            by_agent=by_agent,
            by_model=by_model,
            agent_names=self._agent_name_map(),
            usernames=self._username_map(),
            timezone=self._timezone,
            locale=locale,
        )
        filename = self._export_filename(window, locale=locale)
        return payload, filename

    # -- internal helpers -------------------------------------------------

    def _summary_buckets(
        self,
        user_id: int | None,
        agent_id: str | None,
        window: str,
        granularity: str,
    ) -> list[Any]:
        return self.summary(
            user_id=user_id,
            agent_id=agent_id,
            window=window,
            granularity=granularity,
        )["buckets"]

    def _agent_name_map(self) -> dict[str, str]:
        rows = self._agent_repo.list_all(include_disabled=True)
        return {str(row.agent_id): str(row.name or row.agent_id) for row in rows}

    def _username_map(self) -> dict[int, str]:
        out: dict[int, str] = {}
        for user in self._user_manager.list_all(include_disabled=True):
            uid = getattr(user, "id", None)
            if uid is None:
                continue
            name = getattr(user, "username", None) or getattr(user, "display_name", None) or ""
            out[int(uid)] = str(name)
        return out

    def _present_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._label_user_buckets(self._label_agent_buckets(payload))

    def _label_agent_buckets(self, payload: dict[str, Any]) -> dict[str, Any]:
        if str(payload.get("granularity") or "") != "by_agent":
            return payload
        names = self._agent_name_map()
        labeled: list[Any] = []
        for bucket in payload.get("buckets") or []:
            if not isinstance(bucket, dict):
                labeled.append(bucket)
                continue
            name = names.get(str(bucket.get("key") or ""), "").strip()
            if name:
                bucket = {**bucket, "label": name}
            labeled.append(bucket)
        return {**payload, "buckets": labeled}

    def _label_user_buckets(self, payload: dict[str, Any]) -> dict[str, Any]:
        if str(payload.get("granularity") or "") != "by_user":
            return payload
        names = self._user_chart_labels()
        labeled: list[Any] = []
        for bucket in payload.get("buckets") or []:
            if not isinstance(bucket, dict):
                labeled.append(bucket)
                continue
            raw_key = bucket.get("key")
            if isinstance(raw_key, bool) or not isinstance(raw_key, (int, str)):
                labeled.append(bucket)
                continue
            try:
                uid = int(raw_key)
            except ValueError:
                labeled.append(bucket)
                continue
            name = names.get(uid, "").strip()
            if name:
                bucket = {**bucket, "label": name}
            labeled.append(bucket)
        return {**payload, "buckets": labeled}

    def _user_chart_labels(self) -> dict[int, str]:
        rows: list[tuple[int, str, str]] = []
        for user in self._user_manager.list_all(include_disabled=True):
            uid = getattr(user, "id", None)
            if uid is None:
                continue
            username = str(getattr(user, "username", None) or uid).strip() or str(uid)
            display = getattr(user, "display_name", None)
            preferred = display.strip() if isinstance(display, str) and display.strip() else username
            rows.append((int(uid), preferred, username))
        counts: dict[str, int] = {}
        for _uid, preferred, _username in rows:
            counts[preferred] = counts.get(preferred, 0) + 1
        labels: dict[int, str] = {}
        for uid, preferred, username in rows:
            if counts[preferred] > 1 and preferred != username:
                labels[uid] = f"{preferred} ({username})"
            else:
                labels[uid] = preferred
        return labels

    def _export_filename(self, window: str, *, locale: str) -> str:
        prefix = tr("usage_export.filename_prefix", normalize_locale(locale))
        range_match = _RANGE_WINDOW_RE.fullmatch(window)
        if range_match is not None:
            period = f"{range_match.group(1)}-{range_match.group(2)}"
        else:
            day_match = _DAY_WINDOW_RE.fullmatch(window)
            if day_match is not None:
                period = day_match.group(1)
            else:
                month_match = _MONTH_WINDOW_RE.fullmatch(window)
                if month_match is not None:
                    period = month_match.group(1)
                else:
                    period = _SAFE_FILENAME_RE.sub("_", window).strip("._") or "usage"
        return f"{prefix}_{period}.xlsx"


__all__ = ["UsageReportService"]
