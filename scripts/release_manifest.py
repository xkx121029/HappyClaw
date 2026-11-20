#!/usr/bin/env python3
"""Build and validate the HappyClaw release manifest.

The manifest is consumed by ``GET /api/update/check`` (see
``src/octop/infra/setup/release_manifest.py``) and by the static site's
download section. Both the API and this script implement the same schema; the
JSON Schema lives in ``docs/release-manifest.schema.json``.

Usage
-----
Build a manifest from a directory of build artifacts::

    python scripts/release_manifest.py build \
        --version 1.0.4 \
        --channel stable \
        --artifacts-dir dist/release \
        --base-url https://downloads.example.invalid/happyclaw/1.0.4 \
        --notes-file docs/release-notes-1.0.4.md \
        --minimum-supported-version 1.0.0 \
        --output dist/release-manifest.json

Validate a manifest (optionally re-hashing the files on disk)::

    python scripts/release_manifest.py validate dist/release-manifest.json \
        --artifacts-dir dist/release

Artifact filenames must carry a platform and an architecture token, e.g.
``HappyClaw-portable-windows-x64-1.0.4.zip``. Unknown files fail the build
instead of being silently skipped.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

SCHEMA_VERSION = 1
CHANNELS: tuple[str, ...] = ("stable", "beta")
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
VERSION_RE = re.compile(
    r"^(\d+(?:\.\d+)*)((?:[-_.]?(?:a|alpha|b|beta|c|rc|pre|preview)\d*)?)"
    r"((?:[-_.]?(?:post|rev|r)\d*)?)((?:[-_.]?dev\d*)?)"
    r"(?:\+[a-z0-9]+(?:[-_.][a-z0-9]+)*)?$",
    re.IGNORECASE,
)

PLATFORM_ALIASES = {
    "windows": "windows",
    "win": "windows",
    "win32": "windows",
    "win64": "windows",
    "macos": "macos",
    "mac": "macos",
    "darwin": "macos",
    "osx": "macos",
    "linux": "linux",
    "fnos": "fnos",
    "android": "android",
    "ios": "ios",
}

ARCH_ALIASES = {
    "amd64": "x64",
    "x86_64": "x64",
    "x64": "x64",
    "arm64": "arm64",
    "aarch64": "arm64",
    "386": "x86",
    "x86": "x86",
    "armv7": "arm",
    "arm": "arm",
    "universal": "universal",
    "any": "any",
}

KIND_ALIASES = {
    "desktop": "desktop",
    "portable": "portable",
    "native": "native",
    "docker": "docker",
    "installer": "installer",
    "setup": "installer",
    "cli": "cli",
    "apk": "apk",
    "source": "source",
    "sdist": "source",
}


class ArtifactError(Exception):
    """Raised when a build artifact cannot be mapped to platform/arch/kind."""


def is_valid_version(value: str) -> bool:
    return bool(value and value.strip()) and VERSION_RE.match(value.strip()) is not None


def _infer_artifact(path: Path) -> tuple[str, str, str]:
    """Infer ``(platform, arch, kind)`` from an artifact filename.

    Raises :class:`ArtifactError` when the name does not carry enough
    information, so a release never silently drops a package.
    """
    name = path.name
    lowered = name.lower()

    if lowered.endswith(".whl"):
        return ("any", "any", "python")

    tokens = [token for token in re.split(r"[-_.]+", lowered) if token]
    platform = next(
        (PLATFORM_ALIASES[token] for token in tokens if token in PLATFORM_ALIASES),
        None,
    )
    arch = next((ARCH_ALIASES[token] for token in tokens if token in ARCH_ALIASES), None)
    kind = next((KIND_ALIASES[token] for token in tokens if token in KIND_ALIASES), None)

    if "docker" in tokens:
        kind = "docker"
        platform = platform or "linux"

    if kind is None:
        suffix = lowered
        if suffix.endswith((".exe", ".msi", ".dmg", ".appimage", ".deb", ".rpm")):
            kind = "installer"
        elif suffix.endswith(".fpk"):
            kind = "native"
        elif suffix.endswith(".apk"):
            kind = "apk"
        elif suffix.endswith((".zip", ".tar.gz", ".tgz", ".tar")):
            kind = "portable"
        else:
            kind = "artifact"

    if platform is None:
        raise ArtifactError(
            f"{name}: cannot infer platform; include a token such as "
            "windows / macos / linux / fnos / android in the filename"
        )
    if arch is None:
        raise ArtifactError(
            f"{name}: cannot infer architecture; include a token such as "
            "x64 / arm64 in the filename"
        )
    return platform, arch, kind


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_files(directory: Path, *, exclude: set[Path]) -> list[Path]:
    files = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path in exclude:
            continue
        if path.name.startswith("."):
            continue
        if path.suffix.lower() in {".json", ".sha256"}:
            continue
        files.append(path)
    return files


def build_manifest(args: argparse.Namespace) -> dict[str, Any]:
    artifacts_dir = Path(args.artifacts_dir).resolve()
    output = Path(args.output).resolve()
    if not artifacts_dir.is_dir():
        raise SystemExit(f"error: artifacts directory does not exist: {artifacts_dir}")
    if not is_valid_version(args.version):
        raise SystemExit(f"error: --version is not a PEP 440 version: {args.version}")
    if args.channel not in CHANNELS:
        raise SystemExit(f"error: --channel must be one of {', '.join(CHANNELS)}")
    if args.minimum_supported_version and not is_valid_version(
        args.minimum_supported_version
    ):
        raise SystemExit(
            "error: --minimum-supported-version is not a PEP 440 version: "
            f"{args.minimum_supported_version}"
        )

    base_url = args.base_url.rstrip("/")
    if not base_url.lower().startswith(("http://", "https://")):
        raise SystemExit("error: --base-url must be an absolute HTTP(S) URL")

    files = _artifact_files(artifacts_dir, exclude={output})
    if not files:
        raise SystemExit(f"error: no build artifacts found in {artifacts_dir}")

    artifacts: list[dict[str, Any]] = []
    for path in files:
        try:
            platform, arch, kind = _infer_artifact(path)
        except ArtifactError as exc:
            raise SystemExit(f"error: {exc}") from exc
        artifacts.append(
            {
                "platform": platform,
                "arch": arch,
                "kind": kind,
                "filename": path.name,
                "url": f"{base_url}/{quote(path.name)}",
                "sha256": sha256_of(path),
                "size_bytes": path.stat().st_size,
            }
        )

    notes = None
    if args.notes_file:
        notes_path = Path(args.notes_file)
        if not notes_path.is_file():
            raise SystemExit(f"error: notes file does not exist: {notes_path}")
        notes = notes_path.read_text(encoding="utf-8").strip() or None

    published_at = args.published_at or datetime.now(timezone.utc).replace(
        microsecond=0
    ).isoformat()

    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "product": args.product,
        "version": args.version,
        "channel": args.channel,
        "published_at": published_at,
        "notes": notes,
        "minimum_supported_version": args.minimum_supported_version or None,
        "artifacts": artifacts,
    }
    return manifest


def validate_manifest_data(
    data: object, *, artifacts_dir: Path | None = None
) -> list[str]:
    """Return a list of human-readable problems; empty means valid."""
    errors: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            errors.append(message)

    if not isinstance(data, dict):
        return ["manifest: top level must be a JSON object"]

    require(
        data.get("schema_version") == SCHEMA_VERSION,
        f"schema_version: must be {SCHEMA_VERSION}",
    )

    version = data.get("version")
    require(
        isinstance(version, str) and is_valid_version(version),
        "version: must be a PEP 440 version string",
    )

    channel = data.get("channel")
    require(
        isinstance(channel, str) and channel in CHANNELS,
        f"channel: must be one of {', '.join(CHANNELS)}",
    )

    published_at = data.get("published_at")
    if published_at is not None:
        require(
            isinstance(published_at, str) and bool(published_at.strip()),
            "published_at: must be a non-empty ISO-8601 string when present",
        )

    minimum = data.get("minimum_supported_version")
    if minimum is not None:
        require(
            isinstance(minimum, str) and is_valid_version(minimum),
            "minimum_supported_version: must be a PEP 440 version string",
        )

    notes = data.get("notes")
    require(notes is None or isinstance(notes, str), "notes: must be a string or null")

    product = data.get("product")
    require(product is None or isinstance(product, str), "product: must be a string or null")

    raw_artifacts = data.get("artifacts")
    if not isinstance(raw_artifacts, list) or not raw_artifacts:
        errors.append("artifacts: must be a non-empty list")
        return errors

    file_index: dict[str, Path] | None = None
    if artifacts_dir is not None:
        if not artifacts_dir.is_dir():
            errors.append(f"artifacts directory does not exist: {artifacts_dir}")
        else:
            file_index = {
                path.name: path
                for path in artifacts_dir.rglob("*")
                if path.is_file()
            }

    seen_files: set[str] = set()
    seen_urls: set[str] = set()

    for index, item in enumerate(raw_artifacts):
        field = f"artifacts[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{field}: must be an object")
            continue

        strings = ("platform", "arch", "filename", "url", "sha256")
        for key in strings:
            value = item.get(key)
            require(
                isinstance(value, str) and bool(value.strip()),
                f"{field}.{key}: must be a non-empty string",
            )

        kind = item.get("kind")
        require(
            kind is None or (isinstance(kind, str) and bool(kind.strip())),
            f"{field}.kind: must be a non-empty string or null",
        )

        sha = item.get("sha256")
        if isinstance(sha, str):
            require(
                SHA256_RE.match(sha.lower()) is not None,
                f"{field}.sha256: must be 64 hexadecimal characters",
            )

        url = item.get("url")
        if isinstance(url, str):
            require(
                url.lower().startswith(("http://", "https://")),
                f"{field}.url: must be an absolute HTTP(S) URL",
            )

        size = item.get("size_bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            errors.append(f"{field}.size_bytes: must be a positive integer")

        filename = item.get("filename")
        if isinstance(filename, str) and filename:
            if filename in seen_files:
                errors.append(f"{field}.filename: duplicate {filename}")
            seen_files.add(filename)

        if isinstance(url, str) and url:
            if url in seen_urls:
                errors.append(f"{field}.url: duplicate {url}")
            seen_urls.add(url)

        if (
            file_index is not None
            and isinstance(filename, str)
            and filename
            and isinstance(sha, str)
            and filename in file_index
        ):
            path = file_index[filename]
            actual_sha = sha256_of(path)
            if actual_sha != sha.lower():
                errors.append(
                    f"{field}.sha256: mismatch for {filename} "
                    f"(manifest {sha.lower()}, file {actual_sha})"
                )
            actual_size = path.stat().st_size
            if isinstance(size, int) and not isinstance(size, bool) and size != actual_size:
                errors.append(
                    f"{field}.size_bytes: mismatch for {filename} "
                    f"(manifest {size}, file {actual_size})"
                )

    if file_index is not None:
        for filename in seen_files:
            if filename not in file_index:
                errors.append(f"artifact file not found: {filename}")

    return errors


def load_json(path: Path) -> object:
    if not path.is_file():
        raise SystemExit(f"error: manifest does not exist: {path}")
    if path.stat().st_size > MAX_MANIFEST_BYTES:
        raise SystemExit(f"error: manifest is larger than {MAX_MANIFEST_BYTES} bytes")
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"error: manifest is not valid JSON: {exc}") from exc


def cmd_build(args: argparse.Namespace) -> int:
    manifest = build_manifest(args)
    artifacts_dir = Path(args.artifacts_dir).resolve()
    errors = validate_manifest_data(manifest, artifacts_dir=artifacts_dir)
    if errors:
        print("FAILED: generated manifest is invalid", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    total = sum(item["size_bytes"] for item in manifest["artifacts"])
    print(f"manifest: {output}")
    print(
        f"version: {manifest['version']}  channel: {manifest['channel']}  "
        f"artifacts: {len(manifest['artifacts'])}  total: {total} bytes"
    )
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest)
    data = load_json(manifest_path)
    artifacts_dir = Path(args.artifacts_dir).resolve() if args.artifacts_dir else None
    errors = validate_manifest_data(data, artifacts_dir=artifacts_dir)
    if errors:
        print(f"FAILED: {manifest_path}", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    artifacts = data.get("artifacts", []) if isinstance(data, dict) else []
    print(f"OK: {manifest_path}")
    print(f"artifacts: {len(artifacts)}")
    if artifacts_dir is not None:
        print(f"hashes verified against: {artifacts_dir}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build or validate the HappyClaw release manifest."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="generate a manifest from build artifacts")
    build.add_argument("--version", required=True, help="release version (PEP 440)")
    build.add_argument("--channel", required=True, choices=CHANNELS)
    build.add_argument("--artifacts-dir", required=True, help="directory of build artifacts")
    build.add_argument(
        "--base-url",
        required=True,
        help="public HTTP(S) prefix used to build artifact URLs (no placeholder is invented)",
    )
    build.add_argument("--output", required=True, help="path of the manifest to write")
    build.add_argument("--product", default="HappyClaw")
    build.add_argument("--notes-file", help="Markdown file with release notes")
    build.add_argument("--minimum-supported-version", help="oldest version that may upgrade")
    build.add_argument(
        "--published-at",
        help="ISO-8601 timestamp; defaults to the current UTC time",
    )
    build.set_defaults(func=cmd_build)

    validate = subparsers.add_parser("validate", help="validate an existing manifest")
    validate.add_argument("manifest", help="path to the manifest JSON")
    validate.add_argument(
        "--artifacts-dir",
        help="when set, re-hash files and verify sizes against the manifest",
    )
    validate.set_defaults(func=cmd_validate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
