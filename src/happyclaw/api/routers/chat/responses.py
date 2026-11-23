"""Response contracts for the dashboard chat REST surface.

Handlers in this package build their payloads as plain dicts. The models below
pin that JSON down so the generated OpenAPI (and clients built from it) see real
types instead of ``additionalProperties: true``.

:class:`PayloadOut` keeps the wire payload byte-identical to what the handler
returned: a field the payload did not carry is left out of the response instead
of being materialised as ``null``. Models also allow unknown fields to pass
through, so adding a payload key never turns into a 500 or a silently dropped
field until the model is updated.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    JsonValue,
    SerializerFunctionWrapHandler,
    model_serializer,
)


class PayloadOut(BaseModel):
    """Base for payload mirrors: open to extra keys, silent about absent ones."""

    model_config = ConfigDict(extra="allow")
    #: Published schema admits unknown keys (provider/variant payloads).
    payload_schema_open: ClassVar[bool] = False

    @model_serializer(mode="wrap")
    def _drop_unset(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data = handler(self)
        if not isinstance(data, dict):  # pragma: no cover - always a dict for models
            return dict(data)
        fields = type(self).model_fields
        return {k: v for k, v in data.items() if k not in fields or k in self.model_fields_set}


class HitlPolicyOut(PayloadOut):
    """Per-thread tool-approval bypass (``ask`` / ``allow_all`` / ``allow_tools``)."""

    mode: Literal["ask", "allow_all", "allow_tools"] = "ask"
    tools: list[str] | None = None


class ThreadArtifactRefOut(PayloadOut):
    path: str
    agent_id: str | None = None


class ThreadSummaryOut(PayloadOut):
    """One sidebar row from ``GET /agents/{agent_id}/threads``."""

    thread_id: str
    title: str
    channel_type: str
    session_key: str
    last_active: int
    created_at: int
    is_active: bool
    has_messages: bool
    pinned: bool
    unread_count: int
    contributed: bool
    owned: bool
    model_ref: str | None = None
    reasoning_mode: str | None = None
    reasoning_effort: str | None = None
    conversation_mode: str
    pending_plan_path: str | None = None
    hitl_policy: HitlPolicyOut
    turn_active: bool
    awaiting_user: bool
    artifacts: list[str]
    artifact_refs: list[ThreadArtifactRefOut]


class ThreadCreatedOut(PayloadOut):
    thread_id: str
    session_key: str


class ThreadUpdatedOut(PayloadOut):
    """Result of ``PATCH /agents/{agent_id}/threads/{thread_id}``."""

    thread_id: str
    title: str | None = None
    pinned: bool
    contributed: bool
    owned: bool
    model_ref: str | None = None
    reasoning_mode: str | None = None
    reasoning_effort: str | None = None
    conversation_mode: str
    pending_plan_path: str | None = None
    hitl_policy: HitlPolicyOut


class ThreadDeletedOut(PayloadOut):
    """Body of the ``compact`` delete branch (status 200, not the default 204)."""

    compacted: bool
    scheduled: bool


class ThreadTurnCancelledOut(PayloadOut):
    thread_id: str
    cancelled: bool


class ThreadForkOut(PayloadOut):
    thread_id: str
    session_key: str
    source_thread_id: str
    copied_messages: int
    title: str | None = None
    last_active: int
    created_at: int


class SessionReboundOut(PayloadOut):
    session_key: str
    thread_id: str


class ContextUsageSegmentOut(PayloadOut):
    key: str
    tokens: int


class ThreadContextUsageOut(PayloadOut):
    max_tokens: int
    used_tokens: int
    decision_saved: int
    segments: list[ContextUsageSegmentOut]


class HistoryMigrationStatusOut(PayloadOut):
    remaining: int
    pending: int
    queued: int
    running: int
    failed: int
    processing: bool
    agent_busy: bool
    can_start: bool


class HistoryMigrationStartOut(HistoryMigrationStatusOut):
    accepted: int


class HitlActionRequestOut(PayloadOut):
    name: str
    description: str | None = None


class HitlPendingItemOut(PayloadOut):
    """One card in the Home approval inbox."""

    pendingId: str
    agentId: str
    threadId: str
    sessionTitle: str | None = None
    createdAtMs: int
    kind: Literal["question", "approval"]
    questions: list[dict[str, JsonValue]]
    actionRequests: list[HitlActionRequestOut]


class HitlPendingListOut(PayloadOut):
    ok: bool
    items: list[HitlPendingItemOut]


class LocalizedTextOut(PayloadOut):
    zh: str
    en: str


class ChatQuickPromptOut(PayloadOut):
    title: LocalizedTextOut
    description: LocalizedTextOut
    prompt: LocalizedTextOut
    color: str
    icon_name: str | None = None
    # Team rooms stamp the member that contributed the card.
    expert: str | None = None
    agent_id: str | None = None


class ChatWelcomeOut(PayloadOut):
    welcome_message: LocalizedTextOut
    quick_prompts: list[ChatQuickPromptOut]
    task_examples: dict[str, list[str]] | None = None


class ChatPolishOut(PayloadOut):
    text: str


class ChatContentBlockOut(PayloadOut):
    """One content block of a history message.

    ``text`` / ``thinking`` / ``tool_use`` / ``tool_result`` are the blocks this
    backend writes; any other provider block (``image``, ``cache_control``, …) is
    passed through untouched, so the declared fields are all optional.
    """

    payload_schema_open: ClassVar[bool] = True

    type: str | None = None
    text: str | None = None
    thinking: str | None = None
    id: str | None = None
    name: str | None = None
    input: JsonValue | None = None
    output: str | None = None
    artifact: JsonValue | None = None
    error_code: str | None = None


class ChatAuthorOut(PayloadOut):
    """Who sent a user turn in a shared conversation."""

    user_id: int
    display_name: str
    username: str
    avatar_icon: str | None = None
    avatar_url: str | None = None


class ChatMessageOut(PayloadOut):
    """One projected history message (see ``chat/serialize.py``)."""

    payload_schema_open: ClassVar[bool] = True

    role: str
    content: list[ChatContentBlockOut]
    id: str | None = None
    usage: dict[str, JsonValue] | None = None
    composer_context: dict[str, JsonValue] | None = None
    inbound_attachments: list[dict[str, JsonValue]] | None = None
    author_user_id: int | None = None
    author: ChatAuthorOut | None = None
    status: str | None = None
    error_code: str | None = None
    agent_id: str | None = None
    team_wrapup: bool | None = None
    decision: dict[str, JsonValue] | None = None
    edited_files: list[str] | None = None
    duration_ms: int | None = None
    timestamp: int | None = None


class HitlPendingOut(PayloadOut):
    """The approval card a paused thread is waiting on."""

    pending_id: str
    action_requests: list[dict[str, JsonValue]]
    review_configs: list[dict[str, JsonValue]] | None = None


class ThreadHistoryOut(PayloadOut):
    """``GET /agents/{agent_id}/threads/{thread_id}/history``.

    Paging is offset based (``limit``/``offset``/``has_more``). ``next_cursor``
    is reserved for cursor paging and is always ``null`` today.
    """

    thread_id: str
    messages: list[ChatMessageOut]
    has_more: bool
    limit: int
    offset: int
    next_cursor: str | None = None
    history_loading: bool
    history_status: str
    history_retry_after_ms: int
    turn_active: bool
    hitl_pending: HitlPendingOut | None = None
    artifacts: list[str]
    artifact_refs: list[ThreadArtifactRefOut]
    conversation_mode: str
    pending_plan_path: str | None = None
    hitl_policy: HitlPolicyOut


RESPONSE_MODELS: tuple[type[PayloadOut], ...] = (
    HitlPolicyOut,
    ThreadArtifactRefOut,
    ThreadSummaryOut,
    ThreadCreatedOut,
    ThreadUpdatedOut,
    ThreadDeletedOut,
    ThreadTurnCancelledOut,
    ThreadForkOut,
    SessionReboundOut,
    ContextUsageSegmentOut,
    ThreadContextUsageOut,
    HistoryMigrationStatusOut,
    HistoryMigrationStartOut,
    HitlActionRequestOut,
    HitlPendingItemOut,
    HitlPendingListOut,
    LocalizedTextOut,
    ChatQuickPromptOut,
    ChatWelcomeOut,
    ChatPolishOut,
    ChatContentBlockOut,
    ChatAuthorOut,
    ChatMessageOut,
    HitlPendingOut,
    ThreadHistoryOut,
)


def model_schemas(
    models: tuple[type[PayloadOut], ...], *, open_schema: bool = False
) -> dict[str, Any]:
    """Component schemas for payload mirrors, nested models included.

    FastAPI renders response schemas in serialization mode; :meth:`PayloadOut._drop_unset`
    is a wrap serializer, which collapses each model to a bare ``object`` there. The
    field schema is the honest contract, so the OpenAPI pass publishes these instead.
    Models that admit unknown keys (provider blocks, protocol frames) keep
    ``additionalProperties: true``; the rest publish as closed objects.
    """
    schemas: dict[str, Any] = {}
    nested: dict[str, Any] = {}
    for model in models:
        schema = model.model_json_schema(ref_template="#/components/schemas/{model}")
        nested.update(schema.pop("$defs", {}))
        if not (open_schema or model.payload_schema_open):
            schema["additionalProperties"] = False
        schemas[model.__name__] = schema
    for name, definition in nested.items():
        schemas.setdefault(name, definition)
    if schemas.get("JsonValue") == {}:
        schemas["JsonValue"] = {
            "title": "JsonValue",
            "description": "Any JSON value (object, array, string, number, boolean, or null).",
        }
    return schemas


__all__ = [
    "ChatAuthorOut",
    "ChatContentBlockOut",
    "ChatMessageOut",
    "ChatPolishOut",
    "ChatQuickPromptOut",
    "ChatWelcomeOut",
    "ContextUsageSegmentOut",
    "HistoryMigrationStartOut",
    "HistoryMigrationStatusOut",
    "HitlActionRequestOut",
    "HitlPendingItemOut",
    "HitlPendingListOut",
    "HitlPendingOut",
    "HitlPolicyOut",
    "LocalizedTextOut",
    "SessionReboundOut",
    "ThreadArtifactRefOut",
    "ThreadContextUsageOut",
    "ThreadCreatedOut",
    "ThreadDeletedOut",
    "ThreadForkOut",
    "ThreadHistoryOut",
    "ThreadSummaryOut",
    "ThreadTurnCancelledOut",
    "ThreadUpdatedOut",
    "model_schemas",
]
