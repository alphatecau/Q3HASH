"""Strict shared JSON mechanics for the two v1 data contracts."""

import json
import math


MAX_JSON_BYTES = 1_048_576


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError(f"Q3-SER-002: duplicate object key {key!r}")
        result[key] = value
    return result


def _constant(value):
    raise ValueError(f"Q3-SER-001: non-standard JSON constant {value}")


def _unicode_and_finite(value):
    if type(value) is str:
        value.encode("utf-8")
    elif type(value) is float and not math.isfinite(value):
        raise ValueError("Q3-SER-001: nonfinite JSON number")
    elif type(value) is dict:
        for key, item in value.items():
            _unicode_and_finite(key)
            _unicode_and_finite(item)
    elif type(value) is list:
        for item in value:
            _unicode_and_finite(item)


def _budget(text):
    if len(text) > MAX_JSON_BYTES or len(text.encode("utf-8")) > MAX_JSON_BYTES:
        raise ValueError("Q3-SER-001: JSON exceeds the 1 MiB UTF-8 wire budget")


def read_json(text):
    if type(text) is not str:
        raise TypeError("Q3-SER-001: JSON input must be a string")
    try:
        _budget(text)
        value = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
        _unicode_and_finite(value)
    except (ValueError, UnicodeError, RecursionError) as error:
        if isinstance(error, ValueError) and str(error).startswith("Q3-SER-"):
            raise
        raise ValueError("Q3-SER-001: malformed JSON, Unicode or numeric value") from error
    return value


def write_json(value):
    try:
        text = json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False)
        _budget(text)
    except (ValueError, UnicodeError, RecursionError) as error:
        if isinstance(error, ValueError) and str(error).startswith("Q3-SER-"):
            raise
        raise ValueError("Q3-SER-001: object cannot be represented within the JSON wire contract") from error
    return text


def fields(value, required, *, top=False):
    if type(value) is not dict:
        error = TypeError if top else ValueError
        raise error("Q3-SER-003: expected a JSON object")
    if set(value) != set(required):
        raise ValueError("Q3-SER-003: missing or unknown object fields")


def header(value, schema, required, *, kind=None):
    fields(value, required, top=True)
    if type(value["schema"]) is not str or value["schema"] != schema:
        raise ValueError("Q3-SER-004: unsupported schema")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("Q3-SER-004: unsupported schema version")
    if kind is not None and (type(value["kind"]) is not str or value["kind"] != kind):
        raise ValueError("Q3-SER-004: unsupported encoding kind")


def array(value):
    if type(value) is not list:
        raise ValueError("Q3-SER-003: expected a JSON array")
    return value
