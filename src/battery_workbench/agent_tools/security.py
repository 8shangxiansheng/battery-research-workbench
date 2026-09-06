"""BRW-026 security guards (§17/§8/§9).

Input hygiene enforced before any tool executes: no arbitrary paths, URLs,
shell, eval, SQL, pickles, custom code, or oversized payloads. Parameter
no-guess guard blocks agent-inferred scientific values.
"""

from __future__ import annotations

import re
from typing import Any

MAX_INPUT_JSON_BYTES = 256 * 1024
MAX_STRING_FIELD_LEN = 4096

_ARBITRARY_PATH = re.compile(r"(\.{1,2}/|^/|[A-Za-z]:\\\\)")
_URL = re.compile(r"https?://|ftp://|file://")
_SHELL = re.compile(r"[;&|`$><]|\bsh\b|\bbash\b|\bcurl\b|\bwget\b")
_SQL = re.compile(
    r"\b(select|insert|update|delete|drop|alter)\b.+\b(from|into|table)\b", re.IGNORECASE
)
_CODE = re.compile(r"(__import__|eval\(|exec\(|compile\(|pickle|marshal)")

# Parameters the agent must never infer (§9)
NO_GUESS_PARAMETERS = {
    "ultrasound.sampling_rate_hz",
    "ultrasound.trigger_sample_index",
    "experiment.timezone",
    "experiment.ultrasound_path_length_m",
    "experiment.reference_capacity_ah",
}

FORBIDDEN_INFERENCE_SOURCES = (
    "sample count",
    "frame cadence",
    "filename",
    "demo config",
    "waveform length",
)


class SecurityViolation(ValueError):
    """Raised when tool input violates the security baseline."""


def check_input_safety(tool_name: str, inputs: dict[str, Any]) -> None:
    blob = repr(inputs)
    if len(blob.encode("utf-8")) > MAX_INPUT_JSON_BYTES:
        raise SecurityViolation("oversized input payload")
    for key, value in inputs.items():
        if not isinstance(value, str):
            continue
        if key == "content":
            # asset payload: bounded by MAX_INPUT_JSON_BYTES overall; hostile-pattern scan only
            if len(value.encode("utf-8", errors="ignore")) > MAX_INPUT_JSON_BYTES:
                raise SecurityViolation("asset payload too large")
            if _CODE.search(value) or _URL.search(value):
                raise SecurityViolation(f"hostile content rejected in {key}")
            continue
        if len(value) > MAX_STRING_FIELD_LEN:
            raise SecurityViolation(f"string field too long: {key}")
        if key in {"path", "file_path", "url", "command", "sql", "code"}:
            raise SecurityViolation(f"client-controlled {key} is not accepted by any tool")
        if _ARBITRARY_PATH.search(value):
            raise SecurityViolation(f"arbitrary filesystem path rejected in {key}")
        if _URL.search(value):
            raise SecurityViolation(f"arbitrary URL rejected in {key}")
        if tool_name != "inspect_text" and _SHELL.search(value):
            raise SecurityViolation(f"shell metacharacters rejected in {key}")
        if _CODE.search(value):
            raise SecurityViolation(f"code execution rejected in {key}")
        if _SQL.search(value):
            raise SecurityViolation(f"SQL rejected in {key}")


def check_parameter_guess(name: str, value: Any, *, inferred_from: str | None = None) -> None:
    """Agent-set scientific parameters must come from the user, never inference (§9)."""
    if name in NO_GUESS_PARAMETERS and inferred_from is not None:
        lowered = inferred_from.lower()
        for source in FORBIDDEN_INFERENCE_SOURCES:
            if source in lowered:
                raise SecurityViolation(
                    f"refusing to set {name}: inferred from '{inferred_from}' "
                    f"({source} is not a valid scientific source)"
                )
