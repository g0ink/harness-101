# Context and memory in LLM applications

## Three layers of "memory"

An application that feels like it remembers you is built from three separate layers.
None of them replaces another.

| Layer | What it holds | When it disappears |
|---|---|---|
| System prompt | Rules, resource index, project instructions | Never, but it is rebuilt and paid for on every turn |
| Context window | Messages, tool results | At the end of the session; long histories get compacted |
| Filesystem | Project files, session archives | Only enters the context when something reads it |

The useful test: a fact is remembered only if it is read again when the next session
starts. Everything else is a transcript nobody re-reads.

## Compaction

Compaction is what happens when the context window is close to full: the older
messages are summarised, and the agent continues in a fresh window.

Two properties matter:

1. It compresses only the conversation history. Facts that were never written down
   are lost, not compressed.
2. The summary is lossy. Detail in the dropped messages is gone, so anything
   load-bearing belongs in a file, not in the transcript.

## Hot summary budget

A common pattern is to inject a short "hot summary" at the start of every session.
Its size must stay small: a practical ceiling is 2%–5% of the context window.
Above that, the summary starts competing with the actual task for room.

## Retrieval

When the corpus is larger than the budget, inject by retrieval instead of injecting
everything. Two families:

- lexical search matches words; it is cheap, deterministic, and blind to synonyms
- embedding search matches meaning; it needs a vector index and an embedding model

Both are retrieval. Neither fixes a bad query, which is why a harness usually gives
the model a way to search again with different words.
