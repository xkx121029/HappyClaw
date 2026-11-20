"""RPC framing tests: host->runner requests, runner->host requests, failures."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from octop.infra.dsh.compat.errors import DshCompatCode, DshCompatError
from octop.infra.dsh.compat.transport import NodeRpcClient

RUNNER = textwrap.dedent(
    """
    import json
    import sys

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        message = json.loads(line)
        if message.get("rpc"):
            # answer to *our* host request, not a new request
            print(json.dumps({"id": 999, "ok": True, "result": "late"}), flush=True)
            continue
        method = message.get("method")
        request_id = message.get("id")
        if method == "mount":
            print(json.dumps({"rpc": True, "id": 700, "method": "tools.register",
                              "params": {"name": "demo"}}), flush=True)
            answer = json.loads(sys.stdin.readline())
            print(json.dumps({"id": request_id, "ok": True,
                              "result": {"host_answer": answer.get("result")}}), flush=True)
        elif method == "fail":
            print(json.dumps({"id": request_id, "ok": False,
                              "error": {"code": "DSH_RUNTIME_THROW", "message": "boom"}}), flush=True)
        elif method == "hang":
            continue
        elif method == "die":
            break
        else:
            print(json.dumps({"id": request_id, "ok": True, "result": method}), flush=True)
    """
)


def _client(tmp_path: Path, **kwargs: object) -> NodeRpcClient:
    runner = tmp_path / "fake_runner.py"
    runner.write_text(RUNNER, encoding="utf-8")
    client = NodeRpcClient(
        node=sys.executable,
        runner=runner,
        plugin_id="dsh:fake",
        cwd=tmp_path,
        **kwargs,
    )
    client.start()
    client.wait_ready()
    return client


def test_runner_request_is_answered_without_corrupting_the_host_call(tmp_path: Path) -> None:
    seen: list[tuple[str, dict]] = []

    def handler(method: str, params: dict) -> dict:
        seen.append((method, dict(params)))
        return {"registered": params.get("name")}

    client = _client(tmp_path, on_host_request=handler)
    try:
        result = client.request("mount", {"entry": "x"}, timeout=10)
    finally:
        client.close()

    assert seen == [("tools.register", {"name": "demo"})]
    assert result == {"host_answer": {"registered": "demo"}}


def test_plain_request_roundtrip(tmp_path: Path) -> None:
    client = _client(tmp_path)
    try:
        assert client.request("ping", {}, timeout=10) == "ping"
    finally:
        client.close()


def test_runner_failure_surfaces_the_code(tmp_path: Path) -> None:
    client = _client(tmp_path)
    try:
        with pytest.raises(DshCompatError) as excinfo:
            client.request("fail", {}, timeout=10)
    finally:
        client.close()
    assert excinfo.value.code == DshCompatCode.RUNTIME_THROW
    assert excinfo.value.message == "boom"


def test_timeout_is_reported_not_hung(tmp_path: Path) -> None:
    client = _client(tmp_path)
    try:
        with pytest.raises(DshCompatError) as excinfo:
            client.request("hang", {}, timeout=0.4)
    finally:
        client.close()
    assert excinfo.value.code == DshCompatCode.TIMEOUT


def test_process_exit_is_visible_immediately(tmp_path: Path) -> None:
    client = _client(tmp_path)
    try:
        with pytest.raises(DshCompatError) as excinfo:
            client.request("die", {}, timeout=5)
    finally:
        client.close()
    assert excinfo.value.code == DshCompatCode.PROCESS_EXIT
    assert client.alive is False
