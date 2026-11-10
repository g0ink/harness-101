"""Context budget: estimate, offload, compact.

How this file is used
---------------------
``harness.loop.run`` calls, once per turn:

1. ``compact``   -- before asking the model, shrink history if it is over budget
2. ``offload``   -- before appending a tool result, keep head+tail and spill the rest
3. ``estimate_tokens`` / ``messages_tokens`` -- the numbers both stages decide on

Scope rule: this layer only shapes *volume*. Judging relevance is the model's job.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

# Character-class coefficients. Calibrated with scripts/measure_tokens.py against
# the local Qwen3 tokenizer; re-measure before trusting them on another model.
#   CJK ideographs ~1.6 chars/token (common words get merged)
#   kana / emoji / other non-ASCII ~1 char/token (each kana is close to one token)
#   ASCII ~4 chars/token
CJK_CHARS_PER_TOKEN = 1.6
OTHER_NON_ASCII_PER_TOKEN = 1.0
LATIN_CHARS_PER_TOKEN = 4

# A bounded document read must never be truncated by this gate: 1500 was small
# enough to cut a 44-line file in half, and the model then reported the answer as
# missing. Offload exists for unbounded dumps, so the threshold sits above what a
# single read_note call may return (MAX_READ_CHARS in tools.py).
OFFLOAD_THRESHOLD = 6000
HEAD_CHARS = 500
TAIL_CHARS = 500

SUMMARIZER = (
    "Compress the conversation below into bullet points. Keep only: "
    "1) facts that were confirmed, 2) file paths and line numbers that were cited, "
    "3) actions still pending. No commentary, no restating the source."
)


def _is_cjk(char: str) -> bool:
    return "\u4e00" <= char <= "\u9fff" or "\u3400" <= char <= "\u4dbf"


def estimate_tokens(text: str) -> int:
    """Rough token count for a string. Empty input is zero.

    Deliberately an over-estimate: a budget gate should brake early rather than
    send a request that is certain to fail.
    """
    if not text:
        return 0
    cjk = kana = latin = 0
    for char in text:
        if _is_cjk(char):
            cjk += 1
        elif ord(char) > 0x7F:
            kana += 1
        else:
            latin += 1
    return int(cjk / CJK_CHARS_PER_TOKEN + kana / OTHER_NON_ASCII_PER_TOKEN + latin / LATIN_CHARS_PER_TOKEN) + 1


def messages_tokens(messages: list[dict], extra: int = 0) -> int:
    """Estimate a whole request.

    ``extra`` carries what is sent every turn but is not part of ``messages`` --
    the tool schemas. Leaving them out made every estimate ~25% low.
    """
    total = extra
    for message in messages:
        total += estimate_tokens(message.get("content") or "")
        for call in message.get("tool_calls") or []:
            total += estimate_tokens(json.dumps(call, ensure_ascii=False))
    return total


@dataclass
class Offloaded:
    """Result of a truncation: what the model sees, plus where the rest went."""

    payload: str
    truncated: bool
    full_path: Path | None = None
    saved_chars: int = 0


def offload(
    payload: str,
    step: int,
    spill_dir: Path,
    threshold: int = OFFLOAD_THRESHOLD,
    head: int = HEAD_CHARS,
    tail: int = TAIL_CHARS,
) -> Offloaded:
    """Keep the head and tail of a long tool result, spill the whole thing to disk.

    Head and tail are kept because the head usually carries structure (JSON opening,
    table header) and the tail usually carries the conclusion or the total. The
    middle is the cheapest part to lose.
    """
    if len(payload) <= threshold:
        return Offloaded(payload=payload, truncated=False)

    spill_dir.mkdir(parents=True, exist_ok=True)
    full_path = spill_dir / f"tool_{step:02d}.json"
    full_path.write_text(payload, encoding="utf-8")

    # The marker is actionable: a bare character count tells the model nothing about
    # how to see the rest, so it either guesses or gives up.
    short = (
        payload[:head]
        + f"\n... [{len(payload) - head - tail} characters omitted; "
        + "call the same tool again with a narrower range to see them] ...\n"
        + payload[-tail:]
    )
    return Offloaded(payload=short, truncated=True, full_path=full_path, saved_chars=len(payload) - len(short))


def _safe_tail(messages: list[dict], keep_recent: int) -> list[dict]:
    """Take the last few messages without starting on an orphan ``tool`` message.

    Protocol rule: an ``assistant`` message with ``tool_calls`` must be followed by
    one ``tool`` message per call id. Slicing history can leave a ``tool`` message
    whose caller moved into the summarised middle; the API answers that with 400.

    A leading ``assistant(tool_calls)`` is *not* dropped: its results follow right
    after it, so the pair is intact.
    """
    tail = messages[-keep_recent:]
    while tail and tail[0].get("role") == "tool":
        tail = tail[1:]
    return tail


def compact(
    messages: list[dict],
    llm,
    budget: int,
    keep_recent: int = 4,
    ratio: float = 0.8,
    extra: int = 0,
) -> tuple[list[dict], dict | None]:
    """Summarise the middle of the history when the request is close to budget.

    Keeps the original system prompt, one summary message, and the recent tail.
    Returns ``(messages, record)``; ``record`` is ``None`` when nothing happened and
    otherwise carries the cost of the summary call, which the caller must add to its
    own usage ledger.
    """
    used = messages_tokens(messages, extra)
    if used <= budget * ratio or len(messages) <= keep_recent + 2:
        return messages, None

    head = messages[0]
    tail = _safe_tail(messages, keep_recent)
    middle = messages[1 : len(messages) - len(tail)]
    if not middle:
        return messages, None

    reply = llm.chat(
        [
            {"role": "system", "content": SUMMARIZER},
            {"role": "user", "content": json.dumps(middle, ensure_ascii=False)},
        ]
    )
    summary = (reply.content or "").strip() or "(empty summary)"
    new_messages = [head, {"role": "system", "content": "[compacted history]\n" + summary}, *tail]

    record = {
        "before_tokens": used,
        "after_tokens": messages_tokens(new_messages, extra),
        "dropped_messages": len(middle),
        "summary_tokens": estimate_tokens(summary),
        "summary_prompt_tokens": reply.usage.prompt_tokens,
        "summary_completion_tokens": reply.usage.completion_tokens,
    }
    return new_messages, record
