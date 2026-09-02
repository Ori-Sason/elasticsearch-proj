# Session 3 — Search fundamentals

## TL;DR

Learned the Query DSL against the `logs-app` dataset: `match` (analyzed, free-text) vs `term` (exact, unanalyzed) queries, combining conditions with `bool`'s `must` vs `filter` clauses, and sorting/pagination via `from`/`size`. Went deep on why pagination cost scales with `from + size` (per-shard bounded heap, coordinator merge), then used `_explain` to see BM25 relevance scoring broken into its real formula components, and confirmed hands-on that rewriting a `must` clause as `filter` keeps the same result set but drops scoring entirely.

## `match` vs `term`

A query in Elasticsearch is a JSON document describing what to search for, sent to a search endpoint.

**`match`** is for free-text search: it runs the query string through the same analyzer the target field used at index time, then looks for documents containing those tokens — this is why a `match` query against `message` (a `text` field, see [session 2](/learning-notes/session-2-model-and-load-data.md)) can find `"connection"` inside `"retrying connection, attempt 39"` even though the input and the stored value aren't identical strings.

**`term`** is for exact-value matching: no analysis happens, the input is compared byte-for-byte against the stored value. This is why `term` needs a `keyword` field, not `text` — a `text` field never stores the original string as one token, only the analyzer's output tokens, so a `term` query for a whole phrase or the original casing almost never matches anything in a `text` field. The one exception: a single word that's already lowercase with no punctuation analyzes to itself unchanged, so a `term` query for that exact word would match by coincidence. The moment the original value is multi-word, mixed-case, or has punctuation, the stored tokens diverge from the original string and `term` stops matching.

By default `match` on multi-word input is an OR across the resulting tokens (any token matching is enough, more matching tokens just score higher) — requiring *all* conditions to hold at once is what `bool` is for, covered next.

**Hands-on:** ran a `match` query against `message`:

```
GET logs-app/_search
{
  "query": {
    "match": { "message": "timeout" }
  }
}
```

returned `hits.total.value: 0` — not a bug, a real fact about the dataset. Checking [`generate_logs.py`](/scripts/generate_logs.py)'s `MESSAGES` templates, the literal token `timeout` never appears; the closest is `"database query timed out after {ms}ms"`, which tokenizes to `timed`, `out`, `after`, ... — separate tokens, not `timeout`. `match` matches exact analyzed tokens, no stemming or synonyms by default, so `timed` ≠ `timeout`.

Same query for `"connection"` returned 274 hits, all from the one template that contains that word — the `DEBUG`-level `"retrying connection, attempt {n}"`:

```json
{
  "hits": {
    "total": { "value": 274, "relation": "eq" },
    "max_score": 3.0687466,
    "hits": [
      {
        "_score": 3.0687466,
        "_source": {
          "timestamp": "2026-08-28T15:46:54.802406+00:00",
          "level": "DEBUG",
          "service": "inventory",
          "message": "retrying connection, attempt 39",
          "status_code": 200
        }
      },
      ...
    ]
  }
}
```

Every single hit had the identical `_score` of `3.0687466` — worth noting now, explained properly in the BM25 section below: same token, same term frequency (1), same field length (4 tokens) every time, so same score every time.

Then ran a `term` query on the `keyword` field `level`:

```
GET logs-app/_search
{
  "query": {
    "term": { "level": "ERROR" }
  }
}
```

The generator's `ERROR` weight (`5` out of `100` total, from [`generate_logs.py`](/scripts/generate_logs.py)'s `LEVEL_WEIGHTS`) predicts roughly 5% of 5,000 documents ≈ 250 `ERROR`-level logs. The query returned 242 — within normal sampling variance for `random.choices`-driven weighted selection:

```json
{
  "hits": {
    "total": { "value": 242, "relation": "eq" },
    "hits": [
      {
        "_source": {
          "timestamp": "2026-08-27T03:11:02.501+00:00",
          "level": "ERROR",
          "service": "billing",
          "message": "failed to connect to downstream service",
          "status_code": 502
        }
      },
      ...
    ]
  }
}
```

## `bool`: `must` vs `filter`

`bool` combines multiple conditions, but its clauses aren't interchangeable — `must` and `filter` both require the condition to match, but only `must` contributes to `_score`. `filter` is a pure yes/no gate that contributes nothing to relevance scoring. For a deterministic condition (like an exact `term` match), the *result set* is identical whichever clause it's in — what differs is the score, and (see the query-vs-filter-context section below) the performance characteristics.

**Hands-on:** combined the two earlier queries — free-text on `message`, exact filter on `level`:

```
GET logs-app/_search
{
  "query": {
    "bool": {
      "must": [
        { "match": { "message": "connection" } }
      ],
      "filter": [
        { "term": { "level": "ERROR" } }
      ]
    }
  }
}
```

No document can satisfy both conditions simultaneously: the only message template containing `"connection"` is the `DEBUG`-level one, while `level: ERROR` is a hard filter. Running it confirms that directly:

```json
{
  "hits": {
    "total": { "value": 0, "relation": "eq" },
    "hits": []
  }
}
```

## Sorting and pagination

By default, results are sorted by `_score` descending. For log data you often want strict recency instead, regardless of relevance — that's what `sort` does; when a field-based sort is used, `_score` isn't computed by default (comes back `null`) since the ranking no longer depends on it. `from`/`size` then give you an offset-based page into the sorted results.

**Hands-on:**

```
GET logs-app/_search
{
  "query": {
    "term": { "level": "ERROR" }
  },
  "sort": [
    { "timestamp": "desc" }
  ],
  "from": 0,
  "size": 5
}
```

returned the 5 most recent `ERROR` logs, ordered purely by `timestamp`, no `_score` involved:

```json
{
  "hits": {
    "total": { "value": 242, "relation": "eq" },
    "hits": [
      {
        "_score": null,
        "_source": {
          "timestamp": "2026-09-01T22:14:07.501+00:00",
          "level": "ERROR",
          "service": "checkout",
          "message": "unhandled exception processing request",
          "status_code": 500
        },
        "sort": [1788480847501]
      },
      ...
    ]
  }
}
```

**Why deep pagination (a large `from`) gets expensive** — and specifically why this isn't a full-table-scan problem, and isn't about "the data being sorted on disk" either. Elasticsearch has no single physical sort order for an index the way a relational DB's clustering key gives one table one privileged order. Instead, every field gets its own **`doc_values`** — a columnar, per-field, per-document structure built at index time (distinct from the inverted index used for search) that answers "what's this field's value for document N" efficiently. Sorting (and later, aggregations — session 4) run over `doc_values`, not the inverted index, and every field's `doc_values` are equally cheap to sort by; there's no field that's privileged the way a clustering key is in a relational DB.

Finding *which* documents match a query costs the same regardless of `from` — the posting-list walk for `level: ERROR` doesn't change size based on pagination depth. What actually changes is a separate step: each shard runs a streaming top-K algorithm, keeping a bounded max-heap (priority queue) of size `K = from + size` as it streams through matches, replacing the worst entry in the heap whenever a better-sorted document shows up. That's `O(N log K)`, not `O(N log N))` — the shard never fully sorts all N matches, only maintains a heap of size K. The real cost scaling with `from` shows up in two places downstream of that: (1) every shard has to ship its *entire* top-K — not just the final page — to the coordinating node, so network payload per shard scales with K, not with `size`; and (2) the coordinating node has to merge `num_shards × K` candidates and re-sort them to pick the final page, discarding everything before position `from`.

Small worked example: 3 shards, `from: 20, size: 10` → `K = 30`. Each shard builds and ships a heap of 30 candidates (not 10). The coordinator receives `3 × 30 = 90` candidates total, sorts them, and returns documents 21–30 — throwing away the other 80 it just spent effort transferring and merging. Ask for `from: 0, size: 10` instead and each shard only ever builds/ships a heap of 10, and the coordinator merges just `3 × 10 = 30` candidates. (`logs-app` itself only has 1 primary shard, so this multi-shard merge collapses to a single heap in this cluster — the mechanism is the same either way, it's just not observable in a 1-shard index the way it would be in a larger cluster).

This cost profile is exactly what `search_after` (not implemented this session, but worth knowing) is built to avoid — instead of "give me the top `from + size` so I can discard the first `from`," it takes a cursor (the sort values of the last-seen document) and asks for "whatever comes strictly after this," with no heap that grows as pagination goes deeper.

## Scoring mechanism: understand BM25 via `_explain`

`GET <index>/_explain/<doc_id>` runs a query against one specific document and returns the actual score computation instead of just the number, which is how the BM25 formula's pieces got inspected directly against real data.

BM25's score for one term in one document is built from three named quantities — `idf`, `tf`, and `b` — each with a distinct plain-language job:

- **`idf` (inverse document frequency)** — how rare the term is *across the whole corpus*. The more documents a term appears in, the lower its `idf`, trending toward 0 for a term nearly every document has (it carries no discriminating information); the fewer documents it appears in, the higher its `idf`. This is the "unique words matter more" half of relevance: a term that's rare across the corpus is more informative when it does show up, so it's weighted higher. Formula: `idf = log(1 + (N - n + 0.5)/(n + 0.5))`, where `N` is total documents with the field and `n` is how many of those contain the term.
- **`tf` (term frequency, with saturation)** — how much a term's *repeated occurrence within one document* should matter. In isolation, this would just be a saturating curve on `freq` alone, something like `freq/(freq + k1)`: diminishing returns per additional occurrence rather than a linear reward, which is what stops something (or in this dataset's case, a repeated log template) from inflating a score just by repeating a word. `k1` controls how fast that saturation kicks in.
- **`b` (field-length normalization)** — a term match in a short field should generally count for more than the same match in a long field, since the long field had more "opportunity" to contain the word incidentally. This is expressed as a correction factor `B = 1 - b + b·dl/avgdl`, where `dl` is this document's field length in tokens and `avgdl` is the corpus average; `b` controls how strongly the correction applies (`b=0` disables it, `b=1` applies it fully — Elasticsearch's default is `0.75`).

`tf` and `b` aren't separate multiplicative pieces that get combined with `idf` at the end, though — they're fused into one shared fraction, because `B` doesn't stand alone, it corrects `k1` inside `tf`'s own denominator: `tf = freq / (freq + k1·B)`. That means `freq` shows up twice in the full formula — once alone in the numerator (capped by a `(k1+1)` ceiling), and again added to `k1·B` in the denominator, where `B` carries the length normalization computed from `b`. Multiplying that `tf` by `idf` and writing everything out in full gives the actual formula used above:

```
score = idf × [ freq·(k1+1) / (freq + k1·(1 - b + b·dl/avgdl)) ]
```

**Hands-on:** ran `_explain` for the `"connection"` match against one of the earlier hits:

```
GET logs-app/_explain/ylcPYaAB2lPiMDlQDoKi
{
  "query": {
    "match": { "message": "connection" }
  }
}
```

returned (trimmed to the numbers that matter):

```json
{
  "value": 3.0687466,
  "description": "score(freq=1.0), computed as boost * idf * tf from:",
  "details": [
    { "value": 2.2, "description": "boost" },
    {
      "value": 2.902442,
      "description": "idf, computed as log(1 + (N - n + 0.5) / (n + 0.5)) from:",
      "details": [
        { "value": 274, "description": "n, number of documents containing term" },
        { "value": 5000, "description": "N, total number of documents with field" }
      ]
    },
    {
      "value": 0.48059005,
      "description": "tf, computed as freq / (freq + k1 * (1 - b + b * dl / avgdl)) from:",
      "details": [
        { "value": 1, "description": "freq" },
        { "value": 1.2, "description": "k1" },
        { "value": 0.75, "description": "b" },
        { "value": 4, "description": "dl" },
        { "value": 4.6108, "description": "avgdl" }
      ]
    }
  ]
}
```

Verified each number by hand: `idf = log(1 + (5000 - 274 + 0.5)/(274 + 0.5)) = log(18.223) ≈ 2.9024` — matches; `"connection"` appears in 274 of 5,000 documents (~5.5%), moderately rare, so it carries real weight. `tf = 1 / (1 + 1.2·(1 - 0.75 + 0.75·(4/4.6108))) = 1 / 2.0808 ≈ 0.4806` — matches; `dl` (4) is close to `avgdl` (4.6108) here, so length normalization barely moves the score either way for this particular hit. `2.2 × 2.9024 × 0.4806 ≈ 3.0687` — matches the reported score.

One naming quirk worth knowing: the `"boost": 2.2` in this output is **not** a query-time relevance boost anyone configured — it's `k1 + 1 = 1.2 + 1 = 2.2`, the `(k1+1)` factor from the formula above, which Lucene's `_explain` output splits into its own labeled node rather than folding into `tf`. Don't go looking for where a `2.2` boost was set; it isn't one.

Plugging in `freq=2` instead of `freq=1` (same `k1`, `b`, `dl`, `avgdl`) makes the saturation effect concrete: `tf(freq=2) = 2/(2 + 1.2·0.9007) = 2/3.0808 ≈ 0.6491`, versus `tf(freq=1) ≈ 0.4806` — the term count doubled, but `tf` only rose ~35%, not 100%, exactly the diminishing-returns behavior `k1` is designed to produce.

## Query context vs filter context

A `filter` clause produces only membership (yes/no), never a score, and that distinction is what makes it faster than an equivalent `must`. Because there's no score to compute, Elasticsearch can represent "which documents match this filter" as a cached bitset (one bit per document) per segment. The real payoff is on *repeated* identical filters — run `level: ERROR` as a `filter` clause across several different searches, and after the first one the rest reuse the cached bitset instead of re-executing the lookup. A `must` clause can never be cached this way because its output isn't just membership, it's a score that depends on exactly which query produced it.

**Hands-on:** rewrote the earlier `"connection"` `match` query, moving it from `must` into `filter` with no `must` clause left in the `bool`:

```
GET logs-app/_search
{
  "query": {
    "bool": {
      "filter": [
        { "match": { "message": "connection" } }
      ]
    }
  }
}
```

`hits.total.value` stayed at 274 — identical result set to the original `must` version. But every hit's `_score` came back as `0.0` instead of `3.0687466`, since there was no scoring clause left in the `bool` for Elasticsearch to compute a value from:

```json
{
  "hits": {
    "total": { "value": 274, "relation": "eq" },
    "max_score": 0.0,
    "hits": [
      {
        "_score": 0.0,
        "_source": {
          "timestamp": "2026-08-28T15:46:54.802406+00:00",
          "level": "DEBUG",
          "service": "inventory",
          "message": "retrying connection, attempt 39",
          "status_code": 200
        }
      },
      ...
    ]
  }
}
```

Same documents, zero scoring cost, and (per the reasoning above) cacheable — confirming the rule of thumb: use `filter` for yes/no gates (exact matches, ranges, status codes), reserve `must` for whatever should actually influence result ranking.
