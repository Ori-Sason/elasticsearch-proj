# Session 3 — Search fundamentals

## TL;DR

Learned the Query DSL against the `logs-app` dataset: `match` (analyzed, free-text) vs `term` (exact, unanalyzed), `match_phrase` (analyzed but ordered and adjacent) for a step in between, and a `keyword` multi-field for exact whole-value equality on a `text` field without changing its type. Covered `bool` for combining conditions via `must` (scores) vs `filter` (yes/no, cacheable). Went deep on why deep pagination (`from`) gets expensive — a per-shard bounded heap, not a full scan — and used `_explain` to see BM25 relevance scoring broken into its real formula pieces. Confirmed hands-on that moving a clause from `must` to `filter` returns the exact same documents but drops scoring entirely.

## Request lifecycle

Every query this session flows through the same pipeline, just with different pieces lighting up depending on what you send.

```
                    GET logs-app/_search
                            │
                            ▼
                 ┌────────────────────┐
                 │   Query DSL body   │  match / term / bool
                 └──────────┬─────────┘
                            │  broadcast to every shard
              ┌─────────────┼──────────────┐
              ▼             ▼              ▼
          Shard 1         Shard 2        Shard 3
       (each one independently):
         - "must" clauses  → BM25 score
         - "filter" clauses → yes/no bitset (cacheable, no score)
         - streaming top-K heap, size K = from + size
              └────────────┼──────────────┘
                           ▼
                Coordinating node merges
             num_shards × K candidates, re-sorts,
             returns hits[from : from+size]
```

`logs-app` runs on a single primary shard in this cluster, so the "merge across shards" step collapses to one shard talking to itself — but the mechanism is identical, it's just not visible with only one shard.

## Walkthrough

### `match` vs `term`: analyzed search vs. exact match

A query is just a JSON document you POST to a search endpoint describing what you want.

Think of `match` like typing into a search box. It doesn't care about your exact wording — it breaks your input into tokens and looks for documents containing those tokens. Think of `term` like scanning a spreadsheet column for one exact cell value. No fuzziness, no interpretation, byte-for-byte comparison.

`match` runs your input through the same analyzer the target field used at index time. That's why a `match` query against `message` (a `text` field, see [session 2](/learning-notes/session-2-model-and-load-data.md)) finds `"connection"` inside `"retrying connection, attempt 39"` — the query string and the stored value aren't identical text, but they tokenize the same way.

`term` skips analysis entirely, so it needs a `keyword` field, not `text`. A `text` field never stores the original string as one token, only the analyzer's chopped-up output — so a `term` query for a whole phrase or the original casing almost never matches anything in a `text` field.  
There's one coincidence worth knowing: a single word that's already lowercase with no punctuation analyzes to itself, unchanged. A `term` query for that one word can match a `text` field by accident. The moment the value is multi-word, mixed-case, or has punctuation, that coincidence breaks and `term` stops matching.

| | `match` | `term` |
|---|---|---|
| Runs the analyzer | Yes | No |
| Compares against | Analyzed tokens | Raw stored value, byte-for-byte |
| Target field type | `text` (usually) | `keyword` (usually) |
| Multi-word input | OR across tokens by default | Exact whole-value match only |

**Bottom line:** by default, `match` on multi-word input is an OR across the resulting tokens — any token matching is enough, and more matching tokens just push the score higher. Requiring *all* conditions at once is what `bool` is for, next topic.

**Hands-on:** ran a `match` query against `message`:

```
GET logs-app/_search
{
  "query": {
    "match": { "message": "timeout" }
  }
}
```

Zero hits — not a bug, a real fact about the dataset. [`generate_logs.py`](/scripts/generate_logs.py)'s `MESSAGES` templates never contain the literal token `timeout`. The closest is `"database query timed out after {ms}ms"`, which tokenizes to `timed`, `out`, `after`... — separate tokens, not `timeout`. `match` matches exact analyzed tokens, no stemming and no synonyms by default, so `timed` ≠ `timeout`.

Same query for `"connection"` returned 274 hits, all from the one `DEBUG`-level template that actually contains that word:

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

Every hit had the identical `_score` of `3.0687466`. Same token, same term frequency (1), same field length (4 tokens), every time — so same score every time. The BM25 section below explains why that's exactly what the formula predicts.

Then ran a `term` query on the `keyword` field `level`:

```
GET logs-app/_search
{
  "query": {
    "term": { "level": "ERROR" }
  }
}
```

The generator weights `ERROR` at 5 out of 100 (`LEVEL_WEIGHTS` in [`generate_logs.py`](/scripts/generate_logs.py)), so roughly 5% of 5,000 documents should land here — about 250. The query returned 242, well within normal sampling variance for `random.choices`-driven weighted selection:

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

### `match_phrase`, and matching a whole field, while staying `text`

`match` and `term` sit at two extremes — any token, or an exact whole value on an unanalyzed field. Two more tools sit in between, and both still work on a `text` field without ever changing its mapping type: `match_phrase` for an exact, ordered phrase, and a `keyword` multi-field for exact whole-value equality.

**`match_phrase`: same tokens, but ordered and adjacent.** A `text` field's inverted index stores each token's *position*, not just its presence — that's `index_options: positions`, the default for `text`. `keyword` fields skip this entirely, since the whole value is one token with nothing to check adjacency against. `match_phrase` analyzes the query exactly like `match` does, then requires every resulting token to appear in the field in that order, with no gap between them by default — a `slop` parameter widens that allowed gap if needed.

| | `match` | `match_phrase` |
|---|---|---|
| Token requirement | any one token (OR across tokens) | all tokens, in that order |
| Adjacency required | No | Yes — gap 0 by default, widen with `slop` |
| Matches a token subsequence, not the whole value | Yes | Yes |

```
GET logs-app/_search
{
  "query": {
    "match_phrase": { "message": "retrying connection" }
  }
}
```

Every `"connection"`-containing document in this dataset comes from the single `DEBUG` template `"retrying connection, attempt {n}"` (see [`generate_logs.py`](/scripts/generate_logs.py)), so `"retrying"` always sits immediately before `"connection"`. This phrase query should land on the same 274 documents the plain `match "connection"` query found earlier.

**Exact whole-value match: a `keyword` multi-field, not a workaround.** Neither `match` nor `match_phrase` can express "the field's entire value equals this, nothing more" — both work in terms of token containment, never full-value equality. Getting that without changing `message`'s type to `keyword` means adding a `keyword` **multi-field**: a second, sibling field indexed from the same source value, unanalyzed.

```
PUT logs-app/_mapping
{
  "properties": {
    "message": {
      "type": "text",
      "fields": {
        "exact": { "type": "keyword" }
      }
    }
  }
}
```

`message` keeps its type and its analyzed inverted index untouched; `message.exact` is a second index over that same underlying value, storing it byte-for-byte. Query it with `term`, exactly like any other `keyword` field:

```
GET logs-app/_search
{
  "query": {
    "term": { "message.exact": "retrying connection, attempt 39" }
  }
}
```

**Bottom line:** the two exact-ish options differ in *sensitivity*, not just syntax. `term` on the `keyword` multi-field is case-, punctuation-, and whitespace-sensitive — it compares the literal stored bytes. `match_phrase`, even when it happens to span the whole field, still goes through the same analyzer as `match`: case and punctuation are normalized away, and `"attempt"` / `"attempts"` are unrelated tokens to it. Use `match`/`match_phrase` for anything that should tolerate the analyzer's normalization; reach for a `keyword` multi-field when it shouldn't.

### `bool`: `must` vs `filter`

`bool` combines multiple conditions, but its clauses aren't interchangeable — even though both require the condition to hold true.

A useful mental model: `must` is a judge scoring a contest entry — the entry has to qualify, and *how well* it qualifies affects the score. `filter` is a bouncer checking ID at the door — you're either on the list or you're not, and nothing about *how* you're on the list makes you more or less welcome once you're in.

Only `must` contributes to `_score`. `filter` is a pure yes/no gate that contributes nothing to relevance. For a deterministic condition — an exact `term` match, say — the *result set* comes out identical whichever clause it sits in. What differs is the score, and, as the "Query context vs filter context" section below covers, the performance characteristics.

**Hands-on:** first attempt combined the two earlier queries — free-text on `message`, exact filter on `level`:

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

Zero hits — and not by chance. By [`generate_logs.py`](/scripts/generate_logs.py), the only message that has the word `connection` is `retrying connection, attempt {n}`. However, this is part of `level: DEBUG`. Therefore, there is no document that can apply both `filter` and `must`.

`service`, by contrast, is assigned independently of `level`/`message`, so filtering on it can't contradict the `must` clause.

```
GET logs-app/_search
{
  "query": {
    "bool": {
      "must": [
        { "match": { "message": "connection" } }
      ],
      "filter": [
        { "term": { "service": "inventory" } }
      ]
    }
  }
}
```

56 hits out of the 274 total `"connection"` matches:

```json
{
  "hits": {
    "total": { "value": 56, "relation": "eq" },
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

**Bottom line:** use `must` when a condition should actually move the ranking. Use `filter` for anything that's just a hard yes/no gate — but pick a field that's actually independent of the `must` clause, or the combination can be vacuous (as with `level` here) instead of illustrative.

### Sorting and pagination

By default, results sort by `_score` descending. When will we want that? for example data log usually should be sorted by date, regardless of relevance — that's what `sort` is for. When you sort by a field, `_score` stops getting computed by default and comes back `null`, since the ranking no longer depends on it. `from`/`size` then give you an offset-based page into the sorted results.

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

Returned the 5 most recent `ERROR` logs, ordered purely by `timestamp`, no `_score` involved:

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

**Why deep pagination (a large `from`) gets expensive.** This isn't a full-table-scan problem, and it's not about "the data being sorted on disk" either — Elasticsearch has no single physical sort order for an index at all, unlike a relational DB where a clustering key gives the table one privileged order. Instead, every field gets its own **`doc_values`**: a columnar, per-field, per-document structure built at index time, separate from the inverted index used for search, that answers "what's this field's value for document N" efficiently. Sorting — and later, aggregations in session 4 — runs over `doc_values`, not the inverted index. No field is privileged the way a clustering key is in a relational DB; every field's `doc_values` are equally cheap to sort by.

Finding *which* documents match a query costs the same no matter what `from` is — the posting-list walk for `level: ERROR` doesn't change size based on pagination depth. What changes is a separate step downstream: each shard runs a streaming top-K algorithm, keeping a bounded max-heap of size `K = from + size` as it streams through matches. A better-sorted document knocks the worst entry out of the heap. That's `O(N log K)`, not `O(N log N)` — the shard never fully sorts all N matches, just maintains a heap of size K.

```
from=20, size=10   →   K = 30

  Shard 1          Shard 2          Shard 3
 ┌─────────┐      ┌─────────┐      ┌─────────┐
 │ heap: 30│      │ heap: 30│      │ heap: 30│   each shard streams its
 └────┬────┘      └────┬────┘      └────┬────┘    matches, keeps only its
      │                │                │         own top 30
      └────────────────┼────────────────┘
                       ▼
            Coordinating node merges
          3 × 30 = 90 candidates, sorts
            them, returns docs 21–30 —
             discards the other 80
```

Two costs stack on top of the heap itself. First, every shard ships its *entire* top-K, not just the final page, to the coordinating node — so network payload per shard scales with K, not with `size`. Second, the coordinating node has to merge `num_shards × K` candidates and re-sort them just to throw away everything before position `from`.

Ask for `from: 0, size: 10` instead of `from: 20, size: 10`, and each shard only ever builds and ships a heap of 10 — the coordinator merges just `3 × 10 = 30` candidates. Same query, one-third the work, purely because `K` shrank.

**Bottom line:** cost doesn't scale with `size`, it scales with `from + size`. A shallow page near the top stays cheap no matter the `size`. A deep page stays expensive even with a small `size`, because every shard still has to build, ship, and merge a heap that reaches all the way down to `from`.

`search_after` (not implemented this session, but worth knowing exists) sidesteps this entirely. Instead of "give me the top `from + size` so I can discard the first `from`," it takes a cursor — the sort values of the last document you saw — and asks for "whatever comes strictly after this." No heap grows as pagination goes deeper.

### Scoring mechanism: BM25 via `_explain`

`GET <index>/_explain/<doc_id>` runs a query against one specific document and hands back the actual score computation instead of just the final number.

This is how the BM25 formula's pieces got inspected against real data instead of staying abstract.

```
score = idf  ×  tf
         │      │
         │      └─ tf = freq·(k1+1) / (freq + k1·B)
         │                                       │
         │                                       └─ B = 1 - b + b·(dl/avgdl)
         │  
         └─ idf = log(1 + (N - n + 0.5) / (n + 0.5))
```

Three named quantities, each with a distinct job:

- **`idf` (inverse document frequency)** — how rare the term is *across the whole corpus*. Think of it like a word in a crossword clue: the more common the word, the less it narrows things down. `idf` trends toward 0 for a term nearly every document has, since that term carries no discriminating information. The fewer documents contain it, the higher `idf` climbs — rare terms are more informative when they do show up, so they're weighted higher.
- **`tf` (term frequency, with saturation)** — how much a term's *repeated occurrence within one document* should matter. In isolation this is a saturating curve on `freq` alone, something like `freq/(freq + k1)` — diminishing returns per extra occurrence rather than a linear reward, the same way hearing a joke a second time doesn't make it twice as funny. `k1` controls how fast that saturation kicks in.
- **`b` (field-length normalization)** — a term match in a short field should generally count for more than the same match in a long field, since the long field had more "opportunity" to contain the word incidentally — a one-line status update mentioning "connection" is more clearly about connections than the same word buried in a 10,000-word essay. That correction is expressed as `B = 1 - b + b·dl/avgdl`, where `dl` is this document's field length in tokens and `avgdl` is the corpus average. `b` controls how strongly the correction applies: `b=0` disables it, `b=1` applies it fully, and Elasticsearch's default is `0.75`.

`tf` and `b` aren't separate pieces bolted on after `idf` — they're fused into one shared fraction, because `B` corrects `k1` inside `tf`'s own denominator: `tf = freq / (freq + k1·B)`. `freq` shows up twice in the full formula — once alone in the numerator, capped by a `(k1+1)` ceiling, and again inside the denominator's `k1·B` term.

**Hands-on:** ran `_explain` for the `"connection"` match against one of the earlier hits:

```
GET logs-app/_explain/ylcPYaAB2lPiMDlQDoKi
{
  "query": {
    "match": { "message": "connection" }
  }
}
```

Returned (trimmed to the numbers that matter):

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

By hand: `idf = log(1 + (5000 - 274 + 0.5)/(274 + 0.5)) = log(18.223) ≈ 2.9024`, matching. `"connection"` shows up in 274 of 5,000 documents — about 5.5%, moderately rare, so it carries real weight. `tf = 1 / (1 + 1.2·(1 - 0.75 + 0.75·(4/4.6108))) = 1 / 2.0808 ≈ 0.4806`, also matching. `dl` (4) sits close to `avgdl` (4.6108) here, so length normalization barely moves this particular hit's score either way. `2.2 × 2.9024 × 0.4806 ≈ 3.0687` — matches the reported score.

Plugging in `freq=2` instead of `freq=1` (same `k1`, `b`, `dl`, `avgdl`) makes the saturation effect concrete: `tf(freq=2) = 2/(2 + 1.2·0.9007) = 2/3.0808 ≈ 0.6491`, versus `tf(freq=1) ≈ 0.4806`.

**Bottom line:** doubling the term count only pushed `tf` up about 35%, not 100% — exactly the diminishing-returns behavior `k1` is built to produce.

### Query context vs filter context

A `filter` clause produces only membership — yes or no — never a score. That's what makes it faster than an equivalent `must`. Because there's no score to compute, Elasticsearch can represent "which documents match this filter" as a cached bitset, one bit per document, per segment — like a bouncer's guest list that stays valid for the whole night instead of being re-checked from scratch at every door. The payoff shows up on *repeated* identical filters: run `level: ERROR` as a `filter` clause across several searches, and after the first one, the rest reuse the cached bitset instead of re-executing the lookup. A `must` clause can never be cached this way, because its output isn't just membership — it's a score that depends on exactly which query produced it.

| | `must` | `filter` |
|---|---|---|
| Contributes to `_score` | Yes | No |
| Cacheable as a bitset | No | Yes |
| Use when | Result should affect ranking | Pure yes/no condition |

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

`hits.total.value` stayed at 274 — identical result set to the `must` version. But every hit's `_score` came back `0.0` instead of `3.0687466`, since there was no scoring clause left in the `bool` for Elasticsearch to compute a value from:

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

Same documents, zero scoring cost, and — per the reasoning above — cacheable.

**Bottom line:** use `filter` for yes/no gates — exact matches, ranges, status codes. Reserve `must` for whatever should actually influence result ranking.

## Questions I Had

**Why did searching for `"timeout"` return zero hits when the logs clearly have timeout-related messages?**
Because `match` compares analyzed tokens, not substrings. The dataset's actual message is `"database query timed out after {ms}ms"`, which tokenizes to `timed`, `out`, `after` — never the token `timeout`. No stemming or synonym expansion happens by default, so `timed` and `timeout` are just different tokens.

**Can `term` ever match a `text` field, given that it skips analysis?**
Only by coincidence — if the stored value is a single lowercase word with no punctuation, the analyzer leaves it unchanged, so it happens to equal its own analyzed token. Anything multi-word, mixed-case, or punctuated breaks that coincidence immediately.

**What's the `"boost": 2.2` in the `_explain` output — did we configure a relevance boost somewhere?**
No. It's `k1 + 1 = 1.2 + 1 = 2.2`, the `(k1+1)` ceiling factor from the `tf` formula. Lucene's `_explain` output splits it into its own labeled node instead of folding it into `tf`'s display, which makes it look like a configured boost when it isn't one.

**If I sort by a field instead of relevance, do I still get a `_score` back?**
No — it comes back `null`. Once ranking no longer depends on `_score`, Elasticsearch skips computing it by default.

**If Elasticsearch doesn't do a full scan, why does a large `from` still get expensive?**
Because the expensive part isn't finding matches, it's the top-K heap every shard has to build and ship, sized `K = from + size`. A deep `from` forces a big heap regardless of how small `size` is, and the coordinator still has to merge and re-sort `num_shards × K` candidates just to throw most of them away.
