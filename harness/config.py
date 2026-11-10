"""Typed view over ``policy.yaml``.

How this file is used
---------------------
``harness.guard.Guard`` loads the YAML once at start-up and keeps a ``Policy``.
``harness.loop.run`` reads the budgets and behaviour switches from that object, so
one YAML file drives the whole runtime without touching code.

Why a typed object instead of raw dicts
---------------------------------------
Every consumer used to walk nested dicts with ``.get(..., default)`` chains. One
place for defaults and validation keeps the rest of the codebase free of that
noise -- and makes a malformed rule fail loudly instead of silently changing
behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml  # type: ignore[import-not-found]  # installed inside the conda env


class PolicyError(ValueError):
    """Raised when policy.yaml does not have the shape the runtime expects."""


def _as_tuple(value: object, field: str) -> tuple[str, ...]:
    """Read a YAML list of scalars, refusing a bare string.

    A single string is the most common typo (``deny_segments: ".."``). Accepting
    it would silently turn a list rule into a character-by-character match.
    """
    if value is None:
        return ()
    if isinstance(value, str):
        raise PolicyError(f"{field} must be a list, got a single string: {value!r}")
    if not isinstance(value, (list, tuple)):
        raise PolicyError(f"{field} must be a list, got {type(value).__name__}")
    return tuple(str(item) for item in value)


def _as_int(value: object, field: str, default: int) -> int:
    if value is None:
        return default
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise PolicyError(f"{field} must be an integer, got {value!r}") from exc
    if number < 0:
        raise PolicyError(f"{field} must be >= 0, got {number}")
    return number


@dataclass(frozen=True)
class Policy:
    """Immutable snapshot of the governance rules."""

    allow_tools: frozenset[str] = frozenset()
    allow_prefixes: tuple[str, ...] = ()
    deny_segments: tuple[str, ...] = ()
    max_steps: int = 12
    max_tokens: int = 30_000
    min_searches_before_refusal: int = 0
    injection_patterns: tuple[str, ...] = ()
    action_keywords: tuple[str, ...] = ()
    quarantine_on_match: bool = True
    audit_path: str = "audit.jsonl"

    @classmethod
    def load(cls, path: Path) -> Policy:
        """Parse a policy file. Unknown top-level keys are ignored on purpose."""
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise PolicyError(f"{path} must contain a mapping at the top level")

        tools = raw.get("tools") or {}
        paths = raw.get("paths") or {}
        budget = raw.get("budget") or {}
        behaviour = raw.get("behavior") or {}
        content = raw.get("content") or {}
        audit = raw.get("audit") or {}

        return cls(
            allow_tools=frozenset(_as_tuple(tools.get("allow"), "tools.allow")),
            allow_prefixes=_as_tuple(paths.get("allow_prefix"), "paths.allow_prefix"),
            deny_segments=_as_tuple(paths.get("deny_segments"), "paths.deny_segments"),
            max_steps=_as_int(budget.get("max_steps"), "budget.max_steps", 12),
            max_tokens=_as_int(budget.get("max_tokens"), "budget.max_tokens", 30_000),
            min_searches_before_refusal=_as_int(
                behaviour.get("min_searches_before_refusal"),
                "behavior.min_searches_before_refusal",
                0,
            ),
            injection_patterns=_as_tuple(content.get("injection_patterns"), "content.injection_patterns"),
            action_keywords=_as_tuple(content.get("action_keywords"), "content.action_keywords"),
            quarantine_on_match=str(content.get("on_match", "quarantine")) == "quarantine",
            audit_path=str(audit.get("path", "audit.jsonl")),
        )
