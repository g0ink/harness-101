"""Tools: the registry the model may call, and two real implementations.

How this file is used
---------------------
``harness.loop`` imports ``SCHEMAS`` (what the model is told about) and
``REGISTRY`` (what actually runs). The model never executes anything: it emits
``{"name": ..., "arguments": ...}`` and the loop resolves that name here.

Scope: both tools read ``corpus/`` only. Path containment lives in ``_resolve_note``
and is enforced again by the guard layer -- deliberate defence in depth, because one
check protects this tool and the other protects every tool at once.
"""

from __future__ import annotations

from pathlib import Path

from .lexical import cosine, tokens

LAB = Path(__file__).resolve().parents[1]  # repository root
CORPUS = LAB / "corpus"


def _resolve_note(path: str) -> Path:
    """Turn a model-supplied path into a real path, or refuse.

    Two gates, both needed:

    1. reject any ``..`` segment -- say no early instead of normalising first
    2. ``is_relative_to`` instead of ``startswith`` -- a prefix test would accept
       sibling directories such as ``corpus-private/``
    """
    if ".." in Path(path).parts:
        raise PermissionError(f"path_denied: '..' segments are not allowed: {path}")
    target = (LAB / path).resolve()
    if not target.is_relative_to(CORPUS.resolve()):
        raise PermissionError(f"path_denied: {path}")
    return target


def search_notes(query: str, k: int = 5) -> list[dict]:
    """Score every line in ``corpus/`` against the query and return the best ones."""
    terms = tokens(query)
    if not terms:
        return []

    hits: list[dict] = []
    for path in sorted(CORPUS.rglob("*.md")):
        relative = path.relative_to(LAB).as_posix()
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            text = line.strip()
            if not text or text.startswith("#"):
                continue
            score = cosine(terms, tokens(text))
            if score > 0.05:
                hits.append({"path": relative, "line": lineno, "text": text[:200], "score": round(score, 3)})

    hits.sort(key=lambda hit: -hit["score"])
    return hits[:k]


# One read returns at most this many characters of numbered lines. Larger requests
# are paginated with an explicit `next_start`, so a long document costs several
# turns instead of being silently cut in the middle by the offload gate.
MAX_READ_CHARS = 3000


def read_note(path: str, start: int = 1, end: int = 200) -> dict:
    """Read a line range from one corpus file, numbered, so the model can cite it.

    The default range covers a whole short document: a 40-line default silently
    truncated a 44-line file and the model concluded the answer was not there.
    When the requested range is larger than one page, the response says exactly
    which lines came back and how to fetch the rest.
    """
    target = _resolve_note(path)
    if not target.is_file():
        raise FileNotFoundError(f"not_found: {path}")

    lines = target.read_text(encoding="utf-8").splitlines()
    first = max(1, start)
    last = min(len(lines), end)

    selected: list[str] = []
    used = 0
    for number in range(first, last + 1):
        rendered = f"{number:>4}  {lines[number - 1]}"
        if selected and used + len(rendered) > MAX_READ_CHARS:
            break
        selected.append(rendered)
        used += len(rendered)

    reached = first + len(selected) - 1
    page = {
        "path": path,
        "start": first,
        "end": reached,
        "total_lines": len(lines),
        "lines": selected,
    }
    if reached < last:
        page["truncated"] = True
        page["next_start"] = reached + 1
        page["hint"] = f"returned lines {first}-{reached} of {last}; call read_note(start={reached + 1}) for the rest"
    return page


REGISTRY: dict[str, object] = {
    "search_notes": search_notes,
    "read_note": read_note,
}

# The only description of the tools the model ever sees.
SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "search_notes",
            "description": "Search the corpus by keyword and return the most relevant lines with line numbers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Keywords, Chinese or English"},
                    "k": {"type": "integer", "description": "How many hits to return, default 5"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_note",
            "description": "Read a line range from one corpus file and return it with line numbers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path relative to the lab root, e.g. corpus/memory.md",
                    },
                    "start": {"type": "integer", "description": "First line, default 1"},
                    "end": {"type": "integer", "description": "Last line, default 200"},
                },
                "required": ["path"],
            },
        },
    },
]
