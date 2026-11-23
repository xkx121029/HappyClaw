"""Offline profile tests over real adapter-discovered envelopes.

Every envelope here comes from ``HappyclawPluginLoader().discover`` reading the
fixture plugins under ``tests/fixtures/plugins/profile``: one plugin requires
another, one requires a version that is absent, and one declares no permissions.
No envelope is hand-built in this module.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from happyclaw.infra.plugins.market.pipeline import MarketplaceIndex, uninstall
from happyclaw.infra.plugins.market.sources.octop import HappyclawSource
from happyclaw.infra.plugins.profile import (
    LoadMode,
    MarketInstallSource,
    PluginStatus,
    Profile,
    ProfileEntry,
    ProfileRuntime,
    ProfileStore,
)
from happyclaw.infra.plugins.runtime.contract import (
    ActivationContext,
    InvalidManifestError,
    MissingDependencyError,
    PermissionKind,
    PluginEnvelope,
    PluginErrorCode,
    PluginHandle,
    PluginKind,
    PluginLoadError,
    PluginRequirement,
    VersionConflictError,
)
from happyclaw.infra.plugins.runtime.octop_plugin import HappyclawPluginLoader

_REPO_ROOT = Path(__file__).resolve().parents[4]
_PROFILE_FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "plugins" / "profile"

BASE = "octop:profile-base"
DEPENDENT = "octop:profile-dependent"
CONFLICT = "octop:profile-conflict"
ORPHAN = "octop:profile-orphan"
BARE = "octop:profile-bare"


class FakeClock:
    """Deterministic millisecond clock advanced by the loader wrapper."""

    def __init__(self) -> None:
        self._ms = 0.0

    def now(self) -> float:
        return self._ms / 1000.0

    def advance(self, milliseconds: float) -> None:
        self._ms += milliseconds


class CostedLoader:
    """Real Octop loader wrapper that records calls and simulates load cost.

    Discovery and activation semantics stay in ``HappyclawPluginLoader``; only the
    timing source and the failure injection are test-controlled.
    """

    kind = PluginKind.OCTOP

    def __init__(
        self,
        inner: HappyclawPluginLoader,
        clock: FakeClock,
        *,
        costs: Mapping[str, float] | None = None,
        failing: frozenset[str] = frozenset(),
    ) -> None:
        self._inner = inner
        self._clock = clock
        self._costs = dict(costs or {})
        self._failing = set(failing)
        self.activated: list[str] = []
        self.deactivated: list[str] = []
        self.contexts: dict[str, dict[str, object]] = {}

    def discover(self) -> list[PluginEnvelope]:
        return self._inner.discover(roots=[_PROFILE_FIXTURES])

    def activate(self, envelope: PluginEnvelope, ctx: ActivationContext) -> PluginHandle:
        self.activated.append(envelope.id)
        self.contexts[envelope.id] = dict(ctx.config)
        self._clock.advance(self._costs.get(envelope.id, 0.0))
        if envelope.id in self._failing:
            raise PluginLoadError(f"模拟 {envelope.id} 装载失败")
        return self._inner.activate(envelope, ctx)

    def deactivate(self, handle: PluginHandle) -> None:
        self.deactivated.append(handle.plugin_id)
        self._inner.deactivate(handle)


@pytest.fixture()
def envelopes() -> dict[str, PluginEnvelope]:
    discovered = HappyclawPluginLoader().discover(roots=[_PROFILE_FIXTURES])
    return {envelope.id: envelope for envelope in discovered}


def make_runtime(
    envelopes: Mapping[str, PluginEnvelope],
    *,
    clock: FakeClock | None = None,
    costs: Mapping[str, float] | None = None,
    failing: frozenset[str] = frozenset(),
    store: ProfileStore | None = None,
) -> tuple[ProfileRuntime, CostedLoader]:
    tick = clock or FakeClock()
    loader = CostedLoader(
        HappyclawPluginLoader(),
        tick,
        costs=costs,
        failing=failing,
    )
    runtime = ProfileRuntime(
        loaders={PluginKind.OCTOP: loader},
        envelopes=list(envelopes.values()),
        store=store,
        clock=tick.now,
    )
    return runtime, loader


def test_real_envelopes_resolve_dependency_closure(
    envelopes: Mapping[str, PluginEnvelope],
) -> None:
    dependent = envelopes[DEPENDENT]
    assert dependent.requires == (PluginRequirement(BASE, ">=1.0.0"),)
    assert dependent.metadata["native_manifest"] == "plugin.yaml"

    runtime, loader = make_runtime(envelopes)

    result = runtime.switch(Profile("closure", (ProfileEntry(DEPENDENT),)))

    assert result.ok is True
    # The dependency comes first and is auto-included even though the profile
    # only names the dependent plugin.
    assert result.activated == (BASE, DEPENDENT)
    assert loader.activated == [BASE, DEPENDENT]
    assert loader.contexts[BASE] == {}
    assert [state.plugin_id for state in runtime.status()] == [BASE, DEPENDENT]


def test_real_envelope_missing_dependency_is_identifiable(
    envelopes: Mapping[str, PluginEnvelope],
) -> None:
    assert envelopes[ORPHAN].requires == (
        PluginRequirement("octop:profile-missing", ">=1.0.0"),
    )
    runtime, loader = make_runtime(envelopes)

    with pytest.raises(MissingDependencyError) as caught:
        runtime.switch(Profile("missing", (ProfileEntry(ORPHAN),)))

    assert caught.value.code is PluginErrorCode.DEPENDENCY_MISSING
    assert "octop:profile-missing" in caught.value.message
    assert "未被发现" in caught.value.message
    assert caught.value.details["plugin_id"] == ORPHAN
    assert loader.activated == []
    assert runtime.active_profile is None


def test_real_envelope_version_conflict_is_identifiable(
    envelopes: Mapping[str, PluginEnvelope],
) -> None:
    assert envelopes[CONFLICT].requires == (PluginRequirement(BASE, ">=2.0.0"),)
    assert envelopes[BASE].version == "1.0.0"
    runtime, _loader = make_runtime(envelopes)

    with pytest.raises(VersionConflictError) as caught:
        runtime.switch(Profile("conflict", (ProfileEntry(CONFLICT),)))

    assert caught.value.code is PluginErrorCode.VERSION_CONFLICT
    assert ">=2.0.0" in caught.value.message
    assert "1.0.0" in caught.value.message
    assert caught.value.details["plugin_id"] == CONFLICT
    assert caught.value.details["dependency"] == BASE


def test_composition_permission_report(
    envelopes: Mapping[str, PluginEnvelope],
) -> None:
    runtime, _loader = make_runtime(envelopes)

    result = runtime.switch(
        Profile(
            "perms",
            (ProfileEntry(BASE), ProfileEntry(DEPENDENT), ProfileEntry(BARE)),
        )
    )

    assert result.permissions[BASE] == (PermissionKind.FS_READ,)
    assert result.permissions[DEPENDENT] == (PermissionKind.NETWORK,)
    assert result.permissions[BARE] == ()

    report = runtime.permission_report()
    assert report["profile"] == "perms"
    items = {row["plugin_id"]: row for row in report["plugins"]}
    assert items[BASE] == {
        "plugin_id": BASE,
        "declared": True,
        "items": ["fs.read"],
        "policy": "declared",
    }
    assert items[DEPENDENT]["items"] == ["network"]
    assert items[BARE] == {
        "plugin_id": BARE,
        "declared": False,
        "items": [],
        "policy": "least_privilege",
    }
    assert report["union"] == ["fs.read", "network"]
    assert report["undeclared"] == [BARE]
    assert runtime.permissions_for(BARE) == ()


def test_profile_cannot_grant_undeclared_permissions(
    envelopes: Mapping[str, PluginEnvelope],
) -> None:
    runtime, _loader = make_runtime(envelopes)

    with pytest.raises(InvalidManifestError) as caught:
        runtime.switch(
            Profile(
                "widened",
                (
                    ProfileEntry(
                        BASE,
                        permissions=(PermissionKind.FS_READ, PermissionKind.NETWORK),
                    ),
                ),
            )
        )

    assert caught.value.code is PluginErrorCode.MANIFEST_INVALID
    assert "没有声明权限" in caught.value.message
    assert caught.value.details["permissions"] == ["network"]


def test_lazy_timing_splits_switch_and_first_use(
    envelopes: Mapping[str, PluginEnvelope],
) -> None:
    clock = FakeClock()
    runtime, loader = make_runtime(
        envelopes,
        clock=clock,
        costs={BASE: 30.0, BARE: 70.0},
    )

    result = runtime.switch(
        Profile(
            "lazy",
            (ProfileEntry(BASE), ProfileEntry(BARE, load=LoadMode.LAZY)),
        )
    )

    assert result.ok is True
    assert loader.activated == [BASE]
    assert result.elapsed_ms == pytest.approx(30.0)
    report = runtime.timing_report()
    assert report["eager_ms"] == pytest.approx(30.0)
    assert report["lazy_ms"] == pytest.approx(0.0)
    assert [row["plugin_id"] for row in report["plugins"]] == [BASE]

    runtime.ensure_loaded(BARE)

    report = runtime.timing_report()
    assert report["eager_ms"] == pytest.approx(30.0)
    assert report["lazy_ms"] == pytest.approx(70.0)
    assert report["total_ms"] == pytest.approx(100.0)
    assert [row["phase"] for row in report["plugins"]] == ["eager", "lazy"]


def test_switch_rolls_back_when_a_real_plugin_fails(
    envelopes: Mapping[str, PluginEnvelope],
    tmp_path: Path,
) -> None:
    store = ProfileStore(tmp_path / "store")
    store.save(Profile("base", (ProfileEntry(BASE),)))
    store.save(Profile("broken", (ProfileEntry(BASE), ProfileEntry(DEPENDENT))))
    runtime, loader = make_runtime(
        envelopes,
        failing=frozenset({DEPENDENT}),
        store=store,
    )

    first = runtime.switch("base")
    assert first.ok is True

    result = runtime.switch("broken")

    assert result.ok is False
    assert result.rolled_back is True
    assert [failure.plugin_id for failure in result.failures] == [DEPENDENT]
    assert result.failures[0].code == "PLUGIN_LOAD_FAILED"
    assert result.activated == ()
    assert result.deactivated == ()
    assert loader.activated == [BASE, DEPENDENT]
    assert loader.deactivated == []
    assert runtime.active_profile == "base"
    assert runtime.revision == first.revision
    assert {
        row.plugin_id: row.status for row in runtime.status()
    } == {BASE: PluginStatus.ACTIVE}
    active = store.load_active()
    assert active is not None and active.name == "base"
    assert runtime.timing_report()["eager_ms"] == pytest.approx(0.0)


def test_lazy_failure_marks_only_that_plugin(
    envelopes: Mapping[str, PluginEnvelope],
) -> None:
    runtime, _loader = make_runtime(envelopes, failing=frozenset({BARE}))
    runtime.switch(
        Profile("p", (ProfileEntry(BASE), ProfileEntry(BARE, load=LoadMode.LAZY)))
    )

    with pytest.raises(PluginLoadError):
        runtime.ensure_loaded(BARE)

    statuses = {row.plugin_id: row for row in runtime.status()}
    assert statuses[BASE].status is PluginStatus.ACTIVE
    assert statuses[BARE].status is PluginStatus.FAILED
    assert statuses[BARE].error is not None
    assert statuses[BARE].error.code == "PLUGIN_LOAD_FAILED"
    assert runtime.active_profile == "p"


def test_active_pointer_persists_and_rollback_restores_previous(
    envelopes: Mapping[str, PluginEnvelope],
    tmp_path: Path,
) -> None:
    store = ProfileStore(tmp_path / "store")
    store.save(Profile("base", (ProfileEntry(BASE),)))
    store.save(Profile("extra", (ProfileEntry(BASE), ProfileEntry(DEPENDENT))))
    runtime, loader = make_runtime(envelopes, store=store)

    assert runtime.switch("base").persisted is True
    assert runtime.switch("extra").persisted is True
    assert runtime.active_profile == "extra"

    active = store.load_active()
    assert active is not None
    assert (active.name, active.previous) == ("extra", "base")

    rolled = runtime.rollback()
    assert rolled.ok is True
    assert runtime.active_profile == "base"
    assert runtime.previous_profile == "extra"
    assert loader.deactivated == [DEPENDENT]


# -- market install root linkage ------------------------------------------------
#
# The plugins below are real packages: they are zipped, installed through the
# real ``MarketplaceIndex`` (only the HTTP transport is offline), and read back
# by ``MarketInstallSource`` from the market's own ``<kind>/<native>/<version>``
# layout. No envelope is constructed by hand here either.

MARKET_BASE = "octop:mkt-base"
MARKET_DEPENDENT = "octop:mkt-dependent"


def _zip(files: Mapping[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in files.items():
            archive.writestr(name, text.encode("utf-8"))
    return buffer.getvalue()


def _package(
    native_id: str,
    version: str,
    *,
    requires: Sequence[str] = (),
    permissions: Sequence[str] = (),
) -> bytes:
    manifest = (
        f"id: {native_id}\n"
        f"version: {version}\n"
        f"name: {native_id}\n"
        "kind: tool\n"
        "entry: main.py\n"
    )
    if permissions:
        manifest += "permissions:\n" + "".join(f"  - {item}\n" for item in permissions)
    if requires:
        manifest += "requires:\n" + "".join(f"  - {item}\n" for item in requires)
    return _zip(
        {"plugin.yaml": manifest, "main.py": "def main():\n    return 'ok'\n"}
    )


def _catalog_index(
    releases: Sequence[tuple[str, str]],
    *,
    requires: Mapping[str, Sequence[str]] | None = None,
    native_requires: Mapping[str, Sequence[str]] | None = None,
    permissions: Mapping[str, Sequence[str]] | None = None,
) -> tuple[MarketplaceIndex, dict[str, bytes]]:
    """Build an offline catalog plus the downloadable archives it advertises.

    ``requires`` is what the catalog row says (always an ``octop:``/``dsh:``
    prefixed plugin id) while ``native_requires`` is what ``plugin.yaml``
    declares (the real range), so a test can model the two disagreeing the way
    real packages do.
    """

    deps = dict(requires or {})
    native_deps = dict(native_requires or {})
    perms = dict(permissions or {})
    archives: dict[str, bytes] = {}
    items: list[dict[str, object]] = []
    for native_id, version in releases:
        url = f"https://offline.example/{native_id}-{version}.zip"
        archives[url] = _package(
            native_id,
            version,
            requires=native_deps.get(native_id, ()),
            permissions=perms.get(native_id, ()),
        )
        items.append(
            {
                "id": native_id,
                "version": version,
                "kind": "tool",
                "download_url": url,
                "requires": list(deps.get(native_id, ())),
            }
        )
    source = HappyclawSource(loader=lambda: items, transport=archives.__getitem__)
    return MarketplaceIndex([source]), archives


def _market_runtime(dest: Path) -> tuple[ProfileRuntime, MarketInstallSource]:
    source = MarketInstallSource(dest)
    runtime = ProfileRuntime(
        loaders={PluginKind.OCTOP: HappyclawPluginLoader()},
        envelopes=[],
        envelope_provider=source.envelopes,
    )
    return runtime, source


def test_composition_discovers_and_uses_plugins_from_market_root(
    tmp_path: Path,
) -> None:
    index, _archives = _catalog_index(
        [("mkt-base", "1.0.0"), ("mkt-dependent", "1.0.0")],
        requires={"mkt-dependent": ["octop:mkt-base"]},
        permissions={"mkt-base": ["fs.read"]},
    )
    dest = tmp_path / "market"
    index.install(MARKET_BASE, dest)
    index.install(MARKET_DEPENDENT, dest)

    runtime, source = _market_runtime(dest)

    assert set(source.envelopes()) == {MARKET_BASE, MARKET_DEPENDENT}
    assert source.slot_for(MARKET_BASE) == dest / "octop" / "mkt-base" / "1.0.0"

    result = runtime.switch(Profile("market", (ProfileEntry(MARKET_DEPENDENT),)))

    assert result.ok is True
    # The dependency is auto-included and both come from the market root; the
    # composition names only the dependent id.
    assert result.activated == (MARKET_BASE, MARKET_DEPENDENT)
    assert {
        row.plugin_id: row.version for row in runtime.status()
    } == {MARKET_BASE: "1.0.0", MARKET_DEPENDENT: "1.0.0"}
    assert runtime.permissions_for(MARKET_BASE) == (PermissionKind.FS_READ,)


def test_uninstall_marks_composition_degraded_with_missing_ids(
    tmp_path: Path,
) -> None:
    index, _archives = _catalog_index([("mkt-base", "1.0.0")])
    dest = tmp_path / "market"
    index.install(MARKET_BASE, dest)

    runtime, source = _market_runtime(dest)
    runtime.switch(Profile("solo", (ProfileEntry(MARKET_BASE),)))
    assert source.slot_for(MARKET_BASE) is not None

    uninstall(MARKET_BASE, dest)
    assert source.slot_for(MARKET_BASE) is None
    refreshed = runtime.refresh()

    # A vanished plugin must never look like a healthy, merely smaller profile.
    assert refreshed.ok is False
    assert refreshed.degraded is True
    assert refreshed.missing == (MARKET_BASE,)
    assert refreshed.failures[0].code == PluginErrorCode.DEPENDENCY_MISSING.value
    assert runtime.degraded is True
    assert runtime.missing_plugins == (MARKET_BASE,)
    row = {state.plugin_id: state for state in runtime.status()}[MARKET_BASE]
    assert row.status is PluginStatus.FAILED
    assert row.error is not None
    assert row.error.code == PluginErrorCode.DEPENDENCY_MISSING.value

    # Re-resolving the same profile refuses instead of silently dropping it.
    with pytest.raises(MissingDependencyError) as caught:
        runtime.switch(Profile("solo", (ProfileEntry(MARKET_BASE),)))
    assert caught.value.details["plugin_id"] == MARKET_BASE


def test_upgrade_swaps_version_and_rechecks_profile_constraints(
    tmp_path: Path,
) -> None:
    # The catalog records a bare dependency; plugin.yaml carries the real pin.
    index_v1, _v1 = _catalog_index(
        [("mkt-base", "1.0.0"), ("mkt-dependent", "1.0.0")],
        requires={"mkt-dependent": ["octop:mkt-base"]},
        native_requires={"mkt-dependent": [f"{MARKET_BASE}>=1.0.0,<2.0.0"]},
    )
    dest = tmp_path / "market"
    index_v1.install(MARKET_BASE, dest)
    index_v1.install(MARKET_DEPENDENT, dest)

    runtime, _source = _market_runtime(dest)
    runtime.switch(Profile("pinned", (ProfileEntry(MARKET_DEPENDENT),)))
    assert runtime.envelopes[MARKET_BASE].version == "1.0.0"

    # A satisfying upgrade: the new version is used, the old slot is not.
    index_v11, _v11 = _catalog_index([("mkt-base", "1.1.0")])
    index_v11.upgrade(MARKET_BASE, dest)
    upgraded = runtime.refresh()

    assert upgraded.ok is True
    assert upgraded.degraded is False
    assert upgraded.replaced == (MARKET_BASE,)
    versions = {row.plugin_id: row.version for row in runtime.status()}
    assert versions[MARKET_BASE] == "1.1.0"

    # A breaking upgrade: the composition refuses and says which constraint.
    index_v2, _v2 = _catalog_index([("mkt-base", "2.0.0")])
    index_v2.upgrade(MARKET_BASE, dest)
    broken = runtime.refresh()

    assert broken.ok is False
    assert broken.degraded is True
    assert MARKET_BASE in broken.missing
    assert broken.reason is not None
    assert "2.0.0" in broken.reason
    assert "<2.0.0" in broken.reason

    with pytest.raises(VersionConflictError) as caught:
        runtime.switch(Profile("pinned", (ProfileEntry(MARKET_DEPENDENT),)))
    assert caught.value.details["dependency"] == MARKET_BASE
    assert caught.value.details["plugin_id"] == MARKET_DEPENDENT
