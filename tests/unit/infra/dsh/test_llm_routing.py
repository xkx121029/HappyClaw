"""S8 routing: per-ref switches, fallback isolation, and the minimal live link."""

from __future__ import annotations

import copy
import logging
from typing import Any

import pytest
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from happyclaw_harness.config import ModelConfig, ProviderConfig
from happyclaw_harness.llm.factory import ChatModelFactory
from happyclaw_harness.manager import HarnessAgentManager

from octop.infra.dsh.llm import factory as factory_module
from octop.infra.dsh.llm.factory import DshModelFactory, install_dsh_model_factory
from octop.infra.dsh.llm.langchain_model import (
    REQUIRED_HARNESS_VERSION,
    DshChatModel,
    DshModelError,
    harness_version_warning,
)

STREAM_CHUNKS: list[dict[str, Any]] = [
    {
        "id": "chatcmpl-link",
        "object": "chat.completion.chunk",
        "model": "m",
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant", "reasoning_content": "thi"},
                "finish_reason": None,
            }
        ],
    },
    {
        "choices": [
            {
                "index": 0,
                "delta": {"reasoning_content": "nk", "content": "hel"},
                "finish_reason": None,
            }
        ]
    },
    {"choices": [{"index": 0, "delta": {"content": "lo"}, "finish_reason": None}]},
    {
        "choices": [
            {
                "index": 0,
                "delta": {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "search", "arguments": '{"q":'},
                        }
                    ]
                },
                "finish_reason": None,
            }
        ]
    },
    {
        "choices": [
            {
                "index": 0,
                "delta": {
                    "tool_calls": [{"index": 0, "function": {"arguments": '"x"}'}}]
                },
                "finish_reason": "tool_calls",
            }
        ],
        "model": "m",
    },
    {
        "choices": [],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "prompt_tokens_details": {"cached_tokens": 3},
            "completion_tokens_details": {"reasoning_tokens": 2},
        },
    },
]


class _ScriptedStream:
    def __init__(self, chunks: list[dict[str, Any]]) -> None:
        self._chunks = chunks

    def __aiter__(self):
        async def generate():
            for chunk in self._chunks:
                yield copy.deepcopy(chunk)

        return generate()

    async def aclose(self) -> None:
        return None


class ScriptedTransport:
    def __init__(self, chunks: list[dict[str, Any]]) -> None:
        self.chunks = chunks
        self.requests: list[dict[str, Any]] = []

    def stream(self, request):
        self.requests.append(copy.deepcopy(dict(request)))
        return _ScriptedStream(self.chunks)


class _FakeManager:
    def __init__(self, factory: ChatModelFactory | None) -> None:
        self._shared_factory = factory


class _ReadOnlyManager:
    """Exposes the attribute but rejects assignment, like a read-only property."""

    def __init__(self, factory: ChatModelFactory) -> None:
        self.__factory = factory

    @property
    def _shared_factory(self) -> ChatModelFactory:
        return self.__factory


def _providers() -> list[ProviderConfig]:
    return [
        ProviderConfig(
            id="p",
            base_url="https://example.invalid/v1",
            api_key="k",
            models=[ModelConfig(id="m"), ModelConfig(id="other")],
        )
    ]


def _enable(monkeypatch: pytest.MonkeyPatch, refs: str = "p/m") -> None:
    monkeypatch.setenv("OCTOP_DSH_RUNTIME", "1")
    monkeypatch.setenv("OCTOP_DSH_LLM", "1")
    monkeypatch.setenv("OCTOP_DSH_LLM_REFS", refs)


def _transport_factory(created: list[ScriptedTransport] | None = None):
    def build(_provider: Any, _model: Any) -> ScriptedTransport:
        transport = ScriptedTransport(STREAM_CHUNKS)
        if created is not None:
            created.append(transport)
        return transport

    return build


def test_install_is_a_noop_when_switch_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OCTOP_DSH_RUNTIME", raising=False)
    monkeypatch.delenv("OCTOP_DSH_LLM", raising=False)
    manager = _FakeManager(ChatModelFactory(_providers()))
    original = manager._shared_factory

    result = install_dsh_model_factory(manager, transport_factory=_transport_factory())

    assert result.applied is False
    assert "off" in result.reason
    assert manager._shared_factory is original


def test_only_allow_listed_ref_uses_the_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable(monkeypatch, refs="p/m")
    manager = _FakeManager(ChatModelFactory(_providers()))
    original = manager._shared_factory

    result = install_dsh_model_factory(manager, transport_factory=_transport_factory())

    assert result.applied is True
    assert isinstance(manager._shared_factory, DshModelFactory)
    assert isinstance(manager._shared_factory.get_chat_model("p/m"), DshChatModel)
    sibling = manager._shared_factory.get_chat_model("p/other")
    assert not isinstance(sibling, DshChatModel)
    assert isinstance(sibling, ChatOpenAI)
    # Provider index is shared by reference so add_provider/remove_provider work.
    assert manager._shared_factory._providers is original._providers


def test_one_broken_ref_falls_back_without_affecting_siblings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable(monkeypatch, refs="p/m,p/other")
    manager = _FakeManager(ChatModelFactory(_providers()))

    def transport_factory(provider: ProviderConfig, model: ModelConfig) -> Any:
        if model.id == "m":
            return None
        return ScriptedTransport(STREAM_CHUNKS)

    result = install_dsh_model_factory(manager, transport_factory=transport_factory)

    assert result.applied is True
    broken = manager._shared_factory.get_chat_model("p/m")
    healthy = manager._shared_factory.get_chat_model("p/other")
    assert not isinstance(broken, DshChatModel)
    assert isinstance(broken, ChatOpenAI)
    assert isinstance(healthy, DshChatModel)
    # Calling the broken ref again keeps falling back instead of raising.
    assert isinstance(manager._shared_factory.get_chat_model("p/m"), ChatOpenAI)


def test_unsupported_protocol_is_rejected_before_touching_the_harness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable(monkeypatch, refs="p/m")
    providers = [
        ProviderConfig(
            id="p",
            base_url="https://example.invalid/v1",
            api_key="k",
            protocol="bedrock",
            models=[ModelConfig(id="m")],
        )
    ]
    manager = _FakeManager(ChatModelFactory(providers))
    wrapper = DshModelFactory(
        manager._shared_factory, refs={"p/m"}, transport_factory=_transport_factory()
    )

    with pytest.raises(DshModelError, match="no DSH adapter"):
        wrapper._build_dsh("p/m", max_retries=None)


def test_missing_shared_factory_attribute_is_reported_and_preserves_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable(monkeypatch)

    class _NoSeam:
        pass

    manager = _NoSeam()
    result = install_dsh_model_factory(manager, transport_factory=_transport_factory())

    assert result.applied is False
    assert "cannot read" in result.reason
    assert not hasattr(manager, "_shared_factory")


def test_wrong_shared_factory_type_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable(monkeypatch)
    manager = _FakeManager(object())  # type: ignore[arg-type]
    original = manager._shared_factory

    result = install_dsh_model_factory(manager, transport_factory=_transport_factory())

    assert result.applied is False
    assert "expected ChatModelFactory" in result.reason
    assert manager._shared_factory is original


def test_read_only_shared_factory_keeps_original(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable(monkeypatch)
    factory = ChatModelFactory(_providers())
    manager = _ReadOnlyManager(factory)

    result = install_dsh_model_factory(manager, transport_factory=_transport_factory())

    assert result.applied is False
    assert manager._shared_factory is factory


def test_turning_the_llm_switch_off_rolls_back_per_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable(monkeypatch, refs="p/m")
    manager = _FakeManager(ChatModelFactory(_providers()))
    install_dsh_model_factory(manager, transport_factory=_transport_factory())
    wrapper = manager._shared_factory
    assert isinstance(wrapper.get_chat_model("p/m"), DshChatModel)

    monkeypatch.delenv("OCTOP_DSH_LLM", raising=False)

    assert isinstance(wrapper.get_chat_model("p/m"), ChatOpenAI)


def test_version_mismatch_warns_and_is_reported(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    assert harness_version_warning() is None  # installed harness is the verified one
    monkeypatch.setattr("octop.infra.dsh.llm.langchain_model.version", lambda _name: "9.9.9")
    warning = harness_version_warning()
    assert warning is not None and "9.9.9" in warning and REQUIRED_HARNESS_VERSION in warning

    _enable(monkeypatch)
    monkeypatch.setattr(factory_module, "harness_version_warning", lambda: warning)
    manager = _FakeManager(ChatModelFactory(_providers()))
    with caplog.at_level(logging.WARNING):
        result = install_dsh_model_factory(manager, transport_factory=_transport_factory())

    assert result.applied is True
    assert result.version_warning == warning
    assert any("9.9.9" in record.message for record in caplog.records)


async def test_minimal_live_link_streams_one_fixture_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable(monkeypatch, refs="p/m")
    manager = HarnessAgentManager(_providers(), file_logging=False)
    created: list[ScriptedTransport] = []

    result = install_dsh_model_factory(
        manager, transport_factory=_transport_factory(created)
    )

    assert result.applied is True
    model = manager.shared_factory.get_chat_model("p/m")
    assert isinstance(model, DshChatModel)

    chunks = [chunk async for chunk in model._astream([HumanMessage(content="hi")])]

    assert "".join(str(chunk.message.content) for chunk in chunks) == "hello"
    assert (
        "".join(
            str((chunk.message.additional_kwargs or {}).get("reasoning_content", ""))
            for chunk in chunks
        )
        == "think"
    )
    tool_chunks = [entry for chunk in chunks for entry in (chunk.message.tool_call_chunks or ())]
    assert tool_chunks[0] == {
        "name": "search",
        "args": '{"q":',
        "id": "call_1",
        "index": 0,
        "type": "tool_call_chunk",
    }
    assert tool_chunks[1] == {
        "name": None,
        "args": '"x"}',
        "id": None,
        "index": 0,
        "type": "tool_call_chunk",
    }
    usage = [chunk.message.usage_metadata for chunk in chunks if chunk.message.usage_metadata]
    assert usage == [
        {
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
            "input_token_details": {"cache_read": 3},
            "output_token_details": {"reasoning": 2},
        }
    ]
    finishes = [
        chunk.generation_info["finish_reason"]
        for chunk in chunks
        if chunk.generation_info and "finish_reason" in chunk.generation_info
    ]
    assert finishes == ["tool_calls"]

    # Public LangChain streaming surface also works (message chunks only).
    public = [chunk async for chunk in model.astream([HumanMessage(content="hi")])]
    assert "".join(str(chunk.content) for chunk in public) == "hello"
    assert any(chunk.usage_metadata for chunk in public)

    # Complete requests really went through the adapter, no network.
    assert len(created) == 1
    assert len(created[0].requests) == 2
    payload = created[0].requests[0]
    assert payload["model"] == "m"
    assert payload["stream"] is True
    assert payload["messages"] == [{"role": "user", "content": "hi"}]
