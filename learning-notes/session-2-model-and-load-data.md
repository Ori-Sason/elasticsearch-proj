# Session 2 — Model and load data

## TL;DR

Designed an explicit mapping for a log document (`timestamp`/`date`, `level`/`keyword`, `service`/`keyword`, `message`/`text`, `status_code`/`integer`), created the `logs-app` index with it, then wrote a Python script that generates 5,000 realistic synthetic logs and bulk-indexes them via the Elasticsearch client's bulk helper. Verified the doc count, inspected the actual tokens `text` vs `keyword` fields produce, and confirmed mapping immutability by trying (and failing) to change a mapped field's type on the live index.

## Mapping and index design

**Mapping** is Elasticsearch's equivalent of a schema: field names and types, defined explicitly rather than left to inference. It does more than a SQL schema, though — for string fields it also determines how the value is processed before it becomes searchable (analysis, covered in its own section below).

**`keyword` vs `text`** — both hold JSON strings, but behave completely differently. A `keyword` field is stored **exactly as given**: one atomic token, case preserved, nothing split apart. It behaves like a dropdown value once stored, but Elasticsearch itself doesn't enforce that — nothing stops a document from writing `level: "WHOOPS"` (we don't define a unique list of possible values). A `text` field is run through an analyzer at index time and is meant for full-text search, not exact matching.

**Choosing a field's type by query pattern, not by "what kind of value is it"** — `status_code` is a number, so `integer` looks obvious, but the real reason is that the project needs range queries (`status_code >= 500` to isolate error-class responses) and, later, numeric aggregations (`avg`, histograms) over it — only a numeric type supports those. If the only planned use were exact-match filtering and counting distinct codes, `keyword` would technically work too. The type decision follows from how the field will actually be queried.

**Why relying on dynamic mapping is risky** — by default, an index with no mapping yet infers each field's type from whatever document arrives first: a JSON string becomes `text` (with an auto-generated `keyword` sub-field), a number becomes `long`/`double`, an ISO-looking string becomes `date`. The guess is only as good as that first document, and mistakes are expensive to fix (a field's type is effectively locked in once real documents exist under it — the full reasoning is in [Mapping immutability](#mapping-immutability) below), so this project mapped explicitly instead.

**Hands-on:** put those decisions together and created the `logs-app` index with an explicit mapping via Kibana Dev Tools:

```
PUT logs-app
{
  "mappings": {
    "properties": {
      "timestamp":   { "type": "date" },
      "level":       { "type": "keyword" },
      "service":     { "type": "keyword" },
      "message":     { "type": "text" },
      "status_code": { "type": "integer" }
    }
  }
}
```

returned `"acknowledged": true`, `"shards_acknowledged": true` — the index exists with these five fields locked to these types before a single document was written. As with `test-logs` in session 1, it picked up the default `number_of_replicas: 1`, which the single-node cluster can't place, so the cluster went yellow again (same allocator behavior covered in [session 1](/learning-notes/session-1-cluster-fundamentals.md)).

## Generating and bulk-loading data

**The bulk API's actual format and purpose** (check out [generate_logs.py#bulk method](/scripts/generate_logs.py)) — indexing documents one at a time means one HTTP round trip per document; the bulk API batches many index operations into a single request, which is dramatically faster. Its wire format is newline-delimited JSON (NDJSON), not a JSON array — **each document** becomes two lines, an action/metadata line and a source line:

```
{"index":{"_index":"logs-app"}}
{"timestamp":"...","level":"ERROR","service":"billing","message":"...","status_code":500}
```

This lets Elasticsearch stream and parse line-by-line instead of buffering and parsing one large JSON array in memory.

**Why a partial bulk failure doesn't abort the whole batch** (notice that we set `bulk()` to return errors instead of raising an error) — the bulk API processes every line independently and returns a per-item result array; a bad document among 5,000 shows up as one failed item, the other 4,999 still succeed. This isn't just convenience — it follows from how documents route to shards. Each document's target shard is `hash(_id) % number_of_primary_shards`, so the documents in one bulk request are typically scattered across many shards. Making the whole batch atomic (all-or-nothing) would require a distributed transaction coordinated across every shard involved — real coordination cost, for a system whose whole design point is high-throughput ingestion, where an individual document failing is expected and recoverable, not exceptional. Contrast with a single-node Postgres transaction across rows in one table: coordinating atomicity there is cheap because it's all on one node; Elasticsearch doesn't offer (or need) the equivalent guarantee for bulk ingestion.

The Python client's `bulk()` helper defaults to raising an exception on any failure (`raise_on_error=True`); passing `raise_on_error=False` instead collects failures into a returned list so the successes aren't thrown away.

**Hands-on:** set up the Python tooling with `uv` rather than a manual `venv`:

```
uv init --bare --vcs none --no-readme --name elasticsearch-proj
uv add elasticsearch==8.15.0 python-dotenv==1.0.1
```

`--bare` keeps `uv init` to just a `pyproject.toml` (no README/sample script it would otherwise scaffold); `uv add` creates `.venv` and resolves/installs into it, recorded in [`/pyproject.toml`](/pyproject.toml) and locked in `/uv.lock`. Added [`/.gitignore`](/.gitignore) (`.venv/`, `.env`, `__pycache__/`) and [`/.env.example`](/.env.example) documenting `ES_URL=http://localhost:9200`, consistent with the project's "config explicit over defaulted" convention — the script reads the Elasticsearch URL from the environment instead of hardcoding it.

Wrote [`/scripts/generate_logs.py`](/scripts/generate_logs.py) to generate and load the dataset. Key design points:

- **Level distribution is weighted, not uniform** — `{"INFO": 70, "DEBUG": 15, "WARN": 10, "ERROR": 5}` via `random.choices(..., weights=...)`, so the dataset looks like a real service's logs (mostly routine traffic) rather than an even split across levels. This matters for session 4's aggregations, which are more meaningful against a realistic skew.
- **`status_code` is tied to `level`**, not independently random — `ERROR` only ever produces 5xx codes, `INFO`/`DEBUG` mostly 2xx, `WARN` a mix including `429`/`408`. This makes compound queries later (e.g. "`ERROR` logs with `status_code >= 500`") return something meaningful instead of arbitrary noise.
- **Timestamps are spread across the last 7 days**, randomly offset from `datetime.now(timezone.utc)`, giving `date_histogram` (session 4) an actual time range to bucket.
- **The bulk helper is a generator, not a pre-built list** — `doc_stream()` `yield`s one `{"_index": "logs-app", "_source": {...}}` dict at a time, and `elasticsearch.helpers.bulk(es, doc_stream(), raise_on_error=False)` consumes it, batching internally into the NDJSON format described above rather than requiring all 5,000 documents to be built in memory first.

Ran it:

```
uv run scripts/generate_logs.py
```
output:
```
Indexed: 5000
```

Verified the count independently via Dev Tools:

```
GET logs-app/_count
```
```json
{
  "count": 5000,
  "_shards": { "total": 1, "successful": 1, "skipped": 0, "failed": 0 }
}
```

`_count` returns just the matching document count (no query body means "match everything") — cheaper than a full `_search` when the number is all that's needed.

## Tokenization and the inverted index

**Analysis and the inverted index** — when a document is indexed, every `text` field is run through an analyzer, `standard` by default. It lowercases the value and splits it into tokens on word boundaries; it does **not** remove stopwords (`"to"`, `"a"`, `"the"`, etc.) unless a stopword filter is explicitly configured — confirmed hands-on below, where `"to"` survived analysis. Those tokens, not the original string, get written into the **inverted index** — a structure mapping each token to the list of documents (and positions within them) containing it. That's the data structure that makes full-text search fast: `match "connect"` becomes a lookup into this structure instead of a scan over every document. A `keyword` field skips this pipeline entirely — `_analyze` on one just echoes the input back as a single token, case and all.

Token **position** (its index within the analyzed sequence, starting at 0) is tracked per token, not just presence — this is what lets phrase queries confirm words are adjacent, and it's also an input to the term-frequency part of BM25 relevance scoring (session 3's deep dive). A word repeated in the source text produces multiple entries in the tokens array at different positions, not a single entry with a count — the position list itself carries that information.

**Hands-on:** now that real documents existed, compared tokenization on a `text` field vs a `keyword` field using `_analyze` (a preview endpoint — it doesn't index anything, it just shows what tokens a given string *would* produce under a field's configured analysis):

```
GET logs-app/_analyze
{ "field": "message", "text": "Failed to connect to downstream service" }
```

produced 6 tokens: `failed`, `to`, `connect`, `to`, `downstream`, `service` — lowercased, split on word boundaries, and notably `"to"` was **not** dropped despite appearing twice, confirming the `standard` analyzer doesn't remove stopwords by default. The two occurrences of `"to"` appeared as two separate entries in the `tokens` array, at `position: 1` and `position: 3` respectively — not merged into one entry with a count.

```
GET logs-app/_analyze
{ "field": "level", "text": "ERROR" }
```

produced exactly one token: `ERROR`, case preserved, `type: "word"` (versus `<ALPHANUM>` for the `message` tokens) — confirming a `keyword` field never enters the analyzer pipeline at all.

## Mapping immutability

**Why mappings are effectively immutable** — once Lucene has written a field's values into the inverted index under one analysis rule, there's no operation that goes back and re-analyzes the existing documents under a different rule. "Change `level` from `keyword` to `text`" isn't a metadata edit; it requires creating a new index with the new mapping and reindexing every document into it.

**Hands-on:** confirmed this by attempting to change an existing field's type on the live index:

```
PUT logs-app/_mapping
{
  "properties": {
    "level": { "type": "text" }
  }
}
```

rejected with:
```
"reason": "mapper [level] cannot be changed from type [keyword] to [text]"
```

Elasticsearch refused outright rather than attempting anything destructive — matching the reasoning above: the existing documents' `level` values are already stored as unanalyzed `keyword` tokens, and there's no operation that retroactively re-analyzes them under a `text` mapping.
