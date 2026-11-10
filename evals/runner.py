"""Eval runner: orchestration only.

How this file runs
------------------
    python evals/runner.py --verify-only     # check the task set can be scored
    python evals/runner.py --limit 3         # smoke test
    python evals/runner.py --tag baseline    # full run, results written to disk

Three parts, kept separate on purpose:

    task    evals/tasks.jsonl          question plus rubric
    solver  harness.loop.run           the thing under test
    scorer  evals/scoring.py           pure functions, no model involved

Discipline: temperature is fixed at 0, and every result records the model name and
the timestamp. A number without a model name is not evidence.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
LAB = HERE.parent
sys.path.insert(0, str(LAB))

from evals import scoring  # noqa: E402
from harness.guard import Guard  # noqa: E402
from harness.llm import MODEL, build  # noqa: E402
from harness.loop import run  # noqa: E402
from harness.trace import Tracer, new_run_dir  # noqa: E402

TASKS = HERE / "tasks.jsonl"
CORPUS = LAB / "corpus"


def _select(tasks: list[dict], kind: str, limit: int) -> list[dict]:
    chosen = [task for task in tasks if not kind or task["kind"] == kind]
    return chosen[:limit] if limit else chosen


def _run_all(tasks: list[dict], llm, guard: Guard, run_dir: Path) -> tuple[list[dict], list[float], list[int]]:
    """Execute every task and return rows, latencies and token counts."""
    rows: list[dict] = []
    latencies: list[float] = []
    tokens: list[int] = []

    for index, task in enumerate(tasks, 1):
        tracer = Tracer(run_dir / task["id"])
        started = time.time()
        result = run(task["question"], llm, tracer=tracer, guard=guard, verbose=False)
        elapsed = time.time() - started

        detail = scoring.judge(task, result)
        rows.append(detail)
        latencies.append(elapsed)
        tokens.append(result.usage.total)

        mark = "PASS" if detail["passed"] else "FAIL"
        print(f"{index:>2}. {mark} {task['id']:<4} {elapsed:5.1f}s {result.usage.total:>6} tok  {task['question'][:40]}")
    return rows, latencies, tokens


def _summarise(rows: list[dict], latencies: list[float], tokens: list[int], model: str, stamp: str) -> dict:
    answered = [row for row in rows if row["kind"] != "adversarial"]
    adversarial = [row for row in rows if row["kind"] == "adversarial"]
    modes = {
        mode: sum(1 for row in adversarial if row.get("mode") == mode)
        for mode in ("blocked", "safe_no_action", "attempted_allowed")
    }
    return {
        "model": model,
        "at": stamp,
        "tasks": len(rows),
        "success_rate": round(sum(row["passed"] for row in answered) / len(answered), 3) if answered else None,
        "adversarial_safe_rate": round(sum(row["passed"] for row in adversarial) / len(adversarial), 3)
        if adversarial
        else None,
        "guard_block_rate": round(modes["blocked"] / len(adversarial), 3) if adversarial else None,
        "adversarial_modes": modes,
        "avg_tokens": round(statistics.mean(tokens), 1) if tokens else None,
        "p50_latency_s": round(statistics.median(latencies), 1) if latencies else None,
    }


def _write_report(metrics: dict, rows: list[dict], citations: tuple[int, int], suffix: str) -> Path:
    path = HERE / f"report{suffix}.md"
    ok, total = citations
    lines = [
        "# eval report",
        "",
        f"- model: `{metrics['model']}`",
        f"- run at: {metrics['at']}",
        f"- tasks: {metrics['tasks']}",
        "",
        "| metric | value | denominator |",
        "|---|---|---|",
        f"| success rate | {metrics['success_rate']} | {sum(1 for r in rows if r['kind'] != 'adversarial')} answerable tasks |",
        f"| adversarial safe rate | {metrics['adversarial_safe_rate']} | {sum(1 for r in rows if r['kind'] == 'adversarial')} adversarial tasks |",
        f"| blocked by guard | {metrics['guard_block_rate']} | same set; modes {metrics['adversarial_modes']} |",
        f"| citation precision | {round(ok / total, 3) if total else None} | {total} citations |",
        f"| average tokens | {metrics['avg_tokens']} | {len(rows)} runs |",
        f"| median latency | {metrics['p50_latency_s']}s | {len(rows)} runs |",
        "",
        "## failures",
        "",
    ]
    for row in rows:
        if row["passed"]:
            continue
        lines.append(f"- **{row['id']}** ({row['kind']}): {row.get('note') or row.get('checks')}")
        lines.append(f"  - answer: {row['answer'][:160]}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--kind", default="", help="single | multi | long | refusal | adversarial")
    parser.add_argument("--tag", default="", help="suffix for report/results files")
    args = parser.parse_args()

    tasks = _select(scoring.load_tasks(TASKS), args.kind, args.limit)
    if args.verify_only:
        return scoring.verify(tasks, CORPUS)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = f"-{args.tag}" if args.tag else ""
    run_dir = new_run_dir(LAB / "runs" / "eval", f"{stamp}-{args.model}")
    llm = build(args.model)
    guard = Guard()

    print(f"[eval] {len(tasks)} tasks / model {args.model} / trace {run_dir}\n")
    rows, latencies, tokens = _run_all(tasks, llm, guard, run_dir)

    citations = (0, 0)
    for task, row in zip(tasks, rows, strict=False):
        ok, total = scoring.score_citation(task, row["answer"], LAB)
        citations = (citations[0] + ok, citations[1] + total)

    metrics = _summarise(rows, latencies, tokens, args.model, stamp)
    report = _write_report(metrics, rows, citations, suffix)
    (HERE / f"results{suffix}.json").write_text(
        json.dumps({"metrics": metrics, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    print("\n--- metrics ---")
    for key, value in metrics.items():
        print(f"{key:<22} {value}")
    print(f"\nreport: {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
