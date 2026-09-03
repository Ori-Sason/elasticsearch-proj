# Session 2 — Model and load data

## TL;DR

Designed an explicit mapping for a log document (`timestamp`/`date`, `level`/`keyword`, `service`/`keyword`, `message`/`text`, `status_code`/`integer`), created the `logs-app` index with it, then wrote a Python script that generates 5,000 realistic synthetic logs and bulk-indexes them. Inspected the actual tokens a `text` field vs. a `keyword` field produce via `_analyze`, and confirmed mapping immutability by trying — and failing — to change a mapped field's type on the live index.

## Architecture: mapping decides the pipeline a field goes through

```
PUT logs-app with mapping   (locked in before a single doc exists)
        │
        ▼
document arrives via bulk API (NDJSON, 2 lines per doc)
        │
        ▼
   per field, by mapping type:
   ┌─────────────────────────┬──────────────────────────┐
   │ text field (message)    │ keyword field (level)    │
   │  → standard analyzer    │  → stored exactly as-is  │
   │  lowercase + split      │  one atomic token,       │
   │  into tokens            │  case preserved          │
   └───────────┬─────────────┴────────────┬─────────────┘
               ▼                          ▼
        inverted index               inverted index
    token → doc list + position    exact value → doc list
```

The mapping decision made once, up front, determines which path every future document's fields take — that's why getting it right before real data lands matters more here than in a typical SQL migration.

## Walkthrough

### Mapping and index design

**Mapping** is Elasticsearch's equivalent of a schema — field names and types, defined explicitly rather than left to inference. It does more than a SQL schema, though: for string fields it also determines how the value gets processed before it becomes searchable. That processing is called analysis, covered in its own section below.

`keyword` and `text` both hold JSON strings, but they behave completely differently. Think of `keyword` like a barcode — stored exactly as given, one atomic token, case preserved, nothing split apart, scanned only as a whole. Think of `text` like a paragraph in a book — broken into words at index time so any word inside it can be searched, not just the paragraph as a whole.

| | `keyword` | `text` |
|---|---|---|
| Processed at index time | No — stored as-is | Yes — run through an analyzer |
| Matches on | The whole value, byte-for-byte | Individual tokens |
| Good for | Exact filters, aggregations, sorting | Full-text search |

A `keyword` field behaves like a dropdown value once stored, but Elasticsearch itself doesn't enforce that — nothing stops a document from writing `level: "WHOOPS"`, since no unique list of allowed values is defined anywhere.

The type decision follows from how a field will actually be queried, not from what kind of value it happens to be. `status_code` is a number, so `integer` looks obvious — but the real reason is that the project needs range queries (`status_code >= 500` to isolate error-class responses) and, later, numeric aggregations (`avg`, histograms) over it. Only a numeric type supports those. If the only planned use were exact-match filtering and counting distinct codes, `keyword` would technically work too.

Relying on dynamic mapping is risky. By default, an index with no mapping yet infers each field's type from whatever document arrives first — a JSON string becomes `text` (with an auto-generated `keyword` sub-field), a number becomes `long`/`double`, an ISO-looking string becomes `date`. The guess is only as good as that first document, and mistakes are expensive to fix, since a field's type is effectively locked in once real documents exist under it — the full reasoning is in [Mapping immutability](#mapping-immutability) below. This project mapped explicitly instead.

**Hands-on:** created the `logs-app` index with an explicit mapping via Kibana Dev Tools:

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

Returned `"acknowledged": true`, `"shards_acknowledged": true` — the index exists with these five fields locked to these types before a single document was written. As with `test-logs` in session 1, it picked up the default `number_of_replicas: 1`, which the single-node cluster can't place, so the cluster went yellow again — same allocator behavior covered in [session 1](/learning-notes/session-1-cluster-fundamentals.md).

**Bottom line:** a mapping decision here is a one-way door. Get the type wrong and the fix isn't an `ALTER TABLE`, it's a new index and a full reindex — worth the extra minute of thinking before `PUT`.

### Generating and bulk-loading data

Indexing documents one at a time means one HTTP round trip per document. The bulk API batches many index operations into a single request instead — like mailing a box of letters in one trip to the post office instead of driving out for each one individually.

Its wire format is newline-delimited JSON (NDJSON), not a JSON array. Each document becomes two lines — an action/metadata line and a source line (see [generate_logs.py#bulk method](/scripts/generate_logs.py)):

```
{"index":{"_index":"logs-app"}}
{"timestamp":"...","level":"ERROR","service":"billing","message":"...","status_code":500}
```

This lets Elasticsearch stream and parse line-by-line instead of buffering and parsing one large JSON array in memory.

A partial bulk failure doesn't abort the whole batch. The bulk API processes every line independently and returns a per-item result array — a bad document among 5,000 shows up as one failed item, the other 4,999 still succeed. It's less like a single database transaction and more like a warehouse shipping each item in a cart separately: one out-of-stock item doesn't cancel the rest of the order.

This isn't just convenience, it follows from how documents route to shards. Each document's target shard is `hash(_id) % number_of_primary_shards`, so the documents in one bulk request are typically scattered across many shards. Making the whole batch atomic would require a distributed transaction coordinated across every shard involved — real coordination cost, for a system whose whole design point is high-throughput ingestion, where an individual document failing is expected and recoverable, not exceptional. Contrast with a single-node Postgres transaction across rows in one table: coordinating atomicity there is cheap because it's all on one node. Elasticsearch doesn't offer, or need, the equivalent guarantee for bulk ingestion.

The Python client's `bulk()` helper defaults to raising an exception on any failure (`raise_on_error=True`). Passing `raise_on_error=False` instead collects failures into a returned list so the successes aren't thrown away.

**Hands-on:** set up the Python tooling with `uv` rather than a manual `venv`:

```
uv init --bare --vcs none --no-readme --name elasticsearch-proj
uv add elasticsearch==8.15.0 python-dotenv==1.0.1
```

`--bare` keeps `uv init` to just a `pyproject.toml` — no README or sample script it would otherwise scaffold. `uv add` creates `.venv` and resolves/installs into it, recorded in [`/pyproject.toml`](/pyproject.toml) and locked in `/uv.lock`. Added [`/.gitignore`](/.gitignore) (`.venv/`, `.env`, `__pycache__/`) and [`/.env.example`](/.env.example) documenting `ES_URL=http://localhost:9200`, consistent with the project's "config explicit over defaulted" convention — the script reads the Elasticsearch URL from the environment instead of hardcoding it.

Wrote [`/scripts/generate_logs.py`](/scripts/generate_logs.py) to generate and load the dataset. Key design points:

- **Level distribution is weighted, not uniform** — `{"INFO": 70, "DEBUG": 15, "WARN": 10, "ERROR": 5}` via `random.choices(..., weights=...)`, so the dataset looks like a real service's logs (mostly routine traffic) rather than an even split across levels. This matters for session 4's aggregations, which are more meaningful against a realistic skew.
- **`status_code` is tied to `level`**, not independently random — `ERROR` only ever produces 5xx codes, `INFO`/`DEBUG` mostly 2xx, `WARN` a mix including `429`/`408`. This makes compound queries later, like "`ERROR` logs with `status_code >= 500`," return something meaningful instead of arbitrary noise.
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

`_count` returns just the matching document count — no query body means "match everything" — cheaper than a full `_search` when the number is all that's needed.

**Bottom line:** bulk ingestion trades all-or-nothing safety for throughput and resilience. That trade-off is deliberate, not a missing feature — high-volume log ingestion needs "keep going past one bad document" far more than it needs transactional atomicity.

### Tokenization and the inverted index

When a document is indexed, every `text` field is run through an analyzer — `standard` by default. It lowercases the value and splits it into tokens on word boundaries. It does **not** remove stopwords (`"to"`, `"a"`, `"the"`, etc.) unless a stopword filter is explicitly configured, confirmed hands-on below.

Those tokens, not the original string, get written into the **inverted index** — a structure mapping each token to the list of documents, and positions within them, containing it. Think of it like a book's index in the back: instead of scanning every page for a word, you jump straight to the pages listed. That's the data structure that makes full-text search fast — `match "connect"` becomes a lookup into this structure instead of a scan over every document. A `keyword` field skips this pipeline entirely: `_analyze` on one just echoes the input back as a single token, case and all.

Token **position** — its index within the analyzed sequence, starting at 0 — is tracked per token, not just presence. This is what lets phrase queries confirm words are adjacent, and it's also an input to the term-frequency part of BM25 relevance scoring, covered in [session 3](/learning-notes/session-3-search-fundamentals.md)'s deep dive. A word repeated in the source text produces multiple entries in the tokens array at different positions, not a single entry with a count — the position list itself carries that information.

**Hands-on:** compared tokenization on a `text` field vs. a `keyword` field using `_analyze` — a preview endpoint that doesn't index anything, it just shows what tokens a given string *would* produce under a field's configured analysis:

```
GET logs-app/_analyze
{ "field": "message", "text": "Failed to connect to downstream service" }
```

Produced 6 tokens: `failed`, `to`, `connect`, `to`, `downstream`, `service` — lowercased, split on word boundaries. `"to"` was **not** dropped despite appearing twice, confirming the `standard` analyzer doesn't remove stopwords by default. The two occurrences of `"to"` appeared as two separate entries in the `tokens` array, at `position: 1` and `position: 3` respectively — not merged into one entry with a count.

```
GET logs-app/_analyze
{ "field": "level", "text": "ERROR" }
```

Produced exactly one token: `ERROR`, case preserved, `type: "word"` — versus `<ALPHANUM>` for the `message` tokens — confirming a `keyword` field never enters the analyzer pipeline at all.

**Bottom line:** a `text` field's token count and positions are a direct product of the analyzer, not the raw string — two occurrences of the same word are two tracked positions, which is exactly the kind of detail BM25 leans on later.

### Mapping immutability

Once Lucene has written a field's values into the inverted index under one analysis rule, there's no operation that goes back and re-analyzes the existing documents under a different rule. It's less like editing a spreadsheet column and more like concrete that's already been poured — reshaping it means demolishing and repouring, not touching up. "Change `level` from `keyword` to `text`" isn't a metadata edit, it requires creating a new index with the new mapping and reindexing every document into it.

**Hands-on:** confirmed this by attempting to change an existing field's type on the live index:

```
PUT logs-app/_mapping
{
  "properties": {
    "level": { "type": "text" }
  }
}
```

Rejected with:

```
"reason": "mapper [level] cannot be changed from type [keyword] to [text]"
```

Elasticsearch refused outright rather than attempting anything destructive — matching the reasoning above. The existing documents' `level` values are already stored as unanalyzed `keyword` tokens, and there's no operation that retroactively re-analyzes them under a `text` mapping.

**Bottom line:** the only path to a different field type on data that already exists is a new index plus a full reindex, never an in-place edit — mapping decisions carry that weight from the moment the first real document lands.

## Questions I Had

**If Elasticsearch doesn't enforce a fixed set of values on a `keyword` field, what actually stops garbage like `level: "WHOOPS"` from being written?**
Nothing at the mapping level. `keyword` behaves like a dropdown once data is well-behaved, but Elasticsearch doesn't validate against an allowed-values list unless one is added separately, such as with an `enum`-style application check before indexing.

**Why not just rely on dynamic mapping and let Elasticsearch guess each field's type from the first document?**
Because the guess is only as good as that first document, and a wrong guess is expensive to fix — a field's type locks in once real documents exist under it, and the only fix is a new index plus a full reindex. Explicit mapping avoids betting the schema on whichever document happens to arrive first.

**Why doesn't one bad document in a 5,000-document bulk request abort the whole batch?**
Because the bulk API processes every line independently, and documents in one batch are typically scattered across many shards by `hash(_id) % number_of_primary_shards`. Making the batch atomic would need a distributed transaction across every shard involved — real coordination cost for a system whose whole point is high-throughput ingestion, where one bad document is expected and recoverable, not exceptional.

**Why did the repeated word `"to"` show up as two separate entries in the `_analyze` output instead of one entry with a count of 2?**
Because the inverted index tracks token position, not just presence or frequency as a single number. Each occurrence of a token gets its own position — `1` and `3` for the two `"to"`s here — which is what lets phrase queries confirm adjacency and feeds the term-frequency component of BM25 scoring later.
