"""Measure the token estimator against the real tokeniser.

Run: ``python scripts/measure_tokens.py``

Why this exists: every budget decision rests on the estimator, and the estimator is
hand-written. If its coefficients are wrong, the budget gate is decoration.

Method: keep the system message fixed and swap the user content. The template
overhead is constant, so differences are attributable to the content itself.

The samples are deliberately multilingual -- kana and emoji are where a naive
"4 characters per token" rule breaks.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.context import estimate_tokens  # noqa: E402
from harness.llm import build  # noqa: E402

SAMPLES = [
    ("empty", ""),
    ("ascii 88 chars", "the quick brown fox jumps over the lazy dog " * 2),
    ("chinese 62 chars", "上下文窗口是模型一次能看见的全部内容，超出就必须压缩或者报错。" * 2),
    ("japanese mixed", "コンテキストウィンドウはモデルが一度に見られる範囲です。超えたら圧縮が必要です。"),
    ("kana only", "あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをん"),
    ("emoji x10", "🚀" * 10),
]


def main() -> int:
    llm = build()
    print(f"{'sample':<18}{'chars':>7}{'utf8 bytes':>12}{'estimate':>10}{'actual':>8}{'delta':>7}")
    print("-" * 62)

    baseline: int | None = None
    for label, text in SAMPLES:
        reply = llm.chat([{"role": "system", "content": "x"}, {"role": "user", "content": text or "x"}])
        actual = reply.usage.prompt_tokens
        if baseline is None:
            baseline = actual
        content_tokens = actual - baseline
        estimate = estimate_tokens(text)
        print(
            f"{label:<18}{len(text):>7}{len(text.encode()):>12}"
            f"{estimate:>10}{content_tokens:>8}{estimate - content_tokens:>+7}"
        )

    print("\nactual = prompt_tokens minus the empty-sample baseline")
    print("a negative delta means the estimate is low and the model is more expensive")
    return 0


if __name__ == "__main__":
    sys.exit(main())
