# Replication

## Why replicate

Replication keeps a copy of the data on another node. Four reasons show up again and
again:

| Reason | What it buys |
|---|---|
| Availability | the system survives the loss of one node |
| Read scaling | more replicas can serve more read traffic |
| Latency | a replica near the user answers faster |
| Throughput | writes can be acknowledged before every copy is updated |

The last one is where the hard trade-off lives.

## Single leader

One node accepts writes and ships a log to the followers. Reads can be served by any
replica, but a follower may be behind, so a read from a follower can return stale
data.

This is the default because it is the easiest to reason about: writes have one order,
and there is no write conflict to resolve.

## Asynchronous versus synchronous

- synchronous: the write is acknowledged only after followers have it. No data loss on
  failover, but every write pays the slowest replica's latency.
- asynchronous: the write is acknowledged immediately. Fast, but a leader failure can
  lose the writes that had not shipped yet.

Most systems let you choose per write, and most production setups end up asynchronous
with a bounded lag.

## What replication does not fix

Replication duplicates data. It does not split it. When one node can no longer hold
the dataset or absorb the write traffic, replication stops helping and partitioning
takes over. Confusing the two is the most common capacity planning mistake.
