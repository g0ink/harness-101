"""Trace: append-only JSONL record of one run.

How this file is used
---------------------
``harness.loop.run`` creates one ``Tracer`` per run and calls ``log(kind, **fields)``
at each stage. ``NullTracer`` is the same interface with no output, so call sites
never branch on "is tracing enabled".

Why it exists
-------------
1. A non-deterministic system cannot be debugged from memory: a rerun is a
   different run.
2. Failure attribution needs the evidence the model actually saw.
3. ``python -m harness.trace <file>`` replays any run after the fact.

Format: one JSON object per line, append-only.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path


class Tracer:
    """Writes events into ``<run_dir>/trace.jsonl``."""

    def __init__(self, run_dir: Path):
        self.run_dir = Path(run_dir)
        self.spill_dir = self.run_dir / "offload"
        self.path = self.run_dir / "trace.jsonl"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")
        self.counts: dict[str, int] = {}

    def log(self, kind: str, **fields: object) -> None:
        self.counts[kind] = self.counts.get(kind, 0) + 1
        line = {"t": round(time.time(), 3), "kind": kind, **fields}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")

    def summary(self) -> dict:
        return {"path": str(self.path), "events": self.counts, "total": sum(self.counts.values())}


class NullTracer:
    """Null object: identical interface, writes nothing.

    Without this, every log call needs ``if tracer:``. Seven of those had already
    appeared in the loop, and each new one is a chance to forget the guard.
    """

    def __init__(self, spill_dir: Path | None = None):
        self._spill = spill_dir
        self.path: Path | None = None

    @property
    def spill_dir(self) -> Path:
        if self._spill is None:
            import tempfile

            self._spill = Path(tempfile.mkdtemp(prefix="harness-spill-"))
        return self._spill

    def log(self, kind: str, **fields: object) -> None:
        return None

    def summary(self) -> dict:
        return {"path": None, "events": {}, "total": 0}


def new_run_dir(base: Path, label: str = "") -> Path:
    """One directory per run, timestamp first so ``ls`` sorts chronologically."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = "".join(char if char.isalnum() or char in "-_" else "-" for char in label)[:24].strip("-")
    return Path(base) / (f"{stamp}-{slug}" if slug else stamp)


def replay(path: Path, limit: int = 500) -> list[dict]:
    """Read a trace back for humans and scripts."""
    if not Path(path).is_file():
        return []
    events = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    return events[:limit]


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        sys.exit("usage: python -m harness.trace <trace.jsonl>")
    for event in replay(Path(sys.argv[1])):
        print(json.dumps(event, ensure_ascii=False))
