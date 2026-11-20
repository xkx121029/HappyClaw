"""Typed failures for the DSH compatibility adapter.

Every failure the adapter can report is one of these codes. A plugin is never
reported as "running" when its mount, its client asset or a host API it needs
did not actually work.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class DshCompatCode(StrEnum):
    OK = "OK"
    DISABLED = "DISABLED"
    ENTRY_SHAPE = "ENTRY_SHAPE"
    IMPORT_FAILED = "IMPORT_FAILED"
    MISSING_API = "MISSING_API"
    SIGNATURE_MISMATCH = "SIGNATURE_MISMATCH"
    RUNTIME_THROW = "RUNTIME_THROW"
    TIMEOUT = "TIMEOUT"
    PROCESS_EXIT = "PROCESS_EXIT"
    NEEDS_BUILD = "NEEDS_BUILD"
    NEEDS_NETWORK = "NEEDS_NETWORK"
    NEEDS_CREDENTIAL = "NEEDS_CREDENTIAL"
    NEEDS_PERMISSION = "NEEDS_PERMISSION"
    NATIVE_MODULE = "NATIVE_MODULE"
    ENGINE_UNSATISFIED = "ENGINE_UNSATISFIED"
    SLOT_UNSUPPORTED = "SLOT_UNSUPPORTED"
    BUNDLE_UNSUPPORTED = "BUNDLE_UNSUPPORTED"
    HOST_API_UNSUPPORTED = "HOST_API_UNSUPPORTED"
    REMOTE_DENIED = "REMOTE_DENIED"
    CLIENT_MISSING = "CLIENT_MISSING"
    NOT_ALLOWED = "NOT_ALLOWED"


class DshCompatError(Exception):
    """A compatibility failure with a stable code and diagnostic details."""

    def __init__(
        self,
        code: DshCompatCode,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
            "details": self.details,
        }
