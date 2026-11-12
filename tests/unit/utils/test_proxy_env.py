"""Loopback hosts must bypass the system proxy (Ollama / LM Studio / mock)."""

from __future__ import annotations

from octop.infra.utils.proxy_env import LOOPBACK_HOSTS, skip_loopback_proxy


def test_loopback_hosts_are_added_to_empty_no_proxy() -> None:
    env: dict[str, str] = {}

    out = skip_loopback_proxy(env)

    assert out["NO_PROXY"].split(",") == list(LOOPBACK_HOSTS)
    assert out["no_proxy"] == out["NO_PROXY"]


def test_existing_no_proxy_entries_are_preserved() -> None:
    env = {"NO_PROXY": "example.com, 10.0.0.0/8", "no_proxy": "example.com"}

    out = skip_loopback_proxy(env)

    no_proxy = out["NO_PROXY"].split(",")
    assert no_proxy[0] == "example.com"
    assert no_proxy[1] == "10.0.0.0/8"
    for host in LOOPBACK_HOSTS:
        assert host in no_proxy
    # The lowercase mirror gets the same treatment.
    assert "localhost" in out["no_proxy"].split(",")


def test_merge_is_idempotent() -> None:
    env = {"NO_PROXY": "127.0.0.1,localhost,::1"}

    skip_loopback_proxy(env)
    first = env["NO_PROXY"]
    skip_loopback_proxy(env)

    assert env["NO_PROXY"] == first


def test_does_not_touch_proxy_variables() -> None:
    env = {
        "HTTP_PROXY": "http://127.0.0.1:7890",
        "HTTPS_PROXY": "http://127.0.0.1:7890",
    }

    out = skip_loopback_proxy(env)

    assert out["HTTP_PROXY"] == "http://127.0.0.1:7890"
    assert out["HTTPS_PROXY"] == "http://127.0.0.1:7890"
