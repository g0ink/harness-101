"""Offline self-check: pin down every error path.

Run: ``python scripts/selftest.py``

Why this exists: error paths never appear in a demo, only in production. It needs no
model and no network, so it runs in two seconds and can gate every commit.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import context as ctx  # noqa: E402
from harness.llm import MissingToken, Reply, Usage  # noqa: E402
from harness.loop import Step, _fallback_answer, execute, run  # noqa: E402
from harness.trace import Tracer, replay  # noqa: E402
from scripts.probe_toolcall import validate  # noqa: E402

CASES: list[tuple[str, bool]] = []


def check(name: str, condition: bool) -> None:
    CASES.append((name, condition))
    print(f"{'PASS' if condition else 'FAIL'}  {name}")


def call(name: str, arguments: str) -> dict:
    return {"id": "c1", "type": "function", "function": {"name": name, "arguments": arguments}}


def _no_orphans(messages: list[dict]) -> bool:
    """Every tool message must have an assistant tool_call that asked for it."""
    seen: set[str] = set()
    for message in messages:
        if message.get("role") == "assistant":
            for call_id in message.get("tool_calls") or []:
                seen.add(call_id["id"])
        elif message.get("role") == "tool" and message.get("tool_call_id") not in seen:
            return False
    return True


# --- execute: the three error paths -----------------------------------------
result, error, args = execute(call("search_notes", "{query: token budget"))
check("bad JSON returns an error instead of raising", error is not None and isinstance(result, dict))
check("bad JSON degrades arguments to an empty dict", args == {})

_, error, _ = execute(call("delete_all_notes", "{}"))
check("unknown tool is rejected", error is not None and "unknown_tool" in error)

_, error, _ = execute(call("search_notes", '["token"]'))
check("non-object arguments are rejected", error is not None and "JSON object" in error)

_, error, _ = execute(call("read_note", '{"path": "../../.ssh/id_rsa"}'))
check("path escape becomes an error, not a crash", error is not None and "PermissionError" in error)

for bad_path in ("corpusX/y.md", "corpus/../corpusX/b.md", "corpus/../../etc/passwd"):
    _, error, _ = execute(call("read_note", json.dumps({"path": bad_path})))
    check(f"bypass attempt blocked: {bad_path}", error is not None and "path_denied" in error)


# --- schema validation used by the probe ------------------------------------
check("wrong argument name is caught", validate(call("search_notes", '{"keyword": "token"}')) is not None)
check("wrong argument type is caught", validate(call("search_notes", '{"query": 123}')) is not None)
check("valid call passes validation", validate(call("search_notes", '{"query": "token", "k": 5}')) is None)


# --- token resolution: env, .env file, and the missing case -----------------
def _token_cases() -> None:
    import os

    import harness.llm as llm_module

    original = llm_module.ENV_FILE
    saved = os.environ.pop("LM_API_TOKEN", None)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            llm_module.ENV_FILE = Path(tmp) / "missing.env"
            try:
                llm_module.load_token()
                check("missing token raises MissingToken", False)
            except MissingToken:
                check("missing token raises MissingToken", True)

            env_file = Path(tmp) / ".env"
            env_file.write_text("# comment\nLM_API_TOKEN=abc123\n", encoding="utf-8")
            llm_module.ENV_FILE = env_file
            check(".env file is parsed", llm_module.load_token() == "abc123")

            os.environ["LM_API_TOKEN"] = "from" + "-env"  # fixture, not a secret
            check("environment wins over .env", llm_module.load_token() == "from-env")
            os.environ.pop("LM_API_TOKEN")
    finally:
        llm_module.ENV_FILE = original
        if saved is not None:
            os.environ["LM_API_TOKEN"] = saved


_token_cases()


# --- context: estimate, offload, compaction ---------------------------------
check("empty string costs zero tokens", ctx.estimate_tokens("") == 0)
check("CJK costs more than the same length of ASCII", ctx.estimate_tokens("上下文压缩") > ctx.estimate_tokens("abcdef"))
check(
    "messages_tokens counts tool arguments",
    ctx.messages_tokens([{"role": "assistant", "tool_calls": [call("search_notes", '{"query":"token"}')]}]) > 0,
)

with tempfile.TemporaryDirectory() as tmp:
    spill = Path(tmp)
    short = ctx.offload("x" * 100, 1, spill)
    check("short output is not offloaded", not short.truncated and short.full_path is None)

    long = ctx.offload("y" * (ctx.OFFLOAD_THRESHOLD + 3000), 2, spill)
    check("long output is offloaded", long.truncated and len(long.payload) < 5000)
    check("offloaded full text is on disk", long.full_path is not None and long.full_path.is_file())
    check("offloaded payload carries a marker", "omitted" in long.payload)
    check(
        "one read page never hits the offload gate",
        ctx.OFFLOAD_THRESHOLD > 3000,  # tools.MAX_READ_CHARS
    )

orphan_tail = [
    {"role": "system", "content": "s"},
    {"role": "assistant", "tool_calls": [call("search_notes", "{}")]},
    {"role": "tool", "tool_call_id": "c1", "content": "r"},
    {"role": "assistant", "content": "a"},
]
check("tail never starts on an orphan tool message", ctx._safe_tail(orphan_tail, 3)[0]["role"] != "tool")

pair_tail = [
    {"role": "system", "content": "s"},
    {"role": "assistant", "tool_calls": [call("search_notes", "{}")]},
    {"role": "tool", "tool_call_id": "c1", "content": "r"},
]
kept = ctx._safe_tail(pair_tail, 2)
check("a complete call/result pair survives", len(kept) == 2 and kept[0]["role"] == "assistant")


class _SummaryLLM:
    """Stands in for the model only to exercise the compaction path."""

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages, tools=None) -> Reply:  # noqa: ANN001
        self.calls += 1
        return Reply(content="- fact: the user asked X\n- cite: corpus/memory.md:79", usage=Usage(100, 20))


history = [{"role": "system", "content": "s"}, {"role": "user", "content": "question"}]
history += [{"role": "assistant", "content": "long history " * 200} for _ in range(6)]
summariser = _SummaryLLM()
compacted, record = ctx.compact(history, summariser, budget=1000, keep_recent=2)
check("over-budget history is compacted", record is not None and summariser.calls == 1)
check("compaction lowers the token count", record is not None and record["after_tokens"] < record["before_tokens"])
check("compaction keeps the system prompt", compacted[0]["content"] == "s")
check("compaction inserts a summary message", "[compacted history]" in compacted[1]["content"])

_, no_record = ctx.compact([{"role": "system", "content": "s"}], _SummaryLLM(), budget=1000)
check("under-budget history is left alone", no_record is None)


# --- loop: bad arguments must not kill the run ------------------------------
class _BadArgsLLM:
    """Returns malformed arguments once, then an answer."""

    def __init__(self) -> None:
        self.turn = 0

    def chat(self, messages, tools=None) -> Reply:  # noqa: ANN001
        self.turn += 1
        if self.turn == 1:
            return Reply(tool_calls=[call("search_notes", "{query: broken")], usage=Usage(10, 5))
        return Reply(content="ok", usage=Usage(10, 5))


outcome = run("test", _BadArgsLLM(), verbose=False)
check("bad arguments do not abort the run", outcome.answer == "ok")
check("bad arguments are recorded in the ledger", bool(outcome.steps) and outcome.steps[0].error is not None)
check("the ledger keeps the token count", outcome.usage.total > 0)
check("the ledger keeps the step count", len(outcome.steps) == 1)
check("the run reports why it stopped", outcome.stopped_by == "answer")


# --- fallback: hand back the last useful result -----------------------------
fallback_steps = [
    Step(index=1, tool="search_notes", args={"query": "a"}, result_preview="S"),
    Step(index=2, tool="read_note", args={"path": "corpus/x.md"}, result_preview="R"),
]
check("fallback uses the last successful step", "read_note" in _fallback_answer(fallback_steps))
check(
    "fallback says so when nothing succeeded",
    _fallback_answer([Step(index=1, tool="read_note", args={}, error="boom")]) == "Ran out of steps without an answer.",
)


# --- a 15-turn chain: no window overflow, no orphans, replayable ------------
class _LoopLLM:
    """Always asks for a tool; returns a short summary when asked to compact."""

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages, tools=None) -> Reply:  # noqa: ANN001
        if "Compress the conversation" in (messages[0].get("content") or ""):
            return Reply(content="- fact: compacted", usage=Usage(50, 10))
        self.calls += 1
        return Reply(tool_calls=[call("search_notes", '{"query":"compaction"}')], usage=Usage(200, 20))


with tempfile.TemporaryDirectory() as tmp:
    tracer = Tracer(Path(tmp))
    chain_llm = _LoopLLM()
    chain = run("fifteen turns", chain_llm, max_steps=15, token_budget=2000, tracer=tracer, verbose=False)
    events = replay(tracer.path)
    replies = [event for event in events if event["kind"] == "reply"]
    check("the chain really ran many turns", len(replies) >= 10)
    check("every turn stayed inside the budget", all(event["est_prompt_tokens"] <= 2000 for event in replies))
    check("no orphan tool messages after 15 turns", _no_orphans(chain.messages))
    check("the chain compacted at least once", chain.compactions > 0)
    check(
        "the trace has both start and end",
        any(event["kind"] == "start" for event in events) and any(event["kind"] == "end" for event in events),
    )
    check("the trace kept tool output", any(event.get("result") for event in events if event["kind"] == "tool"))

# --- a single oversized message: stop instead of sending a doomed request ---
huge_llm = _LoopLLM()
huge = run("long " * 50_000, huge_llm, max_steps=5, token_budget=2000, verbose=False)
check("an oversized input is stopped by the budget gate", huge.stopped_by == "budget")
check("no model call is made once over budget", huge_llm.calls == 0)


failed = [name for name, ok in CASES if not ok]
print(f"\n{len(CASES) - len(failed)}/{len(CASES)} passed")
sys.exit(1 if failed else 0)
