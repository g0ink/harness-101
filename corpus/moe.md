# Mixture of Experts

## The idea

A dense feed-forward layer activates every parameter for every token. A mixture of
experts layer splits that feed-forward block into N experts and activates only the
top few for each token. Total parameters grow, activated parameters stay small.

## Data flow of one MoE layer

```
hidden state
   -> router (a small linear layer, produces one score per expert)
   -> top-k selection (choose k experts per token)
   -> dispatch (send each token to the devices that hold its experts)
   -> experts (each expert runs its own feed-forward on the tokens it received)
   -> combine (gather the outputs back, weighted by the router scores)
   -> output
```

Two communication points sit in that flow: dispatch and combine. Both are
all-to-all style exchanges across devices, and both are where expert parallelism
spends its time.

## Router details that bite

- The router score type matters. Running the router in lower precision changes which
  experts win, so many training setups force the router to fp32.
- Top-1 routing with a softmax needs renormalisation, otherwise the gradient through
  the router disappears.
- Load balancing is not optional: without an auxiliary loss, a few experts absorb
  everything and the rest never train.
