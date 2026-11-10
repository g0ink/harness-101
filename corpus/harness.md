# Agent harness

## Agent = model + harness

If it is not the model, it is the harness. A raw model predicts text; it cannot keep
state between calls, execute code, or fetch anything. The harness is the code around
the model that turns prediction into work.

## The six parts

| Part | What it does |
|---|---|
| Loop | calls the model, executes what it asks for, feeds results back, decides when to stop |
| Tools | a registry of functions plus the schema the model is told about |
| Context | decides what enters the window: injection, offload, compaction |
| Sandbox | the environment where generated code runs, with limits on files and network |
| Governance | deterministic rules about what the agent may do, plus an audit trail |
| Eval | a task set, a runner and a scorer, so "better" becomes a number |

A harness is not a framework. A framework ships parts you assemble; a harness ships a
working agent with the loop, context management, tool registry and permission layer
already wired together.

## Compaction, from the harness side

Compaction means: when the context approaches its limit, summarise and reopen a
window. The harness owns this because the model cannot see its own budget.

## Governance

Governance means: what the agent may do, expressed as code instead of as a request in
the system prompt. A prompt that says "do not read system files" is a suggestion; a
path check that returns an error is a rule.

Five dimensions are enough to start:

1. path — which files may be touched
2. tools — which functions may be called at all
3. budget — how many steps and tokens a run may spend
4. content — whether tool output carries instructions aimed at the model
5. audit — one line per decision, including the rule that fired

## Eval

An eval has three parts: a task (question plus rubric), a solver (the harness), and a
scorer. Two numbers worth reporting from the start: the success rate, and the
citation precision — whether the lines the agent cited actually support the answer.
