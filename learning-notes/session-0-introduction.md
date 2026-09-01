# Session 0 — Introduction notes

Summary of the intro walkthrough before Session 1, plus the Q&A that followed. Kept as a reference to come back to.

## What Elasticsearch is, and why it exists

- **The problem:** relational databases index for exact lookups and range scans (B-trees) — fast for `WHERE id = 5`, but `WHERE message LIKE '%timeout%'` usually means a full scan, with no concept of relevance ranking.
- **Elasticsearch** is a distributed search and analytics engine built on Apache Lucene. It solves the above by building an **inverted index** at write time — for every unique word, a list of which documents contain it — so a text search becomes a fast lookup instead of a scan.
- **Distributed** means data and query load are spread across multiple nodes so it scales by adding machines. We're running a single-node cluster in this project, but the concepts (shards, replicas) still apply even at one node — that's covered in Session 1.
- **Industry use:** the ELK stack (Elasticsearch, Logstash, Kibana) is a standard way to centralize logs from many services into one searchable place — the theme of this project. Also widely used for app/product search and security/observability (SIEM) platforms.

### vs. a relational database

| Relational DB | Elasticsearch |
|---|---|
| Rows in tables | Documents (JSON) in indices |
| B-tree index (exact/range lookups) | Inverted index (text search) |
| Strong consistency, transactions | Eventually consistent, no cross-document transactions |
| Joins are first-class | No real joins — data is usually denormalized |

Elasticsearch is not a replacement for a primary database — it's normally a secondary store optimized for search/analytics, fed from a source of truth.

### Where this project is headed

Stand up a real Elasticsearch + Kibana cluster in Docker → model and load ~5,000 synthetic log lines with an explicit schema → learn the Query DSL to search that data → build the aggregations that power a log dashboard → wrap it all in a small TypeScript API.

---

## Q&A

**1. Do other tools have search built in (e.g. Postgres)?**

Yes. Postgres has `tsvector`/`tsquery` + a GIN index (itself a kind of inverted index), plus the `pg_trgm` extension for fuzzy/substring matching. MySQL has `FULLTEXT`, SQLite has `FTS5`, MongoDB Atlas Search is Lucene-based. Dedicated products like Algolia/Meilisearch also exist, more focused on instant-search UX than log analytics.

Elasticsearch's edge is scale (distributed across many nodes) and its aggregation framework, which goes well beyond what's practical to hand-roll in SQL for things like "error rate by service over time." *(A hands-on comparison with Postgres FTS specifically is now its own optional session at the end of the curriculum.)*

**2. Is there an AWS service for this?**

**Amazon OpenSearch Service.** Backstory: OpenSearch is a fork of Elasticsearch — in 2021 Elastic changed Elasticsearch's license in a way AWS didn't like for its managed offering, so AWS forked the last open-source version and has maintained OpenSearch independently since. APIs are still very similar. There's also Amazon Kendra (a different, ML/NLP-driven enterprise search product) and the older CloudSearch.

**3. Do I need to store my data in two places (a normal DB and Elasticsearch)?**

Generally yes. Elasticsearch is almost always a secondary store, not the system of record: the primary database (Postgres, etc.) holds the authoritative data, and a copy is synced into Elasticsearch (dual writes, a queue, or CDC off the DB's write-ahead log) purely to make it fast to search/aggregate. This is because Elasticsearch trades away things a primary store needs — no real cross-document transactions, no joins, and only eventual consistency (a just-indexed document may not be searchable for up to ~1 second, the "refresh interval").

Logs are one of the few cases where Elasticsearch is often treated as close to primary, since log data is append-only and doesn't need transactional guarantees. In this project there's no separate primary DB — synthetic logs are generated directly into Elasticsearch.

**4. Can I search part of a word, like SQL's `LIKE '%art%'`?**

Yes, via a few different mechanisms with different performance characteristics:

- `wildcard` query — closest to `LIKE '%art%'`, scans terms for a pattern; can be slow, same caveat as a leading-`%` `LIKE`.
- `fuzzy` query — matches words *close* to the term (typo-tolerant, edit-distance based), not substrings.
- N-gram / edge-n-gram analyzers — the idiomatic Elasticsearch way to do partial/prefix matching (e.g. autocomplete). The field's *analyzer* breaks a word into overlapping fragments at index time (n-grams: `"tim","ime","meo",...`; edge-n-grams: `"t","ti","tim",...`), so a partial match becomes a normal fast inverted-index lookup instead of a scan.

This is a preview of Session 2: the analyzer chosen in a field's mapping determines what kind of matching is even possible later — another reason mappings are explicit in this project, not left to dynamic mapping.

**5. Since data is tokenized into words, is the query also tokenized? So can I search "summer is hot" and it finds records with "summer" and "hot" separately?**

Yes — that symmetry is the key idea. When a document is indexed, the field's *analyzer* tokenizes the text (splits into words, lowercases, may drop stopwords/stem) before it goes into the inverted index; the original string isn't what's stored there. When you run a `match` query, Elasticsearch runs your query text through *the same analyzer*. So `match: "summer is hot"` gets tokenized into something like `[summer, hot]` too (with "is" likely dropped as a stopword), and it looks up each token separately.

By default this is effectively OR: a document matches if it contains *any* of the tokens, then results are ranked by relevance (BM25) — so a document containing both "summer" and "hot" scores higher than one containing only "hot," and a rarer matching word counts for more than a common one. A few knobs change that default: `match` with `"operator": "and"` requires all tokens present (still not phrase order); `match_phrase` requires the exact adjacent sequence; `minimum_should_match` requires some number/percentage of tokens, a middle ground between OR and AND.

This is also why the `text` vs `keyword` distinction from Session 2 matters: a `text` field goes through this analyze-and-tokenize pipeline (so "hot" matches "It's hot today"), while a `keyword` field is indexed as one exact, unanalyzed string, so a `match` query for "hot" against a `keyword` field storing `"It's hot today"` would *not* match — no tokenization happens at all, just an exact-string compare. That's the mechanism behind why a `term` query needs a `keyword` field, coming up in Session 3.
