"""ReAct loop: the agent's heartbeat.

How this file runs
------------------
``python -m harness.cli ask "..."`` -> ``cli.main`` -> ``run``.

``run`` is an orchestrator. It resolves the limits, builds a ``RunState`` and then
hands that state to one small stage function per turn:

1. ``_enforce_budget``   shrink history, or stop when compaction cannot help
2. ``_ask_model``        one chat call, recorded in the trace
3. ``_answer_or_retry``  accept the answer, or force one more search before a refusal
4. ``_execute_tools``    guard -> execute -> inspect output -> offload -> append

Every stage returns ``None`` to continue, or a ``RunResult`` when the run is over.
That is the whole control flow: no nested conditionals, no shared mutable flags.

Known limits (also listed in README): the loop is single-threaded, and the refusal
gate only helps when the model gave up after a single search.
"""

from __future__ import annotations

import json

from .context import compact, estimate_tokens, messages_tokens, offload
from .guard import Guard
from .llm import Reply
from .state import RunConfig, RunResult, RunState, Step
from .tools import REGISTRY, SCHEMAS
from .trace import NullTracer, Tracer

SYSTEM = (
    "You are a note-corpus assistant. Answer only from what the tools return.\n"
    "Cite every claim as [relative/path.md:line].\n"
    "If the tools do not contain the answer, say that the notes do not cover it."
)

# Tool schemas are sent on every request, so they must be counted in the budget.
# Leaving them out made every estimate about 25% low.
SCHEMA_TOKENS = estimate_tokens(json.dumps(SCHEMAS, ensure_ascii=False))

TRACE_RESULT_CHARS = 2000  # how much of a tool result is kept in the trace

# Refusal phrasings the model actually emits. The corpus is bilingual, so this
# detector has to be too. These are data, not comments.
REFUSAL_HINTS = ("not covered", "no information", "cannot find", "没有", "未找到", "不包含", "找不到", "不涉及")
RESEARCH_NUDGE = (
    "You searched only once before concluding the notes do not cover this. "
    "Search again with different keywords (synonyms, broader terms, English terms), "
    "then decide again. Only say it is not covered if it really is not."
)

__all__ = ["Step", "RunResult", "execute", "run"]


# --------------------------------------------------------------------- helpers


def parse_args(call: dict) -> tuple[dict, str | None]:
    """Parse tool arguments exactly once; return ``({}, reason)`` on bad input."""
    raw = call["function"].get("arguments") or "{}"
    try:
        args = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {}, f"bad_arguments_json: {exc}"
    if not isinstance(args, dict):
        return {}, "bad_arguments: arguments must be a JSON object"
    return args, None


def call_tool(name: str, args: dict) -> tuple[object, str | None]:
    """Execute a tool. A tool failure becomes data for the model, not an exception."""
    function = REGISTRY.get(name)
    if function is None:
        return {"error": f"unknown_tool: {name}"}, f"unknown_tool: {name}"
    try:
        return function(**args), None  # type: ignore[operator]
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}, f"{type(exc).__name__}: {exc}"


def execute(call: dict) -> tuple[object, str | None, dict]:
    """Parse + execute without governance. Kept for offline tests and scripts."""
    name = call["function"]["name"]
    args, error = parse_args(call)
    if error:
        return {"error": error}, error, {}
    result, error = call_tool(name, args)
    return result, error, args


def _config_from(guard: Guard | None, max_steps: int, token_budget: int) -> RunConfig:
    """Policy is the source of truth when a guard is supplied."""
    if guard is None:
        return RunConfig(max_steps=max_steps, token_budget=token_budget)
    policy = guard.policy
    return RunConfig(
        max_steps=policy.max_steps,
        token_budget=policy.max_tokens,
        min_searches_before_refusal=policy.min_searches_before_refusal,
    )


def _finish(state: RunState, answer: str, stopped_by: str, tracer: Tracer | NullTracer) -> RunResult:
    """Single exit point, so no ledger field can be forgotten."""
    tracer.log("end", stopped_by=stopped_by, tokens=state.usage.total, steps=len(state.steps))
    return RunResult.from_state(state, answer, stopped_by)


def _looks_like_refusal(answer: str) -> bool:
    return any(hint in answer.lower() for hint in REFUSAL_HINTS)


def _fallback_answer(steps: list[Step]) -> str:
    """When steps run out, hand back the last useful result instead of nothing."""
    usable = [step for step in steps if not step.error]
    if not usable:
        return "Ran out of steps without an answer."
    last = usable[-1]
    return f"Ran out of steps before summarising. Last {last.tool}({last.args}) returned: {last.result_preview[:200]}"


# ---------------------------------------------------------------------- stages


def _enforce_budget(
    state: RunState,
    llm,
    config: RunConfig,
    tracer: Tracer | NullTracer,
    verbose: bool,
) -> RunResult | None:
    """Compact first, then stop if the request would still exceed the budget."""
    messages, record = compact(state.messages, llm, config.token_budget, extra=SCHEMA_TOKENS)
    state.messages = messages
    if record:
        state.compactions += 1
        state.usage.prompt_tokens += record["summary_prompt_tokens"]
        state.usage.completion_tokens += record["summary_completion_tokens"]
        tracer.log("compact", **record)
        if verbose:
            print(f"[budget] compacted {record['before_tokens']} -> {record['after_tokens']} tokens")

    estimate = messages_tokens(state.messages, SCHEMA_TOKENS)
    if estimate <= config.token_budget:
        return None

    tracer.log("budget_stop", est_tokens=estimate, budget=config.token_budget)
    return _finish(state, f"Estimated {estimate} tokens exceeds the budget of {config.token_budget}.", "budget", tracer)


def _ask_model(state: RunState, llm, turn: int, tracer: Tracer | NullTracer) -> Reply:
    """One model call, with the estimate and the real usage both recorded."""
    estimate = messages_tokens(state.messages, SCHEMA_TOKENS)
    reply = llm.chat(state.messages, tools=SCHEMAS)
    state.usage.add(reply.usage)
    tracer.log(
        "reply",
        step=turn,
        est_prompt_tokens=estimate,
        usage={"prompt": reply.usage.prompt_tokens, "completion": reply.usage.completion_tokens},
        content=reply.content,
        tool_calls=[call["function"]["name"] for call in reply.tool_calls],
    )
    return reply


def _answer_or_retry(
    state: RunState,
    reply: Reply,
    config: RunConfig,
    turn: int,
    tracer: Tracer | NullTracer,
    verbose: bool,
) -> RunResult | None:
    """Accept the answer, or force one more search when it gave up too early."""
    answer = reply.content or ""
    if _should_force_research(state, answer, config):
        _force_research(state, answer, turn, tracer, verbose)
        return None

    if verbose:
        print(f"[loop] turn {turn}: model answered, stopping")
    return _finish(state, answer, "answer", tracer)


def _should_force_research(state: RunState, answer: str, config: RunConfig) -> bool:
    return (
        config.min_searches_before_refusal > 0
        and _looks_like_refusal(answer)
        and state.successful_searches() < config.min_searches_before_refusal
        and state.refusal_retries < config.max_refusal_retries
    )


def _force_research(
    state: RunState,
    answer: str,
    turn: int,
    tracer: Tracer | NullTracer,
    verbose: bool,
) -> None:
    """Nudge once, in-band, instead of changing the global system prompt."""
    state.refusal_retries += 1
    searches = state.successful_searches()
    tracer.log("refusal_retry", step=turn, searches=searches, answer=answer[:200])
    if verbose:
        print(f"[loop] turn {turn}: wanted to refuse after {searches} search(es), asking for another one")
    state.messages.append({"role": "assistant", "content": answer})
    state.messages.append({"role": "user", "content": RESEARCH_NUDGE})


def _execute_tools(
    state: RunState,
    reply: Reply,
    turn: int,
    tracer: Tracer | NullTracer,
    guard: Guard | None,
    verbose: bool,
) -> None:
    """Run every tool call in this reply and append the results."""
    state.messages.append({"role": "assistant", "content": reply.content or "", "tool_calls": reply.tool_calls})
    for call in reply.tool_calls:
        _handle_call(state, call, turn, tracer, guard, verbose)


def _handle_call(
    state: RunState,
    call: dict,
    turn: int,
    tracer: Tracer | NullTracer,
    guard: Guard | None,
    verbose: bool,
) -> None:
    """One tool call, end to end: guard, execute, inspect, offload, append."""
    name = call["function"]["name"]
    args, arg_error = parse_args(call)
    result, error = _run_guarded(name, args, arg_error, guard)
    payload, error = _inspect_output(json.dumps(result, ensure_ascii=False), error, name, guard)

    index = len(state.steps) + 1
    spilled = offload(payload, index, tracer.spill_dir)
    if spilled.truncated:
        state.offloads += 1
        tracer.log("offload", step=index, saved_chars=spilled.saved_chars, path=str(spilled.full_path))

    step = Step(
        index=index,
        tool=name,
        args=args,
        result_preview=payload[:120],
        error=error,
        offloaded=spilled.truncated,
    )
    state.steps.append(step)
    tracer.log(
        "tool",
        step=index,
        tool=name,
        args=args,
        error=error,
        result_chars=len(payload),
        result=payload[:TRACE_RESULT_CHARS],
        full_path=str(spilled.full_path) if spilled.truncated else None,
        offloaded=spilled.truncated,
    )
    if verbose:
        status = f"error {error}" if error else payload[:80]
        print(f"[loop] turn {turn}: {name}({args}) -> {status}{' [offloaded]' if spilled.truncated else ''}")
    state.messages.append({"role": "tool", "tool_call_id": call["id"], "content": spilled.payload})


def _run_guarded(name: str, args: dict, arg_error: str | None, guard: Guard | None) -> tuple[object, str | None]:
    """Governance before execution: an allow-list miss never reaches the tool."""
    if arg_error:
        return {"error": arg_error}, arg_error
    if guard:
        decision = guard.check_tool(name, args)
        if not decision.allowed:
            message = f"denied[{decision.rule}]: {decision.reason}"
            return {"error": message}, message
    return call_tool(name, args)


def _inspect_output(payload: str, error: str | None, name: str, guard: Guard | None) -> tuple[str, str | None]:
    """Governance after execution: content may carry instructions for the model."""
    if guard is None or error is not None:
        return payload, error
    decision = guard.check_content(payload, tool=name)
    if decision.allowed or not guard.policy.quarantine_on_match:
        return payload, error
    message = f"content_quarantined: {decision.reason}"
    return json.dumps({"error": message}, ensure_ascii=False), message


# --------------------------------------------------------------------- entry


def run(
    task: str,
    llm,
    max_steps: int = 12,
    token_budget: int = 30_000,
    tracer: Tracer | NullTracer | None = None,
    guard: Guard | None = None,
    verbose: bool = True,
) -> RunResult:
    """Run one task to completion and return the ledger."""
    config = _config_from(guard, max_steps, token_budget)
    state = RunState.start(SYSTEM, task)
    tracer = tracer or NullTracer()
    tracer.log("start", task=task, budget=config.token_budget, max_steps=config.max_steps)

    try:
        for turn in range(1, config.max_steps + 1):
            finished = _enforce_budget(state, llm, config, tracer, verbose)
            if finished:
                return finished

            reply = _ask_model(state, llm, turn, tracer)
            if not reply.wants_tool:
                finished = _answer_or_retry(state, reply, config, turn, tracer, verbose)
                if finished:
                    return finished
                continue

            _execute_tools(state, reply, turn, tracer, guard, verbose)
    except Exception as exc:
        # Record the termination before re-raising: otherwise the trace ends at
        # "start" and a crash is indistinguishable from a run that is still going.
        tracer.log("error", type=type(exc).__name__, message=str(exc)[:500], steps=len(state.steps))
        raise

    return _finish(state, _fallback_answer(state.steps), "max_steps", tracer)

