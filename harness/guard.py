"""Governance: turn "what the agent may do" into deterministic code.

How this file is used
---------------------
``harness.loop`` calls three entry points, one per moment:

* ``check_tool``    -- before running a tool (allow-list + path rules)
* ``check_content`` -- after a tool returns (indirect prompt injection)
* ``check_budget``  -- at the top of a turn (steps, tokens)

Each entry point decides *and* writes an audit line in the same call, so there is no
"checked it but forgot to log it" path.

Three properties carry all the value here
-----------------------------------------
1. single choke point -- every decision happens here, not scattered inside tools
2. rules are data    -- policy.yaml changes behaviour without a code change
3. audit is mandatory -- allow and deny are both recorded, with the rule that fired
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from .config import Policy

HERE = Path(__file__).resolve().parents[1]  # repository root
DEFAULT_POLICY = HERE / "policy.yaml"


@dataclass(frozen=True)
class Decision:
    """Outcome of one check. ``rule`` names the YAML key that fired."""

    allowed: bool
    rule: str
    reason: str


ALLOW = Decision(True, "allow", "matched the allow-list")


def _deny(rule: str, reason: str) -> Decision:
    return Decision(False, rule, reason)


class Guard:
    """Policy evaluator plus audit log."""

    def __init__(self, policy_path: Path = DEFAULT_POLICY, audit_path: Path | None = None):
        self.policy_path = Path(policy_path)
        self.policy = Policy.load(self.policy_path)
        self.audit_path = Path(audit_path or HERE / self.policy.audit_path)
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ checks

    def check_tool(self, tool: str, args: dict, stage: str = "tool_call") -> Decision:
        decision = self._eval_tool(tool, args)
        self._audit(stage, decision, tool=tool, args=args)
        return decision

    def check_content(self, text: str, stage: str = "tool_output", tool: str | None = None) -> Decision:
        decision = self._eval_content(text)
        self._audit(stage, decision, tool=tool, chars=len(text))
        return decision

    def check_budget(self, steps: int, tokens: int, stage: str = "budget") -> Decision:
        decision = self._eval_budget(steps, tokens)
        self._audit(stage, decision, steps=steps, tokens=tokens)
        return decision

    # ------------------------------------------------------------- evaluation

    def _eval_tool(self, tool: str, args: dict) -> Decision:
        if tool not in self.policy.allow_tools:
            return _deny("tools.allow", f"tool {tool!r} is not allow-listed ({sorted(self.policy.allow_tools)})")
        path = args.get("path")
        return ALLOW if path is None else self._eval_path(str(path))

    def _eval_path(self, path: str) -> Decision:
        for segment in self.policy.deny_segments:
            if segment and segment in path:
                return _deny("paths.deny_segments", f"path contains forbidden segment {segment!r}: {path}")

        prefixes = self.policy.allow_prefixes
        if prefixes and not path.startswith(prefixes):
            return _deny("paths.allow_prefix", f"path is outside allowed prefixes {list(prefixes)}: {path}")
        return ALLOW

    def _eval_content(self, text: str) -> Decision:
        """Two-stage test, because a single stage always over-blocks.

        A note that *describes* an injection contains the same words as the
        injection. So: pattern alone means "suspicious, log it"; pattern plus an
        action keyword means "block it".
        """
        lowered = text.lower()
        hit = next((p for p in self.policy.injection_patterns if p and p.lower() in lowered), None)
        if hit is None:
            return ALLOW

        actions = [a for a in self.policy.action_keywords if a and a.lower() in lowered]
        if actions:
            return _deny("content.quarantine", f"injection pattern {hit!r} together with action words {actions[:2]}")
        return Decision(True, "content.flag", f"pattern {hit!r} without an action word -- logged, not blocked")

    def _eval_budget(self, steps: int, tokens: int) -> Decision:
        if steps > self.policy.max_steps:
            return _deny("budget.max_steps", f"{steps} steps exceed the limit of {self.policy.max_steps}")
        if tokens > self.policy.max_tokens:
            return _deny("budget.max_tokens", f"{tokens} tokens exceed the limit of {self.policy.max_tokens}")
        return ALLOW

    # ----------------------------------------------------------------- audit

    def _audit(self, stage: str, decision: Decision, **fields: object) -> None:
        """Append one JSON line per decision. Never rewrites history."""
        line = {
            "t": round(time.time(), 3),
            "stage": stage,
            "allowed": decision.allowed,
            "rule": decision.rule,
            "reason": decision.reason,
            **fields,
        }
        with self.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")
