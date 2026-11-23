"""Small JSON Schema validator used for DSH tool parameters and outputs.

DSH requires every tool to declare ``parameters`` and ``output.schema`` as JSON
Schema and validates both in the execution pipeline. Octop does not depend on
``jsonschema`` directly, so the bridge ships a deliberately small validator
covering the keywords DSH tools actually use. Unknown keywords are ignored.

Supported keywords: ``type``, ``properties``, ``required``,
``additionalProperties``, ``patternProperties``, ``items``, ``enum``, ``const``,
``allOf`` / ``anyOf`` / ``oneOf``, ``minimum`` / ``maximum`` / ``exclusive*``,
``minLength`` / ``maxLength`` / ``pattern``, ``minItems`` / ``maxItems``, and
local ``$ref`` (``#/$defs/...`` / ``#/definitions/...``).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

_JSON_TYPES = frozenset({"object", "array", "string", "integer", "number", "boolean", "null"})
_MAX_SCHEMA_DEPTH = 32


def assert_json_schema(schema: object, *, label: str = "schema") -> None:
    """Raise ``ValueError`` when ``schema`` is not a usable JSON Schema object."""
    if not isinstance(schema, dict):
        raise ValueError(f"{label} must be a JSON Schema object")
    _check_nodes(schema, label=label, depth=0)


def _check_nodes(node: object, *, label: str, depth: int) -> None:
    if depth > _MAX_SCHEMA_DEPTH:
        raise ValueError(f"{label} is nested too deeply")
    if not isinstance(node, dict):
        raise ValueError(f"{label} must be a JSON Schema object")

    declared = node.get("type")
    if declared is not None:
        names = declared if isinstance(declared, list) else [declared]
        if not names or any(str(name) not in _JSON_TYPES for name in names):
            raise ValueError(f"{label}.type must be one of {sorted(_JSON_TYPES)}")

    properties = node.get("properties")
    if properties is not None:
        if not isinstance(properties, dict):
            raise ValueError(f"{label}.properties must be an object")
        for name, sub in properties.items():
            _check_nodes(sub, label=f"{label}.properties.{name}", depth=depth + 1)

    pattern_properties = node.get("patternProperties")
    if isinstance(pattern_properties, dict):
        for pattern, sub in pattern_properties.items():
            try:
                re.compile(str(pattern))
            except re.error as exc:
                raise ValueError(f"{label}.patternProperties has invalid pattern: {exc}") from exc
            _check_nodes(sub, label=f"{label}.patternProperties.{pattern}", depth=depth + 1)

    items = node.get("items")
    if isinstance(items, dict):
        _check_nodes(items, label=f"{label}.items", depth=depth + 1)
    elif isinstance(items, list):
        for index, sub in enumerate(items):
            _check_nodes(sub, label=f"{label}.items[{index}]", depth=depth + 1)

    for combinator in ("allOf", "anyOf", "oneOf"):
        branches = node.get(combinator)
        if branches is not None:
            if not isinstance(branches, list) or not branches:
                raise ValueError(f"{label}.{combinator} must be a non-empty array")
            for index, sub in enumerate(branches):
                _check_nodes(sub, label=f"{label}.{combinator}[{index}]", depth=depth + 1)

    for definitions_key in ("$defs", "definitions"):
        definitions = node.get(definitions_key)
        if isinstance(definitions, dict):
            for name, sub in definitions.items():
                _check_nodes(sub, label=f"{label}.{definitions_key}.{name}", depth=depth + 1)


def validate_json_schema(instance: Any, schema: Mapping[str, Any]) -> list[str]:
    """Return human-readable violations; an empty list means the value is valid."""
    return _validate(instance, schema, schema, "$")


def _validate(value: Any, schema: Any, root: Mapping[str, Any], path: str) -> list[str]:
    if schema is True:
        return []
    if schema is False:
        return [f"{path}: no value is allowed here"]
    if not isinstance(schema, Mapping):
        return [f"{path}: schema node is not an object"]

    if "$ref" in schema:
        resolved = _resolve_ref(str(schema["$ref"]), root)
        if resolved is None:
            return [f"{path}: unresolved $ref {schema['$ref']!r}"]
        return _validate(value, resolved, root, path)

    errors: list[str] = []

    declared = schema.get("type")
    if declared is not None:
        names = [str(name) for name in declared] if isinstance(declared, list) else [str(declared)]
        if not any(_matches_type(value, name) for name in names):
            errors.append(f"{path}: expected {' or '.join(names)}, got {_type_name(value)}")
            return errors

    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: expected constant {schema['const']!r}")

    allowed = schema.get("enum")
    if isinstance(allowed, list) and not any(value == candidate for candidate in allowed):
        errors.append(f"{path}: expected one of {allowed!r}")

    if isinstance(value, str):
        errors.extend(_validate_string(value, schema, path))
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        errors.extend(_validate_number(value, schema, path))
    elif isinstance(value, Mapping):
        errors.extend(_validate_object(value, schema, root, path))
    elif isinstance(value, list):
        errors.extend(_validate_array(value, schema, root, path))

    for combinator in ("allOf", "anyOf", "oneOf"):
        branches = schema.get(combinator)
        if isinstance(branches, list) and branches:
            errors.extend(
                _validate_combinator(combinator, value, branches, root, path),
            )

    return errors


def _validate_string(value: str, schema: Mapping[str, Any], path: str) -> list[str]:
    errors: list[str] = []
    minimum = schema.get("minLength")
    if isinstance(minimum, int) and len(value) < minimum:
        errors.append(f"{path}: shorter than minLength {minimum}")
    maximum = schema.get("maxLength")
    if isinstance(maximum, int) and len(value) > maximum:
        errors.append(f"{path}: longer than maxLength {maximum}")
    pattern = schema.get("pattern")
    if isinstance(pattern, str):
        try:
            if re.search(pattern, value) is None:
                errors.append(f"{path}: does not match pattern {pattern!r}")
        except re.error:
            errors.append(f"{path}: schema has an invalid pattern")
    return errors


def _validate_number(value: int | float, schema: Mapping[str, Any], path: str) -> list[str]:
    errors: list[str] = []
    minimum = schema.get("minimum")
    if isinstance(minimum, (int, float)) and value < minimum:
        errors.append(f"{path}: less than minimum {minimum}")
    maximum = schema.get("maximum")
    if isinstance(maximum, (int, float)) and value > maximum:
        errors.append(f"{path}: greater than maximum {maximum}")
    exclusive_min = schema.get("exclusiveMinimum")
    if isinstance(exclusive_min, (int, float)) and value <= exclusive_min:
        errors.append(f"{path}: not greater than exclusiveMinimum {exclusive_min}")
    exclusive_max = schema.get("exclusiveMaximum")
    if isinstance(exclusive_max, (int, float)) and value >= exclusive_max:
        errors.append(f"{path}: not less than exclusiveMaximum {exclusive_max}")
    return errors


def _validate_object(
    value: Mapping[str, Any],
    schema: Mapping[str, Any],
    root: Mapping[str, Any],
    path: str,
) -> list[str]:
    errors: list[str] = []
    required = schema.get("required")
    if isinstance(required, list):
        for name in required:
            if str(name) not in value:
                errors.append(f"{path}: missing required property {name!r}")

    properties = schema.get("properties")
    known: dict[str, Any] = properties if isinstance(properties, dict) else {}
    for name, sub in known.items():
        if name in value:
            errors.extend(_validate(value[name], sub, root, f"{path}.{name}"))

    pattern_properties = schema.get("patternProperties")
    patterns = pattern_properties if isinstance(pattern_properties, dict) else {}
    for key, item in value.items():
        if key in known:
            continue
        matched = False
        for pattern, sub in patterns.items():
            try:
                if re.search(str(pattern), str(key)) is not None:
                    matched = True
                    errors.extend(_validate(item, sub, root, f"{path}.{key}"))
            except re.error:
                continue
        additional = schema.get("additionalProperties")
        if matched or additional is None or additional is True:
            continue
        if additional is False:
            errors.append(f"{path}: unexpected property {key!r}")
        elif isinstance(additional, Mapping):
            errors.extend(_validate(item, additional, root, f"{path}.{key}"))
    return errors


def _validate_array(
    value: list[Any],
    schema: Mapping[str, Any],
    root: Mapping[str, Any],
    path: str,
) -> list[str]:
    errors: list[str] = []
    minimum = schema.get("minItems")
    if isinstance(minimum, int) and len(value) < minimum:
        errors.append(f"{path}: fewer than minItems {minimum}")
    maximum = schema.get("maxItems")
    if isinstance(maximum, int) and len(value) > maximum:
        errors.append(f"{path}: more than maxItems {maximum}")

    items = schema.get("items")
    if isinstance(items, Mapping):
        for index, item in enumerate(value):
            errors.extend(_validate(item, items, root, f"{path}[{index}]"))
    elif isinstance(items, list):
        for index, sub in enumerate(items[: len(value)]):
            errors.extend(_validate(value[index], sub, root, f"{path}[{index}]"))
    return errors


def _validate_combinator(
    combinator: str,
    value: Any,
    branches: Sequence[Any],
    root: Mapping[str, Any],
    path: str,
) -> list[str]:
    outcomes = [_validate(value, branch, root, path) for branch in branches]
    passing = sum(1 for outcome in outcomes if not outcome)
    if combinator == "allOf":
        return [error for outcome in outcomes for error in outcome]
    if combinator == "anyOf" and passing == 0:
        return [f"{path}: does not match any anyOf branch"]
    if combinator == "oneOf" and passing != 1:
        return [f"{path}: must match exactly one oneOf branch (matched {passing})"]
    return []


def _resolve_ref(ref: str, root: Mapping[str, Any]) -> Any:
    if not ref.startswith("#/"):
        return None
    node: Any = root
    for raw in ref[2:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, Mapping) or token not in node:
            return None
        node = node[token]
    return node


def _matches_type(value: Any, type_name: str) -> bool:
    if type_name == "object":
        return isinstance(value, Mapping)
    if type_name == "array":
        return isinstance(value, list)
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "null":
        return value is None
    return True


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, list):
        return "array"
    return type(value).__name__


__all__ = ["assert_json_schema", "validate_json_schema"]
