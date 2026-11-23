"""Failure modes for the DSH prompt-section bridge."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

__all__ = [
    "DshPromptError",
    "DshPromptErrorCode",
    "DuplicateSectionError",
    "InvalidSectionError",
    "MalformedPromptVariableError",
    "MultipleCompleteSectionsError",
    "UndefinedPromptVariableError",
    "UnknownPromptVariableError",
]


class DshPromptErrorCode(StrEnum):
    DUPLICATE_SECTION = "DSH_PROMPT_DUPLICATE_SECTION"
    INVALID_SECTION = "DSH_PROMPT_INVALID_SECTION"
    MULTIPLE_COMPLETE = "DSH_PROMPT_MULTIPLE_COMPLETE"
    MALFORMED_VARIABLE = "DSH_PROMPT_MALFORMED_VARIABLE"
    UNKNOWN_VARIABLE = "DSH_PROMPT_UNKNOWN_VARIABLE"
    UNDEFINED_VARIABLE = "DSH_PROMPT_UNDEFINED_VARIABLE"


class DshPromptError(Exception):
    """Prompt assembly failure with a stable code and structured details."""

    code: DshPromptErrorCode = DshPromptErrorCode.INVALID_SECTION

    def __init__(
        self,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
            "details": dict(self.details),
        }

    def __str__(self) -> str:
        return self.message


class DuplicateSectionError(DshPromptError):
    """Two sections share one name in the same registry."""

    code = DshPromptErrorCode.DUPLICATE_SECTION


class InvalidSectionError(DshPromptError):
    """A section has a non-finite order, empty name, or non-static text."""

    code = DshPromptErrorCode.INVALID_SECTION


class MultipleCompleteSectionsError(DshPromptError):
    """More than one section claims to be the complete system prompt."""

    code = DshPromptErrorCode.MULTIPLE_COMPLETE


class MalformedPromptVariableError(DshPromptError):
    """A ``{{...}}`` reference has an invalid name or unbalanced braces."""

    code = DshPromptErrorCode.MALFORMED_VARIABLE


class UnknownPromptVariableError(DshPromptError):
    """A section references a variable that was not supplied."""

    code = DshPromptErrorCode.UNKNOWN_VARIABLE


class UndefinedPromptVariableError(DshPromptError):
    """A referenced variable exists but has no value for this assembly."""

    code = DshPromptErrorCode.UNDEFINED_VARIABLE
