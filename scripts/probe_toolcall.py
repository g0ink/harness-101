"""Probe how reliably the model produces a valid tool call.

Run: ``python scripts/probe_toolcall.py --n 10``

Why this exists: a small model often emits broken JSON or an argument name that is not
in the schema. When that happens the eval scores zero and looks like a reasoning
problem. Measure the tool-call format first.

A call counts as valid only if all three hold:

1. a tool call was produced instead of prose
2. ``arguments`` is a JSON object
3. every argument passes the schema check in ``validate`` (required fields, names,
   types) -- otherwise execution fails later with a TypeError
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.llm import MODEL, build  # noqa: E402
from harness.tools import SCHEMAS  # noqa: E402

PROMPTS = [
    "Search the corpus for what compaction means",
    "Show me how read_note is used",
    "What does the corpus say about token budgets",
    "Look up prompt injection",
    "Find content about evaluation",
    "The part about the context window",
    "What is a harness",
    "Search for embedding and vector databases",
    "Is there anything about traces",
    "Find the governance policy section",
]

# JSON schema type -> Python type. bool is a subclass of int, so it is rejected
# separately for integer fields.
PY_TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool}


def validate(call: dict) -> str | None:
    """Check one tool call against SCHEMAS. Returns None when valid."""
    function = call["function"]
    name = function["name"]
    schema = next((s["function"] for s in SCHEMAS if s["function"]["name"] == name), None)
    if schema is None:
        return f"tool not in registry: {name!r}"

    raw = function.get("arguments") or ""
    try:
        args = json.loads(raw)
    except json.JSONDecodeError as exc:
        return f"arguments are not valid JSON ({exc})"
    if not isinstance(args, dict):
        return "arguments are not a JSON object"

    params = schema["parameters"]
    for required in params.get("required", []):
        if required not in args:
            return f"missing required argument: {required}"
    for key, value in args.items():
        spec = params.get("properties", {}).get(key)
        if spec is None:
            return f"argument not in schema: {key}"
        wanted = spec.get("type")
        expected = PY_TYPES.get(wanted)
        if expected is None:
            continue
        if wanted == "integer" and isinstance(value, bool):
            return f"argument {key} should be integer, got boolean"
        if not isinstance(value, expected):
            return f"argument {key} should be {wanted}, got {type(value).__name__}"
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--n", type=int, default=10)
    args = parser.parse_args()

    count = min(args.n, len(PROMPTS))  # the denominator must be what actually ran
    if args.n > len(PROMPTS):
        print(f"[warn] only {len(PROMPTS)} prompts available, measuring {count}\n")

    llm = build(args.model)
    valid = 0
    print(f"model {args.model} / {count} attempts\n")
    for index, prompt in enumerate(PROMPTS[:count], 1):
        reply = llm.chat(
            [
                {"role": "system", "content": "You must call a tool. Do not answer directly."},
                {"role": "user", "content": prompt},
            ],
            tools=SCHEMAS,
        )
        if not reply.tool_calls:
            print(f"{index:>2}. FAIL: no tool call, answered {reply.content!r:.60}")
            continue
        call = reply.tool_calls[0]
        reason = validate(call)
        if reason:
            print(f"{index:>2}. FAIL: {reason}  <- {call['function'].get('arguments')!r:.60}")
            continue
        valid += 1
        print(f"{index:>2}. OK: {call['function']['name']}({call['function']['arguments'][:50]})")

    rate = valid / count
    print(f"\nvalid {valid}/{count} = {rate:.0%}  ->  {'usable' if rate >= 0.8 else 'switch model'}")
    return 0 if rate >= 0.8 else 1


if __name__ == "__main__":
    sys.exit(main())
