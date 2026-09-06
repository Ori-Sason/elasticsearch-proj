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

## `records` depends on two related tables (`runs`, `record_metadata`) to render a frontend row — how do you avoid ES needing joins for that?

Schema: `records` has a `run_id` column and a `record_metadata_id` column, foreign keys into `runs` and a separate `record_metadata` table.

Rendering one frontend row needs data from all three tables — two joins in SQL.

There are three places to resolve those two relationships when `records` is searched through ES:

```
Option A — Query ES, then hydrate the page of results via SQL
┌─────────┐  search   ┌────────────────┐
│    ES   ├──────────►│ run_id +       │
│ records │  results  │ record_meta_id │
└─────────┘           └───────┬────────┘
                              │ SQL lookups (bounded to
                              │ this page of results)
                              ▼
                     runs + record_metadata

Option B — Denormalize both relations onto the ES doc at index time
┌──────┐ ┌────────────────┐  sync   ┌───────────────────────┐
│ runs │ │ record_metadata│────────►│          ES           │
└──────┘ └────────────────┘ writes  │ records + run fields  │
          (once, at index/sync time)│ + embedded metadata   │
                                    └───────────────────────┘

Option C — Skip ES entirely
┌──────┐  join   ┌─────────┐  join   ┌──────────────────┐
│ runs │────────►│ records │────────►│ record_metadata  │  (all in Postgres)
└──────┘         └─────────┘         └──────────────────┘
```

Option B is the standard pattern for this. A sync/reindex job (the same kind of process that keeps ES derived from the DB, per [session 6](session-6-database-of-record.md)) resolves both joins **once**, at write/sync time, and writes the flattened result as a single self-contained document:

```json
{
  "run_id": "...",
  "run_started_at": "...",        ← denormalized field, copied from runs
  "record_metadata": {            ← denormalized object, embedded whole
    "field1": "...",
    "field2": "..."
  },
  ...record's own fields
}
```

At read time, ES never joins anything — a search returns documents that already contain everything the frontend needs to render. Embedding a whole related object (`record_metadata`) instead of just a scalar field is the same embed-over-reference call MongoDB modeling makes when a database can't join collections natively.

Option A also works, and it's cheap specifically because it's bounded: ES already did the actual job it's good at — full-text search or filtering — and returned a page of maybe 20–50 results. Hydrating just those `run_id`s and `record_metadata_id`s with a couple of SQL lookups (or a `WHERE id IN (...)` on each side) is a small, constant-size query, not something that grows with the size of the dataset.

Option C — skipping ES and joining `runs → records → record_metadata` directly in Postgres — is fine whenever the actual query need is exact filters and joins, not full-text relevance. Indexed foreign-key joins in Postgres (`records.run_id`, `records.record_metadata_id`) stay cheap even at tens of millions of rows, so "the join is too expensive" on its own is rarely the real reason to reach for ES.

| Decision axis | Stay Postgres-only | Add ES |
|---|---|---|
| Query type | Exact filters, date ranges, status codes | Full-text relevance ranking, fuzzy/substring match |
| Aggregations | Simple, one-level `GROUP BY` | Nested bucket + metric aggregations over large data |
| Join cost at scale | Cheap, if FKs are indexed | N/A — denormalize instead of joining |
| Consistency need | Records must be correct immediately after write | Tolerant of ES's eventually-consistent refresh cycle |

If Option B is the choice, the trade-off moves from read time to write time. `record_metadata` is a genuine many-to-one relationship if a single metadata row can be shared by many records — editing that one row then means re-syncing every ES document that embedded a copy of it, a fan-out write across potentially many documents instead of the single-row update SQL would need. That cost is real only if `record_metadata` actually gets edited after records already reference it; metadata that's written once and never touched again pays no such penalty.

**Bottom line:** the decision to add ES should be driven by the query shape `records` actually needs — full-text relevance, faceted search, nested aggregations — not by join cost, since an indexed Postgres join usually isn't the bottleneck. If ES is warranted, denormalize both relations onto the record document during the existing sync step (Option B) so reads need zero joins, and only fall back to per-result SQL hydration (Option A) for data that's too volatile or too rarely needed to be worth keeping in sync.
