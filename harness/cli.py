"""Command line entry point.

How this file runs
------------------
``./bin/ask.sh "question"`` (or ``python -m harness.cli ask "question"``) lands in
``main``. It builds the three collaborators and hands them to ``loop.run``:

    ChatLLM   -> which model to talk to
    Guard     -> which rules to enforce (policy.yaml)
    Tracer    -> where the run is recorded (runs/<timestamp>/)

Nothing else lives here on purpose: the CLI is a thin edge, so the loop stays
testable without a terminal.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .guard import Guard
from .llm import MODEL, build
from .loop import run
from .trace import NullTracer, Tracer, new_run_dir

RUNS = Path(__file__).resolve().parents[1] / "runs"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="harness", description="A small vertical agent harness.")
    sub = parser.add_subparsers(dest="command", required=True)

    ask = sub.add_parser("ask", help="ask one question")
    ask.add_argument("question")
    ask.add_argument("--model", default=MODEL, help="model key as shown by `lms ls`")
    ask.add_argument("--max-steps", type=int, default=12)
    ask.add_argument("--budget", type=int, default=30_000, help="token budget per run")
    ask.add_argument("--no-guard", action="store_true", help="disable governance (for comparison)")
    ask.add_argument("--no-trace", action="store_true")
    ask.add_argument("--quiet", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    llm = build(args.model)
    guard = None if args.no_guard else Guard()
    tracer = NullTracer() if args.no_trace else Tracer(new_run_dir(RUNS, args.question))

    print(f"[harness] model={args.model} budget={args.budget} guard={'off' if guard is None else 'on'}")
    result = run(
        args.question,
        llm,
        max_steps=args.max_steps,
        token_budget=args.budget,
        tracer=tracer,
        guard=guard,
        verbose=not args.quiet,
    )

    print("\n--- answer ---")
    print(result.answer)
    print("\n--- ledger ---")
    print(
        f"tool calls {len(result.steps)} / tokens {result.usage.total}"
        f" / compactions {result.compactions} / offloads {result.offloads}"
        f" / stopped_by {result.stopped_by}"
    )
    if tracer.path:
        print(f"trace: {tracer.path}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
