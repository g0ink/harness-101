"""Data carried through one run.

How this file is used
---------------------
``harness.loop.run`` creates a ``RunState`` and passes it to small stage functions
(``_enforce_budget``, ``_ask_model``, ``_execute_tool_calls``). Each stage mutates
the state it is given and returns a ``RunResult`` only when the run is over.

Why a mutable state object
--------------------------
The first version kept ``messages``, ``steps``, ``usage``, ``compactions``,
``offloads`` and ``retries`` as separate locals and copied them into the result at
the end. Two of those copies were forgotten, and the CLI reported "0 tool calls /
0 tokens" while the trace clearly showed otherwise. Carrying one object removes
that whole class of bug.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .llm import Usage


@dataclass
class Step:
    """One executed tool call, as recorded in the run ledger."""

    index: int
    tool: str
    args: dict = field(default_factory=dict)
    result_preview: str = ""
    error: str | None = None
    offloaded: bool = False


@dataclass
class RunConfig:
    """Effective limits for one run, resolved from policy.yaml when present."""

    max_steps: int = 12
    token_budget: int = 30_000
    min_searches_before_refusal: int = 0
    max_refusal_retries: int = 1


@dataclass
class RunState:
    """Everything one run needs to keep between stages."""

    messages: list[dict]
    steps: list[Step] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    compactions: int = 0
    offloads: int = 0
    refusal_retries: int = 0

    @classmethod
    def start(cls, system: str, task: str) -> RunState:
        return cls(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": task},
            ]
        )

    def successful_searches(self) -> int:
        """Searches that actually returned something, used by the refusal gate."""
        return sum(1 for step in self.steps if step.tool == "search_notes" and not step.error)


@dataclass
class RunResult:
    """What the caller gets back. ``stopped_by`` explains why the loop ended."""

    answer: str
    steps: list[Step] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    messages: list[dict] = field(default_factory=list)
    compactions: int = 0
    offloads: int = 0
    stopped_by: str = "answer"  # answer | max_steps | budget

    @property
    def ok(self) -> bool:
        return self.stopped_by == "answer" and bool(self.answer)

    @classmethod
    def from_state(cls, state: RunState, answer: str, stopped_by: str) -> RunResult:
        return cls(
            answer=answer,
            steps=state.steps,
            usage=state.usage,
            messages=state.messages,
            compactions=state.compactions,
            offloads=state.offloads,
            stopped_by=stopped_by,
        )
