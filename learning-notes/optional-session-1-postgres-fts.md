# Optional Session 1 — Postgres's built-in full-text search vs Elasticsearch

## TL;DR

Postgres's own text-search stack — `tsvector`/`tsquery` plus a GIN index, and `pg_trgm` for fuzzy/substring matching — gets run against the same 5,000-row log dataset used throughout the main project, side by side with the equivalent Elasticsearch queries from sessions 3 and 4.

For this dataset, every comparison lands on the same result count on both sides. The interesting part isn't that they agree — it's *why*, and where the two engines' internal mechanics diverge even when the numbers happen to match.

This is a side project. It doesn't feed into the main curriculum's deliverable; it answers a standalone question: what can Postgres alone actually do, and where does that stop being enough.

## Setup

A separate stack, deliberately isolated from the main ES/Kibana compose file, since this is a side project rather than an extension of it:

```
optional-session-1-postgres-fts/
├── docker-compose.yaml      # postgres:18.6, port 5432
├── .env.example
└── scripts/
    └── load_from_sqlite.py  # SQLite (source of truth) → Postgres
```

Getting `psql` itself onto this VM required two packages that weren't already installed:

```bash
sudo apt install postgresql-client-common
sudo apt install postgresql-client-18
```

## Concepts — what's actually new here

Four pieces. Each does one job, and each has a direct ES counterpart from earlier sessions.

**`tsvector`** is a preprocessed, searchable form of a text column. The words in it get reduced to lexemes — stemmed, lowercased, stopwords stripped — with each lexeme's position in the original text recorded alongside it. It's the row-level equivalent of what Lucene did to the `message` field when ES tokenized it in session 2: same job, different engine.

For example:
```
 id |                message                 |                  message_tsv
----+----------------------------------------+------------------------------------------------
  1 | cache hit for key key-7354             | '-7354':6 'cach':1 'hit':2 'key':4,5
  2 | deprecated endpoint called             | 'call':3 'deprec':1 'endpoint':2
```

**`tsquery`** is the query side of the same coin. Search terms get run through that identical normalization — so a search for "caches" and a stored "cached" both reduce to the same stem and match each other — plus boolean operators between terms: `&` (AND), `|` (OR), `!` (NOT).

**GIN index** (Generalized Inverted Index) is Postgres's actual inverted index. It stores `lexeme → list of row ids containing it` — the same data-structure shape as the inverted index sitting behind ES's `match` query. It's not optional infrastructure, it's what makes `tsquery` fast: without a GIN index on a `tsvector` column, `@@` still works, but it falls back to a full sequential scan, re-tokenizing and re-checking every single row on every search instead of doing a direct lexeme lookup.

In simple words: if we query `message_tsv` without index, it's a full sequential scan. So, this column acts as any other column in the table. If we add an index, and specifically a GIN index, we get the benefits of fast and dynamic substrings lookup (Index vs GIN Index comparison at [When to reach each tool](#when-to-reach-for-which-tool) section).

**`pg_trgm`** solves a different problem: neither `tsvector` nor `tsquery` can ever match a typo or a mid-word substring, because both only ever operate on whole, correctly-spelled lexemes. `pg_trgm` breaks a string into overlapping 3-character chunks — "trigrams" — and indexes *those* instead of whole words. `"cache"` becomes `{"  c", " ca", "cac", "ach", "che", "he "}`. Two strings that share most of their trigrams are considered similar, even if they're spelled differently or one is a typo of the other. That's what powers substring matching (`LIKE '%foo%'`) and fuzzy/typo-tolerant matching (`%`, `similarity()`) with actual index support behind them, rather than a full scan.

How the four pieces fit together, and what each maps to on the ES side:

```
tsvector + tsquery + GIN   →   ES's inverted index + `match`     (whole-word, linguistically-normalized search)
pg_trgm + GIN              →   ES's `wildcard` / `fuzzy`         (substring / typo-tolerant search)
```

| Piece | What it is | ES equivalent |
|---|---|---|
| `tsvector` | A row's text, preprocessed into stemmed, deduplicated search tokens with position info | What `_analyze` produces over a `text` field |
| `tsquery` | Search terms run through the same normalization, plus boolean operators (`&`, `\|`, `!`) | A `match`/`bool` query |
| GIN index | `lexeme → list of matching rows` — Postgres's actual inverted index | The inverted index behind ES's `match` |
| `pg_trgm` | Breaks text into overlapping 3-character chunks ("trigrams") and indexes those instead of whole words | `wildcard`/`fuzzy` queries |

**Bottom line:** `tsvector`+GIN covers the same ground as ES's `match` — whole-word, linguistically-normalized search, fast only because of the index sitting behind it. `pg_trgm` covers the same ground as `wildcard`/`fuzzy` — substring and typo-tolerant search that whole-word matching is structurally incapable of, because it only ever compares whole, correctly-spelled lexemes.

## Loading the data — SQLite stays the source of truth

The main project made SQLite the system of record back in session 6. This side project treats that as settled and loads Postgres from SQLite, not from a fresh run of the session 2 generator — one consistent data lineage instead of three independently-generated copies of "the same" dataset.

`psycopg` (v3) was picked over `psycopg2` for the same reason `better-sqlite3` was picked over the Node built-in in session 6: it's the actively-developed generation of the driver. `psycopg2` still gets maintenance patches, but no new feature development — legacy-maintenance mode, not actively developed.

`optional-session-1-postgres-fts/scripts/load_from_sqlite.py` reads every row out of SQLite, then bulk-loads it into Postgres using the `COPY` protocol instead of looping `INSERT` statements — the same idea as ES's bulk API from session 2: stream rows in one continuous operation rather than pay a round trip per row.

```python
with cur.copy(
    "COPY logs (id, timestamp, level, service, message, status_code) FROM STDIN"
) as copy:
    for row in rows:
        copy.write_row(row)
```

`write_row()` doesn't send one network packet per row. It serializes each row into COPY wire format and appends it to an internal buffer, which gets flushed over the socket in larger chunks — one continuous stream, not N request/response round trips. That's the actual mechanism behind "COPY is faster than looping INSERTs."

**Hands-on:**

```
$ uv run python optional-session-1-postgres-fts/scripts/load_from_sqlite.py
Loaded 5002 rows from .../session-5-proj/db/logs.db into Postgres logs_fts.logs
```

5002, not 5000 — the two extra rows are the write-path and recovery-drill rows from session 6, already sitting in SQLite by the time this ran.

## Task 1 — the `tsvector` column

```bash
$ PGPASSWORD=fts psql -h localhost -p 5432 -U fts -d logs_fts
```

```sql
ALTER TABLE logs
  ADD COLUMN message_tsv tsvector
  GENERATED ALWAYS AS (to_tsvector('english', message)) STORED;
```

Two choices worth naming before running it. `'english'` selects Postgres's stemming/stopword dictionary for this column — the direct equivalent of choosing an analyzer on a `text` field in an ES mapping. `GENERATED ALWAYS AS (...) STORED` means Postgres computes the tsvector once, at write time, and physically stores it — the same trade-off as ES's `doc_values` from session 4: pay storage and write cost up front so reads don't recompute anything.

* `GENERATED ALWAYS AS (...)`  
  This tells PostgreSQL that the column's value is completely controlled by the database, using the expression inside the parentheses `(to_tsvector('english', message))`.
  * **Automatic syncing:** Whenever a row is created, or whenever the original `message` column is updated, PostgreSQL automatically calculates and updates the `message_tsv` column.
  * **Strictly read-only:** You cannot manually `INSERT` or `UPDATE` data into this column. If you try to force a specific value into `message_tsv`, PostgreSQL will reject it and throw an error.
* `STORED`  
  This dictates how PostgreSQL handles the computed data under the hood.
  * **Written to disk:** `STORED` means the result of the calculation is physically saved to the disk. The database calculates the vector exactly once (during the insert/update) rather than calculating it on the fly every time you run a **SELECT** query.
  * **Performance:** Because the data is already computed and sitting on the disk, read queries are incredibly fast. The database doesn't waste CPU cycles re-parsing the English text into a search vector for every search.
  * **PostgreSQL context:** Postgres 18 — the version this project runs — added a second mode, `VIRTUAL`, computed on read instead of on write, and made it the *default* when neither `STORED` nor `VIRTUAL` is specified. Writing `STORED` explicitly here isn't a formality: leaving it off on this version would silently produce a `VIRTUAL` `message_tsv` instead, recomputed from `message` on every read rather than persisted.

**Hands-on:**

```sql
SELECT id, message, message_tsv FROM logs LIMIT 3;
```

```
 id |                message                 |                  message_tsv
----+----------------------------------------+------------------------------------------------
  1 | cache hit for key key-7354             | '-7354':6 'cach':1 'hit':2 'key':4,5
  2 | deprecated endpoint called             | 'call':3 'deprec':1 'endpoint':2
  3 | unhandled exception processing request | 'except':2 'process':3 'request':4 'unhandl':1
```

Three real mechanics visible in that output:

- **Stemming, not readable text.** `cache`→`cach`, `deprecated`→`deprec`, `exception`→`except`. These are stems, a common root, not real words — `cache`/`caches`/`cached` all collapse onto the same searchable token.
- **Stopword removal at write time.** `for` disappears entirely from row 1's vector. Searching for `for` later matches nothing, ever, regardless of context — the `'english'` config treats it as noise and never indexes it.
- **Hyphen splitting.** `key-7354` produces two lexemes, not one: `'key':4,5` (merged with the standalone `key` at position 4) and `-7354':6` as its own token.

**A real edge case worth naming, not glossing over:** stemming can collide two unrelated words onto the same lexeme. `except` here is the stem of `exception`, but it's also the stem of the word `except` itself — search for one and both match. That's an accuracy cost deliberate in full-text stemming, not a bug.

## Task 2 — GIN index, `tsquery`, and the ES comparison

```sql
CREATE INDEX idx_logs_message_tsv ON logs USING GIN (message_tsv);

SELECT count(*) FROM logs WHERE message_tsv @@ to_tsquery('english', 'cache & hit');
```

`@@` is the "does this tsvector match this tsquery" operator — what the GIN index actually accelerates.

**Hands-on:** After running the query above on Postgres, run this query on ES:
```
GET logs-app/_search
{
  "query": {
    "match": {
      "message": "cache hit"
    }
  },
  "size": 0,
  "track_total_hits": true
}
```
The first run compared against ES's default `match` query and diverged sharply — 910 (SQL) vs 1151 (ES). The reason: `&` in `to_tsquery` is a hard AND, both stems required in the same document, while ES's `match` defaults to `operator: "or"` — matching a document containing *either* term. Same-looking query, different default logic.

Forcing ES to `operator: "and"` for a fair comparison:

```
GET logs-app/_search
{
  "query": {
    "match": {
      "message": {
        "query": "cache hit",
        "operator": "and"
      }
    }
  },
  "size": 0,
  "track_total_hits": true
}
```

```
Postgres: 910
ES:       910
```

Exact match: 910 = 910. That's real signal, but worth naming the caveat honestly rather than treating it as a general rule: it's an exact match. This dataset's message templates (`scripts/generate_logs.py`) never inflect "cache" or "hit" — no "caches," no "hits". ES's standard analyzer doesn't stem at all, it just lowercases and splits on word boundaries. If the generator ever produced "cached" or "hits," Postgres's stemmer would still match them under `cache`/`hit`, but ES's un-stemmed analyzer wouldn't unless that literal token appeared. Same result today, different mechanism, and they'd diverge on different vocabulary.

## Deep dive — where `message_tsv` actually lives on disk

Postgres is a row store. Every column of a row — `id`, `message`, `message_tsv`, all of it — lives together in one physical record, a heap tuple, in the table's heap file. `message_tsv` being a *generated* column only describes how its value gets computed; once computed, it's stored exactly like any other column, inline, in the same tuple.

```
Heap tuple for row id=1:
┌────┬─────────────────────────────┬──────────────────────────────────┐
│ id │ message                     │ message_tsv                      │
│ 1  │ "cache hit for key key-7354"│ 'cach':1 'hit':2 'key':4,5 ...    │
└────┴─────────────────────────────┴──────────────────────────────────┘
        one physical record, all columns together
```

That's why `SELECT id, message, message_tsv FROM logs LIMIT 3` needed no GIN index at all — it's a plain heap scan, reading whichever columns were asked for out of each tuple.

The GIN index is a separate physical structure, built and maintained alongside the heap, that exists only to answer the reverse question: *which tuples contain lexeme X*. It stores `lexeme → list of tuple locations`, the same shape as ES's inverted index (`term → doc ids`).

```
GIN index (separate structure, not inside the heap):
'cach'  →  [tuple(1), tuple(10), tuple(17), ...]
'hit'   →  [tuple(1), tuple(10), tuple(27), ...]
```

`message_tsv @@ to_tsquery(...)` walks this structure to find candidate tuples, then fetches those specific tuples from the heap. Without the index, the same query still works — it just sequentially scans every heap tuple and recomputes the match by hand, row by row.

| Direction | What answers it | Where it lives |
|---|---|---|
| row → its own columns | heap scan | heap tuple (every column, always) |
| token → matching rows | GIN index scan | separate index structure |

A GIN index isn't architecturally special, either. It's the same relationship as any other index type to its table — a bolt-on structure pointing back at heap tuples — just built differently internally. A B-tree maps one sorted key to one or few tuple pointers, good for `=`/`<`/`>`/sorting. GIN maps one key (a lexeme, or a trigram) to *many* tuple pointers — a posting list — good for "this row contains X" membership checks over composite values like a `tsvector` or an array.

**Bottom line:** Postgres never needed an ES-style `doc_values` structure, because "give me column X for row Y" was already free — that's just what a row store does by default. ES needed `doc_values` because Lucene's native storage is the inverted index itself, which doesn't natively answer that direction at all.

## Task 3 — `pg_trgm` and fuzzy matching

```sql
CREATE EXTENSION pg_trgm;
CREATE INDEX idx_logs_message_trgm ON logs USING GIN (message gin_trgm_ops);
```

A first attempt at a typo search (`exceptoin` instead of `exception`) used the plain `%` similarity operator and returned zero rows:

```sql
SELECT id, message FROM logs WHERE message % 'exceptoin';  -- 0 rows
```

Not a broken query — a real `pg_trgm` gotcha. `%` has a default similarity threshold (0.3) and compares the *whole* `message` string against the query, as raw characters. `similarity()` is `shared trigrams ÷ total distinct trigrams across both` — a set ratio, not a character-length ratio. Worked out for real: `exceptoin` shares only 6 trigrams with the message's 39, giving `6/43 ≈ 0.14` (union size is `10 + 39 − 6`) — well under the 0.3 threshold, which is why this returned zero rows. The general lesson: comparing a short query against a long multi-word string dilutes the ratio fast, since every other word in the message adds trigrams to the total that can never match. This is a genuine pitfall of `pg_trgm` on document-length columns, not something specific to this dataset.

The fix is `word_similarity()` / the `<%` operator, which finds the best-matching substring of comparable length inside the longer string, rather than scoring the two full strings against each other:

```sql
SELECT id, message, word_similarity('exceptoin', message)
FROM logs
WHERE 'exceptoin' <% message
ORDER BY word_similarity('exceptoin', message) DESC
LIMIT 5;
```

```
 id |                message                 | word_similarity
----+----------------------------------------+-----------------
 13 | unhandled exception processing request |             0.6
 ...
```

```sql
SELECT count(*) FROM logs WHERE 'exceptoin' <% message;  -- 89
```

Compared against ES's edit-distance `fuzzy` query:

```
GET logs-app/_search
{
  "query": {
    "fuzzy": {
      "message": {
        "value": "exceptoin",
        "fuzziness": "AUTO"
      }
    }
  }
}
```

Both land on exactly 89. Checked directly against `scripts/generate_logs.py` rather than assumed: `"unhandled exception processing request"` is one of only three fixed `ERROR`-level templates, with zero wording variation — it's the only string in the entire 5,000-row dataset containing anything resembling "exception." Both queries are really answering "does this one literal template exist," not genuinely fuzzy-ranking varied text. `pg_trgm`'s trigram overlap and ES's edit-distance `fuzzy` are different mechanisms and would plausibly disagree on a messier, more varied corpus — this dataset's low vocabulary variety doesn't expose that.

**On why the stemmer didn't touch `exceptoin` at all:** Postgres's `'english'` dictionary (the Snowball stemmer) is a fixed sequence of suffix-stripping *rules* — deterministic pattern matching on literal letter sequences, not machine learning. One rule recognizes the literal substring `-tion` and strips it (`exception`→`except`). `exceptoin` has its letters transposed — it ends in `-toin`, matching no rule — so the stemmer leaves it completely untouched. That's an exact letter-for-letter requirement, not approximate closeness, and it's exactly why stemming/`tsquery` can't handle typos at all — the reason `pg_trgm`'s character-overlap approach exists as a separate tool.

## When to reach for which tool

A B-tree index and `LIKE` are sometimes enough on their own, and reaching for GIN when they'd do costs real, avoidable disk space. So, when to use which?

| | B-tree + `LIKE` | `pg_trgm` + GIN | `tsvector` + GIN |
|---|---|---|---|
| Handles | `'foo%'` — prefix only | `'%foo%'` anywhere, fuzzy, `~` regex | Whole-word, stemmed, ranked |
| Extra storage | Same as any normal index | Larger — every substring's trigrams get indexed | Moderate — one entry per stemmed lexeme |
| Write-time cost | Standard index maintenance | Recompute trigram set on every write | Recompute `tsvector` on every write |
| Relevance ranking | None | `similarity()` score only | `ts_rank` |

A B-tree can only accelerate `LIKE` when the pattern is anchored at the start — it's a sorted structure, and there's no way to binary-search toward "contains this substring anywhere." There's a locale gotcha too: in a non-`C` locale, even prefix `LIKE` needs the index built with `text_pattern_ops` (or `varchar_pattern_ops`), because default B-tree ordering follows locale collation rules rather than raw byte comparison — and a second, separate default-opclass index is needed alongside it if normal `<`/`>`/`ORDER BY` on that column is also required.

**Bottom line:** if a column is only ever searched by prefix — a service code, a SKU, a username autocomplete — a plain B-tree costs nothing extra. `pg_trgm` earns its storage cost only once the wildcard needs to sit in the middle, or typo tolerance is a real requirement. `tsvector` earns its cost only once word-level, stemmed, ranked search is actually needed. `LIKE` alone has no linguistic normalization and no ranking at all.

## Deep dive — ranking and aggregation, structurally

**`ts_rank` has no IDF, at all.** Ranking functions "do not utilize global information." `ts_rank` has no concept of how rare a term is across the whole table — a term appearing in 2% of rows and one appearing in 60% of rows count identically. BM25 (session 3) explicitly weights rare terms higher via IDF; `ts_rank` cannot make that distinction structurally, not just by default configuration.

**No length normalization by default, either.** `ts_rank`'s `normalization` parameter defaults to `0` — off. A one-line message and a ten-paragraph document containing the same term the same number of times score identically. BM25 has length normalization (`b`) built into its formula from the start.

**Weights are opt-in.** `to_tsvector()` tags every lexeme with weight `D` (0.1) unless `setweight()` is called manually to promote specific spans to `A`/`B`/`C`. ES gets field-level boosting and real BM25 math on every field by default.

| | `ts_rank` | BM25 (ES) |
|---|---|---|
| Uses corpus-wide term rarity (IDF) | No — never | Yes, always |
| Length normalization | Off by default, opt-in bitmask | Built into the formula |
| Field/section weighting | Manual, via `setweight()` | Automatic per-field, boostable |
| What it measures | Local, weighted term frequency | Frequency × rarity × length-adjusted |

**Bottom line:** `ts_rank` answers "does this document mention the terms a lot." BM25 answers "is this document unusually relevant compared to the rest of the corpus." Those are different questions.

**Aggregations: `GROUP BY`, not a distributed framework.** Session 4 covered how ES's `terms` aggregation runs: each shard computes its own partial buckets independently and in parallel off `doc_values`, then a coordinator merges them — which is exactly why `shard_size` and `doc_count_error_upper_bound` exist. A single Postgres instance runs `GROUP BY` as one query plan against one dataset, no fan-out and no partial-merge step, because there's only one place doing the work.

The bigger gap is nesting. ES can nest a metric inside a bucket inside a bucket in one request tree (session 4: `terms` by service → `date_histogram` by hour → `avg` response time, one query). A flat `GROUP BY service, date_trunc('hour', ts)` reproduces that one case, but the moment bucket shapes need to differ per branch, SQL has no equivalent to a nested aggregation tree — it needs `GROUPING SETS`, window functions, or several queries stitched together in application code.

**Does `GROUP BY` lose data the way `terms` can?** No, and the reason is a merge-order choice, not a property of sharding. ES's approximation exists because each shard truncates to its own local top-`shard_size` terms *before* sending anything to the coordinator — a term that's globally significant but not locally top-N on any single shard can be missed. Postgres's planner, even across parallel workers or partitions, computes a *complete* partial count for every group first, merges those into exact global counts, and only then applies `LIMIT`. Nothing is discarded before the numbers are exact — but that's not free forever. It's exactly why Citus (a distributed-Postgres extension, which allows sharding) offers a `topn` extension for *approximate* top-K: past a certain cardinality and node count, exact merge-everything stops being cheap, and the same shard-then-merge tension ES optimizes for by default resurfaces.

**Operational cost — the side that has nothing to do with query power.** Session 1 set up ES/Kibana with explicit JVM heap flags, a memory hard cap, and a documented cluster-health cycle — real, ongoing operational surface. Postgres, in this project, cost nothing additional to operate: it's the database already running for everything else, backed up and monitored the same as any other table.

| | Postgres FTS | Standalone Elasticsearch |
|---|---|---|
| New infrastructure | None — same DB, same backups | A second stateful, distributed system |
| Scaling model | Vertical, or Citus for horizontal | Horizontal — add nodes, shards rebalance |
| Failure modes to watch | Whatever's already monitored for Postgres | JVM heap pressure, shard allocation, cluster health |
| Schema change cost | `ALTER TABLE`, in place | Mapping is write-once — new index + reindex |

**On Postgres horizontal scaling specifically (DB sharding):** Citus is a real, legitimate answer — it distributes tables across worker nodes by a shard key and parallelizes queries across them, genuine horizontal scale, not a Postgres dead end. But it trades away the "no new infrastructure" argument: running Citus means operating a coordinator plus worker nodes, shard rebalancing, and distributed transaction coordination — comparable operational surface to running ES, not simpler than it. And a GIN-indexed text search under Citus still has to fan out per shard and merge results at the coordinator, the same shape as ES's shard-then-merge model, with the same accuracy tension at high cardinality. Past the point where data no longer fits comfortably on one node, the choice stops being "Postgres vs. Elasticsearch, pick the simpler one" and becomes "which distributed system's operational model and query shape fits better" — a different, harder question.

## The verdict for this project

For this specific 5,000-row synthetic log dataset and the query patterns actually exercised — whole-word search, boolean combination, typo-tolerant lookup — standalone Elasticsearch was never needed. Every query run this session landed on the identical result Postgres FTS produced, at zero additional operational cost, because this dataset never exercised the areas where the two engines actually diverge: no relevance-quality requirement beyond "does it match," no nested multi-level aggregation, no data volume anywhere near a single Postgres instance's ceiling.

The recommendation for a project shaped exactly like this one: skip Elasticsearch, use `tsvector`+GIN and `pg_trgm` directly on the database already being run. The trigger to revisit that decision isn't "full-text search is involved" — it's any one of: data outgrowing one node's memory/disk under real concurrent load, a genuine relevance-quality requirement where BM25's IDF and length normalization matter to the product, or aggregation needs that outgrow flat `GROUP BY` into real nested bucket/metric trees. None of those three showed up here.
