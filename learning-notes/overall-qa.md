# Overall Q&A

Off-curriculum questions and answers, not tied to a specific session.

## Do real projects run DB + Redis + ES together, and is that extra cost (3 writes, 2 memory-hungry systems) actually worth it?

DB + Redis + ES together is a common industry pattern, not redundancy.

Each layer solves a different access pattern.

| Layer | What it's actually good at |
|---|---|
| Postgres/MySQL | Correctness, transactions, relational integrity |
| Elasticsearch | Full-text search, facets, aggregations over large datasets |
| Redis | Sub-millisecond point lookups, counters, TTLs, pub/sub |

Redis being "faster" only holds for one query shape: get-by-key. It's an in-memory hash map — O(1) lookup, no query planning, no disk I/O.

ES for the same exact-match lookup still runs a full pipeline (parse request → check filter cache → hit doc_values/inverted index → build response), because it isn't built for point lookups.

It's built for a different job: rank 20 results out of 5 million documents, faceted across 4 fields.

Redis has no native mechanism for that job at all.

The common real-world pattern is Redis in front of ES, caching the *output* of expensive ES queries, not Redis replacing ES:

```
client → Redis (cache hit? return)
            │ (miss)
            ▼
          ES (run query → write result to Redis with a TTL)
```

Example: a dashboard's "top error services this hour" aggregation is identical for every viewer in that hour.

Running it fresh per request hammers the ES cluster for no reason — caching the result in Redis with a short TTL (30s–1min) turns "one ES query per request" into "one ES query per TTL window."

On the write side, a naive implementation does write to all three synchronously per request:

```
request → write DB → write ES → write Redis   (all synchronous, in one handler)
```

In practice this is usually split up instead:

```
request → write DB → publish event
                          │
            ┌─────────────┼─────────────┐
            ▼                           ▼
      async consumer              async consumer
      updates ES                  invalidates/updates Redis
```

Redis is also often cache-*aside* rather than written on every DB write — the app just invalidates the stale key, and the next read repopulates it lazily.

That removes one synchronous write per request, at the cost of the next reader paying a cache-miss penalty.

ES usually can't be treated that lazily, since a "miss" there means the document is just absent from search results — it doesn't silently refetch itself the way a cache does.

Memory is also a different problem shape for each system, not one shared budget:

| | Where memory goes |
|---|---|
| Redis | Entire dataset in RAM by design — that's the whole mechanism. Size Redis for 100% of what it caches. |
| Elasticsearch | JVM heap (query/agg working memory, caches) plus OS page cache for segment files on disk. ES leans on the OS to cache hot segments instead of holding everything in heap. Undersized heap causes GC pauses; undersized page cache causes disk reads on every query. |

**Bottom line:** ES's typical latency (single-digit to double-digit ms) is fine as a direct read path for plenty of real systems that skip Redis entirely. Redis gets added on top of ES specifically when requests need latency ES structurally can't hit, or when many requests would ask ES the exact same question. Real platforms also tend to avoid naive N-way synchronous write fan-out past a couple of downstream systems, leaning on event-driven sync (Kafka/Debezium-style CDC) instead of the app writing to DB, ES, and Redis itself in one request.
