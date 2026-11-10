# Questions this project answers

Short, factual answers to the questions that came up while building it. They are
here because most of them were learned the hard way, and a demo that only shows the
final code hides the interesting part.

---

## Setup

**Why does a local model need a token at all?**

Because LM Studio enables "Require Authentication" by default: the local server is a
real HTTP server, and any process on the machine could call it. The token is the
cheapest way to say "only clients I configured may use it". Two alternatives: turn the
requirement off in *Developer -> Server Settings*, or point the harness at another
OpenAI-compatible endpoint and use that provider's key.

**Why is the token in `.env` and not in the code?**

A key in source code is a key in git history, and git history is permanent. `.env` is
ignored, created from `.env.example` by `setup.sh`, and read by one function.

**How can someone try this repo without any model?**

Three entry points need no model and no network: `./bin/selftest.sh` (error paths),
`./bin/adversarial.sh` (governance), and `./bin/eval.sh --verify-only` (task set). They
finish in about two seconds, which is also why they are the ones worth running in CI.

**What breaks first for a new user?**

The model name. A server may be running and healthy while offering a different model
than the one configured, and the failure then looks like a network error. `doctor.sh`
lists the names the server actually offers.

## Concepts

**What is a harness?**

Everything that is not the model. A raw model predicts text; it cannot keep state,
execute code, or fetch anything. The harness is the code around it that turns
prediction into work: the loop, the tool registry, context management, a sandbox,
governance, and an eval.

**How is a harness different from a framework?**

A framework ships parts you assemble. A harness ships a working agent — loop, context
management, tool registry and permission layer already wired together.

**Can the model execute a tool itself?**

No. The model emits a JSON request: name plus arguments. The harness validates it,
executes it, and appends the result. Everything the model "does" is a request.

**Why must an assistant message with `tool_calls` be followed by `tool` messages?**

It is a protocol rule, not a convention. One `tool` message per call id, or the API
rejects the request. This matters when slicing history: a `tool` message whose caller
moved into the summarised middle is an orphan, and the request fails.

**Why put governance at the tool boundary instead of in the system prompt?**

A prompt is a suggestion. A path check that returns an error is a rule. Governance has
to be deterministic code, or it is only a preference.

**Why does one choke point matter?**

If every tool checks its own paths, you never know which check ran. One entry point
gives one place to log, one place to test, and one place to change. The tool-level
check stays as defence in depth, not as a duplicate.

---

## Context and cost

**Why does a token estimate need to know about character classes?**

Tokenisers merge frequent byte pairs. ASCII averages about four characters per token,
CJK ideographs about 1.6, and kana roughly one character per token. Treating all
non-ASCII as "four characters per token" underestimated Japanese by about 70% in a
measured sample.

**Why count the tool schemas in the budget?**

They are sent on every request but are not part of `messages`. Leaving them out made
every estimate about 25% low, which is exactly the kind of error a budget gate must
not have.

**What is the difference between offload and compaction?**

Offload shrinks one oversized tool result: keep the head and tail, spill the rest to
disk. Compaction shrinks the whole history: summarise the middle and reopen a smaller
window. One is per result, the other is per conversation.

**Why is a summary not a substitute for a file?**

Because it is lossy. Anything load-bearing belongs in a file that can be read again,
not in a transcript that will eventually be compressed away.

---

## Governance

**Why can a single-stage content filter not work?**

A document that *describes* an attack contains the same words as the attack. In this
project a question about prompt injection was blocked because the corpus explains the
technique. The fix is two stages: pattern alone means suspicious and is logged;
pattern plus an action verb means blocked.

**What is the difference between a false positive and a false negative here?**

A false positive blocks legitimate content and breaks the product. A false negative
lets an attack through. Every filter trades one for the other; the honest thing is to
say which direction you chose.

**Why keep "blocked by the guard" separate from "the model did nothing"?**

They are different evidence. The first says the governance layer worked. The second
says the dangerous action never happened, which tells you nothing about the guard.
Mixing them inflates the guard's apparent value.

**Where should a classifier sit, if you add one?**

As a signal, not as a verdict. Its output should raise the approval requirement
rather than hard-block, because a classifier will always produce false positives.

---

## Evaluation

**What are the three parts of an eval?**

A task (question plus rubric), a solver (the thing under test), and a scorer. Keeping
them separate is what makes the numbers meaningful.

**Why check that a rubric is answerable before running it?**

A rubric term that appears nowhere in the corpus makes the task impossible, and the
resulting low score looks like a model problem. `--verify-only` also checks that a
`single` task has at least one line satisfying every rubric group — otherwise the
rubric contradicts the document it points at.

**Why are keyword rubrics weak?**

They are brittle in both directions. A correct answer phrased differently fails; a
wrong answer containing the right words passes. Two real failures in this project came
from the scorer, not the model: one rubric demanded a word the cited definition never
used, and one citation used full-width parentheses that the regex did not match.

**What is a baseline, and why does it have to be measured first?**

The number you get before changing anything, under the same task set, model and
temperature. Without it, "it feels better" is the only available claim.

**Why change one variable at a time?**

Because otherwise the delta cannot be attributed. This project's own comparison has
that flaw: the baseline ran before the code change existed, so the difference mixes a
code change with a config change. The cheapest repair is to re-run the baseline with
the new code and the gate disabled.

**Is temperature 0 deterministic?**

Almost. A run that takes exactly the same path reproduces exactly — one task in this
project produced identical token counts in both runs because its refusal gate never
fired. Runs that take different paths do not, and server-side batching adds its own
noise. Repeat the run, or compare per task instead of comparing totals.

**Why compare per task rather than by total score?**

With 25 tasks, 5% is about one task. A paired comparison — how many tasks improved,
how many regressed — is far more sensitive than a difference of totals.

---

## What went wrong here, and what it taught

| Symptom | Cause | Fix |
|---|---|---|
| CLI reported 0 tool calls and 0 tokens while the trace showed both | result fields copied by hand and forgotten twice | one exit point that builds the result from one state object |
| A correct answer was scored as "no citation" | citation regex only accepted square brackets | accept square, full-width and bare forms |
| A rubric could never pass | it demanded a word the cited definition never used | witness-line check in `--verify-only` |
| Seven `if tracer:` branches in the loop | tracing was optional at every call site | a null-object tracer |
| An audit wrapper could be bypassed | the check functions were public and the wrapper was optional | audit inside every check |
| A note explaining prompt injection was blocked | single-stage content filter | two-stage filter with an action-word requirement |
| A 44-line document was read as 40 lines | an arbitrary default range | default covers a whole short document |
| A duplicate `json.loads` crashed the run | the tolerant parse and the strict re-parse disagreed | parse once, return the parsed value |
