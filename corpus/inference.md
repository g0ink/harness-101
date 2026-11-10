# LLM inference: prefill, decode, KV cache

## Why the two phases behave differently

A request is served in two phases.

- **prefill** processes the whole prompt at once. Every token attends to every other
  token, so the work grows with the square of the prompt length. It is compute bound.
- **decode** produces one token at a time. Each step reads the entire weight matrix to
  produce a single token, so it is memory-bandwidth bound.

The arithmetic intensity of the two phases differs by one to two orders of magnitude.
Almost every optimisation in an inference server follows from that gap.

## Where the gap breaks

When the batch is large — say 64 users are generating at once — one read of the
weights serves 64 tokens. The weight read is amortised and decode slides back toward
being compute bound. That is exactly why continuous batching pays off, and it is the
boundary where the simple "decode is bandwidth bound" statement stops holding.

## KV cache

The attention computation for a token needs the key and value vectors of every
previous token. Recomputing them each step would be wasteful, so they are cached.

The cache is a state management problem: allocation, reuse and reclamation. Its size
grows with sequence length times layers times hidden size, which is why long context
is expensive even when the prompt is short.

## Quantisation

Quantisation stores weights in fewer bits — 4-bit formats such as GPTQ, AWQ and GGUF
are common. It trades a small amount of accuracy for a large reduction in memory
footprint and bandwidth. Because decode is bandwidth bound, the speed-up is often
close to the compression ratio.
