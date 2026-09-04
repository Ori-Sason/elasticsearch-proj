# Session 4 — Aggregations

## TL;DR

Moved from finding documents to summarizing them, against the same `logs-app` dataset from [session 2](/learning-notes/session-2-model-and-load-data.md) and [session 3](/learning-notes/session-3-search-fundamentals.md).

Covered bucket aggregations (`terms`, `date_histogram`) for grouping, metric aggregations (`avg`, `sum`, `value_count`) for computing a number over a group, and nesting a metric inside a bucket to get that number per group instead of globally.

Went deep on `doc_values` — the columnar structure aggregations actually run on, separate from the inverted index — and on why a `terms` aggregation can come back approximate once it's spread across shards, using `doc_count_error_upper_bound` and `sum_other_doc_count` to see and reason about that approximation directly.

## Aggregation execution flow

```
                GET logs-app/_search  { "size": 0, "query": {...}, "aggs": {...} }
                                │
                    query/filter context narrows
                    the doc set first (if present)
                                │
              ┌─────────────────┼─────────────────┐
              ▼                 ▼                 ▼
          Shard 1            Shard 2           Shard 3
       (each one independently, over its own doc_values):
         - exact per-term counts for EVERY matching doc, every term
         - sorts its own terms by count, descending
         - ships only its top `shard_size` terms upward
              └─────────────────┼─────────────────┘
                                ▼
                    Coordinating node merges
              the shards' partial term lists, sums matching
              terms across shards, keeps the global top `size`,
           computes doc_count_error_upper_bound + sum_other_doc_count
```

`logs-app` runs on a single primary shard in this cluster (same as session 3), so in every hands-on result below, the "merge across shards" step collapses to one shard talking to itself — which turns out to matter a lot for how the approximation deep dive plays out.

## Walkthrough

### Buckets vs. metrics

Two different jobs, and they compose:

- **Bucket aggregation** — partitions documents into groups by some criterion. `terms` groups by exact field value, `date_histogram` groups by time interval. A bucket is just a subset of documents, nothing computed yet.
- **Metric aggregation** — computes one number over a set of documents: `avg`, `sum`, `percentiles`, `value_count`. On its own it runs over the whole query result.

Nest a metric *inside* a bucket, and it recomputes per-bucket instead of globally. That's the SQL parallel, to `GROUP BY`, with an aggregate function in the `SELECT` list.

```sql
SELECT service, AVG(status_code)
FROM logs
GROUP BY service;
```

### `terms`: why it needs `keyword`, not `text`
*Note: this is a reminder for session 2 and 3*

`terms` buckets on `doc_values`, the per-document columnar structure introduced in session 3's pagination section (like ClickHouse, a columnar database). Every `keyword` field gets `doc_values` by default — one exact value per document, ready to bucket on directly.

A `text` field breaks this in two ways:

1. **What's actually stored.** A `text` field's inverted index holds tokens, not whole values. `service: "checkout-api"` as `text` wouldn't be one bucketable thing — it'd be separate tokens `checkout` and `api`. Buckets would come out as word fragments, not service names.
2. **`doc_values` are off by default on `text`.** Elasticsearch assumes you don't need to sort or aggregate on free-text values — bucketing on every unique token in `message` would be combinatorial junk. Running `terms` on a plain `text` field throws a hard error: `Fielddata is disabled on text fields by default.` The escape hatch (`fielddata: true`) loads all unique terms into heap memory and is almost always the wrong move — which is exactly why `service` got mapped as `keyword` up front in session 2, instead of relying on that escape hatch later.

**Hands-on:** filtered to `level: ERROR` via `bool.filter` (see below for why `filter`, not a bare `query.term`), then bucketed the filtered set by `service`:

```
GET logs-app/_search
{
  "size": 0,
  "query": {
    "bool": {
      "filter": [
        { "term": { "level": "ERROR" } }
      ]
    }
  },
  "aggs": {
    "errors_by_service": {
      "terms": { "field": "service", "size": 10 }
    }
  }
}
```
* `"size": 0` on the top-level search request returns only the aggregation results, not the underlying hits.
* `"size" : 10"` in the `terms` field request to get back only the top 10 services.
* The key under `"aggs"` (`errors_by_service`) is not a built-in Elasticsearch field. It's an arbitrary, user-chosen label, exactly like a variable name — Elasticsearch only cares about the `terms`/`field` underneath it.
* This query is like in SQL
  ```SQL
  SELECT service, COUNT(*) AS errors_by_service
  FROM logs-app
  WHERE level = 'ERROR'
  GROUP BY service
  ORDER BY errors_by_service DESC
  LIMIT 10;
  ```

  The one catch: field mapping  
  For this Elasticsearch query to run successfully and produce exact results, the `level` and `service` fields must be indexed as `keyword` data types, not `text`.
  
  If they are mapped as text fields, Elasticsearch will do text analysis (tokenization) on them:
  * **The Filter:** A `term` query on a `text` field usually fails or behaves unexpectedly because it looks for exact, case-sensitive matches against analyzed tokens.
  * **The Aggregation:** Aggregations are disabled by default on `text` fields to prevent memory crashes (Fielddata error). If `service` contains spaces or hyphens (e.g., `"auth-service"`), it would split into separate tokens and distort your counts.
  
  **The Fix (if needed):** If your fields are standard multi-fields generated by Elasticsearch dynamic mapping, change the fields in your query to target the `.keyword` sub-field:
  * `{ "term": { "level.keyword": "ERROR" } }`
  * `"field": "service.keyword"`

```json
"aggregations": {
  "errors_by_service": {
    "doc_count_error_upper_bound": 0,
    "sum_other_doc_count": 0,
    "buckets": [
      { "key": "billing", "doc_count": 58 },
      { "key": "checkout", "doc_count": 51 },
      { "key": "auth", "doc_count": 50 },
      { "key": "notifications", "doc_count": 45 },
      { "key": "inventory", "doc_count": 38 }
    ]
  }
}
```

`58 + 51 + 50 + 45 + 38 = 242`, exactly matching `hits.total.value` for the `level: ERROR` filter — no doc dropped, no bucket missing.

### Two `size` params, and the agg's name

Same word, two unrelated jobs, easy to conflate:

| | Top-level search `size` | `terms.size` |
|---|---|---|
| Controls | how many raw hit documents come back | how many buckets come back |
| `0` means | return only aggregations, no hits | not valid — `terms.size` picks top N buckets |
| Ordering | irrelevant (usually by `_score` or `sort`) | buckets sorted by `doc_count` descending by default |
| Pagination equivalent | `from` | none — no way to page past the cutoff, it's a hard limit |

### `date_histogram`: request volume over time

Same bucket-aggregation shape as `terms`, but buckets by time interval instead of exact field value, keyed by each interval's start.

```
GET logs-app/_search
{
  "size": 0,
  "aggs": {
    "logs_over_time": {
      "date_histogram": { "field": "timestamp", "calendar_interval": "day" }
    }
  }
}
```

| | `calendar_interval` | `fixed_interval` |
|---|---|---|
| Boundary type | Calendar-aware (`day`, `week`, `month`, `year`) | Literal fixed duration (`"24h"`, `"30m"`) |
| Handles variable month/year length | Yes — Feb gets 28 days, June gets 30 | No — every bucket is exactly the stated duration |
| Use when | Buckets should align to real calendar boundaries | Buckets should be exact-width, e.g. rolling 6h windows |

Only one of the two is allowed per aggregation. There's no `size` here, unlike `terms` — `date_histogram` returns every bucket in the time range, including empty ones (`doc_count: 0`) by default. A `min_doc_count` parameter exists to suppress those if gaps aren't wanted.

**Hands-on:**

```json
"buckets": [
  { "key_as_string": "2026-08-26T00:00:00.000Z", "doc_count": 514 },
  { "key_as_string": "2026-08-27T00:00:00.000Z", "doc_count": 732 },
  { "key_as_string": "2026-08-28T00:00:00.000Z", "doc_count": 683 },
  { "key_as_string": "2026-08-29T00:00:00.000Z", "doc_count": 743 },
  { "key_as_string": "2026-08-30T00:00:00.000Z", "doc_count": 687 },
  { "key_as_string": "2026-08-31T00:00:00.000Z", "doc_count": 711 },
  { "key_as_string": "2026-09-01T00:00:00.000Z", "doc_count": 715 },
  { "key_as_string": "2026-09-02T00:00:00.000Z", "doc_count": 215 }
]
```

8 daily buckets summing to exactly 5000, matching `hits.total.value`. The first (514) and last (215) buckets sit well below the ~700/day the middle days show. That's not an anomaly in the data — the dataset's generation window doesn't start or end on an exact midnight boundary, so the first and last calendar-day buckets only capture a partial day.

**Bottom line:** before reading a `date_histogram` edge bucket as a real signal (a slow day, a spike), check whether it's actually a boundary effect from the query's or dataset's time range not aligning to the interval.

### Nesting a metric inside a bucket

```
GET logs-app/_search
{
  "size": 0,
  "aggs": {
    "by_service": {
      "terms": { "field": "service", "size": 10 },
      "aggs": {
        "avg_status": { "avg": { "field": "status_code" } }
      }
    }
  }
}
```

`avg_status` sits inside `by_service`'s own `"aggs"` key — the same nesting pattern recurses arbitrarily deep, whether the child is another bucket or a metric.

```json
"buckets": [
  { "key": "auth",          "doc_count": 1066, "avg_status": { "value": 227.11 } },
  { "key": "billing",       "doc_count": 996,  "avg_status": { "value": 233.36 } },
  { "key": "inventory",     "doc_count": 992,  "avg_status": { "value": 222.59 } },
  { "key": "notifications", "doc_count": 983,  "avg_status": { "value": 228.66 } },
  { "key": "checkout",      "doc_count": 963,  "avg_status": { "value": 233.99 } }
]
```

`1066 + 996 + 992 + 983 + 963 = 5000`, all docs accounted for across the 5 buckets.

### Sanity-checking an aggregation result

Verified `auth`'s `avg_status` (`227.10506566604127`) a different way instead of trusting `avg` blindly — filtered to `service: auth`, then requested `sum` and `value_count` separately instead of `avg`, and divided by hand:
```
GET logs-app/_search
{
  "size": 0,
  "query": {
    "bool": {
      "filter": [
        { "term": { "service": "auth" } }
      ]
    }
  },
  "aggs": {
    "total_status": {
      "sum": { "field": "status_code" }
    },
    "count_status": {
      "value_count": { "field": "status_code" }
    }
  }
}
```

```json
{
  "total_status": { "value": 242094 },
  "count_status": { "value": 1066 }
}
```

`242094 / 1066 = 227.10506566604127` — an exact match to the nested `avg` value, not just approximately close.

## Deep dive: `doc_values`, the structure aggregations actually run on

`doc_values` is a per-segment, Lucene-level columnar store — one column per field, doc-ID-ordered. Same idea as a columnar database (ClickHouse-style), just scoped to one field's values across all documents in a segment.

| | Inverted index | `doc_values` |
|---|---|---|
| Direction | term → `[doc IDs]` | doc ID → value |
| Answers | "which docs contain this term" | "what's this field's value for doc N" |
| Built for | Full-text search | Sort, aggregate, script access |
| Compression | Postings-list based | Delta/range encoding (numeric); dictionary + per-doc ordinal (`keyword`) |

Both structures get built at index time from the same source field, but only in the direction each one needs. `doc_values` is on by default for `keyword`, numeric, and `date` fields; off by default for `text` — the same fact behind why `terms` on a `text` field throws `Fielddata is disabled`.

**Bottom line:** the inverted index can only ever answer "which docs have this term." It structurally cannot answer "what value does doc N have for this field" — that question needs the reverse mapping, which is exactly what `doc_values` is.

## Deep dive: why `terms` gets approximate across shards

Within *one* shard, a `terms` aggregation is exact — it walks that shard's `doc_values` for the field and counts every matching document, for every term. No sampling happens at this level.

However, on multipe-shard cluster, aggregation with `terms` can return approximate results. We'll get it from an exmaple
**example** — we have 100 documents in a shard, and we ask for the top 2 services (A-D) that has the most errors. 

```
A: 40    B: 30    C: 20    D: 10        (sums to 100, all exact)

shard_size = 2  →  shard ships only its top 2 terms: A(40), B(30)
C and D are dropped from this shard's report entirely.
```

Now, let's say that the coordinator calculated the results and found that the top services are `A` and `C`. In that case, the total count missed the records of the shard (above). That shard sent his own top 2 services, so the count of 20 on `C` didn't get to the coordinator.  
Therefore, our shard will return `A(40), B(30)` and therefore the `doc_count_error_upper_bound` is `30`. In words: `there might be other records with results lower than 30`.

Let's say the end result was `A(40), C(60)` and `doc_count_error_upper_bound: 30`. So, we know that `C` actual count can be can be between `60` to `90`. That's the approximation.

In a single shard cluster, like ours, it can't happen since the coordinator is in the same shard, so it gets all the results.

**Closing hands-on:** reran the `by_service` `terms` aggregation with `"size": 2` (down from 10):

```
GET logs-app/_search
{
  "size": 0,
  "aggs": {
    "by_service": {
      "terms": {
        "field": "service",
        "size": 2
      }
    }
  }
}
```

```json
"aggregations": {
  "by_service": {
    "doc_count_error_upper_bound": 0,
    "sum_other_doc_count": 2938,
    "buckets": [
      { "key": "auth", "doc_count": 1066 },
      { "key": "billing", "doc_count": 996 }
    ]
  }
}
```

`doc_count_error_upper_bound: 0`, as expected on a single-shard cluster ([session 1](/learning-notes/session-1-cluster-fundamentals.md)) — with only one shard, there's no *other* shard that could be silently hiding a count.  
`sum_other_doc_count: 2938` checks out too: `inventory (992) + notifications (983) + checkout (963) = 2938`, the 3 services excluded once `size` dropped to 2.

**Bottom line:** `doc_count_error_upper_bound` is only ever nonzero when a shard drops a term that turns out to matter globally — which requires more than one shard to be merging results in the first place.

## Why doesn't Elasticsearch just ship every shard's complete term list?
In other words, at the example above, why doesn't it simply return `A: 40    B: 30    C: 20    D: 10`, instead of `A` and `B` only?

Worth asking, since it looks at first glance like it would remove the approximation entirely — but the pagination top-K heap from session 3 doesn't map cleanly onto this problem, and the difference is cardinality.

In the pagination case, the heap size `K = from + size` is **caller-controlled and small**, regardless of how many total documents match. It never grows past what the caller asked for.

A shard's full term list is the opposite: **data-dependent, and potentially unbounded.** `service` has 5 distinct values here, so shipping the whole thing costs nothing. Swap the aggregated field for `user_id`, `session_id`, or `client_ip`, and a single shard's term list could run into the millions. If every shard always shipped its complete term breakdown regardless of cardinality, a `terms` aggregation on a high-cardinality field would ship enormous payloads across the network and force the coordinator to merge millions of entries, for a query that only asked for the top 10.

`shard_size` exists specifically to bound that cost to a small, predictable multiple of what was asked for — trading exactness for a bound that only actually costs accuracy in the regime where full shipping would have been expensive anyway. In the low-cardinality regime — this session's 5 services — the result is exact for free, because `size` already exceeds the real cardinality.

Examples for using high-cardinality `terms` aggregations are: top users by request count for abuse detection, top source IPs for security analytics. It's not a corner case — which is why the trade-off has to exist rather than being avoidable. So, what if we do need an exact match, and not approximate:

- **`composite` aggregation** — exhaustively pages through *every* bucket via an `after_key` cursor, same idea as `search_after` from session 3, bounded memory per page regardless of total cardinality.
- **`cardinality` aggregation** — approximate *distinct count* only (not a per-bucket breakdown), via HyperLogLog++, for "how many unique values" instead of "what are the top N."

## Questions I Had

**Does `shard_size` limit how many documents a shard counts?**
No — every shard always counts all of its own matching documents exactly, for every term, via `doc_values`. `shard_size` only limits how many of the shard's already-exact top terms get shipped to the coordinator; anything below that cutoff is dropped entirely, not undercounted.

**Why is `doc_count_error_upper_bound` always `0` on this cluster?**
Because `logs-app` has a single primary shard. The error only exists when a term gets dropped by one shard but turns out to matter once merged with other shards' results — with one shard, there's nothing else to merge with, so a term is either exactly counted or fully excluded via `sum_other_doc_count`.

**Why doesn't Elasticsearch just ship every shard's full term list and skip the approximation?**
Because a shard's term list size is data-dependent and can be unbounded for high-cardinality fields (`user_id`, `client_ip`), unlike the pagination heap from session 3 whose size is caller-controlled. `shard_size` trades exactness for a bounded, predictable cost — a trade that only costs accuracy in the exact regime where shipping everything would be too expensive to do at all.
