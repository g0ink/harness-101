# Fuzzing: harness, coverage, sanitizers

## What a fuzzing harness is

A fuzzer produces raw bytes. A harness is the small piece of code that turns those
bytes into the input the target function expects — it decodes, wraps, fills in the
required structures, and calls the target.

The harness is where the real work lives. A fuzzer that is pointed at the wrong
layer will report nothing for a week and look like a tool problem.

## Coverage

Coverage-guided fuzzing keeps inputs that reach new edges. The feedback loop is:
mutate an input, run the target, keep the input if it covers a new path.

If the fuzzer never reaches the parsing code, no amount of runtime will help. The
first question after a silent run is always reachability, not duration.

## Sanitizers

AddressSanitizer instruments memory accesses at compile time and aborts on the first
invalid one. It catches heap buffer overflow, use-after-free and stack overflow that
would otherwise corrupt memory silently.

Running without a sanitizer mostly finds crashes that happen to be fatal. Running
with one turns latent corruption into a report.

## Reading a silent run

When a campaign finds nothing, the usual order of suspicion is:

1. the input never reached the target line (reachability)
2. the harness did not enable the feature under test
3. the target needs a precondition the harness never satisfies
4. the heap layout needs help (use-after-free that needs pressure)
5. the sanitizer is off, or its report is being swallowed
