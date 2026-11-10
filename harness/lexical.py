"""Lexical scoring used by the search tool.

How this file is used
---------------------
``harness.tools.search_notes`` calls ``tokens`` to break text into terms and
``cosine`` to rank lines against the query.

Why lexical instead of embeddings
---------------------------------
No extra model, no index to build, and the ranking is explainable line by line. The
known weakness is length bias: a short line that shares one word with the query can
outrank a long line that shares several. ``scripts/selftest.py`` and the eval suite
both expose that behaviour rather than hide it.

Chinese is split into character bigrams so the scorer works without a tokeniser.
"""

from __future__ import annotations

import math
import re

CJK = re.compile(r"[\u4e00-\u9fff]+")
WORD = re.compile(r"[a-z0-9]+")


def tokens(text: str) -> set[str]:
    """Split text into terms: ASCII words, plus bigrams for CJK runs."""
    lowered = text.lower()
    terms = set(WORD.findall(lowered))
    for run in CJK.findall(lowered):
        terms.update(run[i : i + 2] for i in range(len(run) - 1))
    return terms


def cosine(left: set[str], right: set[str]) -> float:
    """Cosine similarity over term sets. Returns 0.0 when either side is empty."""
    if not left or not right:
        return 0.0
    return len(left & right) / math.sqrt(len(left) * len(right))
