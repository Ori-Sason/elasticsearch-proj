# Learning Elasticsearch: log search & analytics project

## Purpose of this file

This is a session-by-session curriculum for learning Elasticsearch hands-on. It's meant to be read by Claude Code running in this project's folder, and used as the spec/context for guiding implementation, one session at a time.

**How to use this with Claude Code:** work through sessions in order. Don't skip ahead — each session's deliverable is a dependency for the next one. At the start of each session, tell Claude Code which session number you're on and paste in that section.

**Instruction to Claude Code: teach, don't just execute.** Each session follows the same four-beat pattern — theory, then hands-on, then a deeper theory pass, then more hands-on — and all four matter:

- Start with just enough background to know what's about to be built and why. Explain the concept in plain language: what it is, why it exists, what problem it solves. Don't over-explain before letting the learner touch it — this first pass should be light.
- Move into the session's hands-on tasks. When introducing a command or a piece of code, briefly say what it does and why this is the right tool for the job before running it — not just paste it and move on.
- After the hands-on work, go back into theory — deeper this time. Mechanisms, edge cases, why it actually works the way it does — now that the hands-on work gives it something to anchor to. This is the session's "Deep dive."
- Close with more hands-on that applies the deeper theory, so the session doesn't end on theory alone.
- Connect new ideas to things already covered in earlier sessions, so the mental model builds session over session instead of resetting each time.
- Prefer asking "do you know why we're doing it this way?" and letting the learner answer, over lecturing uninterrupted — check understanding as you go, not just at the end.
- It's fine for a session to feel a little slower because of this. The goal is understanding Elasticsearch, not just finishing the checklist.

## Environment

- Ubuntu VM
- Docker installed (Docker Compose will be used for Elasticsearch + Kibana)
- Python installed (used for data generation / ingestion)
- TypeScript installed (used for the final API layer)

## Introduction — what is Elasticsearch, and why use it

Before session 1 starts, Claude Code should walk through this, adapting depth to the learner's questions rather than reading it verbatim:

- What Elasticsearch actually is (a distributed search and analytics engine built on Apache Lucene) and what "distributed" and "search engine" mean concretely
- The core problem it solves: finding relevant results in large volumes of text or structured data fast, including full-text search that a traditional relational database isn't built for, plus real-time aggregation over that same data
- Where it's actually used in the industry — log and metrics analysis (the ELK/Elastic Stack), application and product search, security and observability platforms — so the learner sees why this project's "log search" theme was chosen, not just that it was
- How it compares at a high level to a relational database (documents vs rows, inverted index vs B-tree index, eventual consistency trade-offs) — enough to place it mentally, not a full deep dive
- A one-paragraph preview of where this specific project is headed, so the learner knows what the 5 sessions build toward

## The project

A small log search and analytics stack: a single-node Elasticsearch cluster holding synthetic application logs, queried first through Kibana's Dev Tools console, then through a small TypeScript API.

No Kibana dashboards, no cluster scaling, no security hardening in this version — those are good candidates for a stretch session once the fundamentals are solid, not before.

---

## Session 1 — Stand up the cluster

**Goal:** get a single-node Elasticsearch + Kibana cluster running via Docker Compose, and understand what a node, index, document, and shard actually are before touching any real data.

**Concepts to cover before the tasks:** node, cluster, index, document, shard (primary vs replica), and what Kibana is for versus Elasticsearch itself. Use a concrete analogy (e.g. index-as-database-table, document-as-row) but also explain where that analogy breaks down. Keep this pass light — just enough to make standing up the cluster make sense.

**Tasks:**
- [x] Write a `docker-compose.yaml` for a single-node Elasticsearch cluster + Kibana (security/auth can stay disabled for local dev — note this explicitly as a dev-only choice, not a default)
- [x] Start it and confirm cluster health is green via `curl` (`GET _cluster/health`)
- [x] Create one index by hand and inspect it in Kibana
- [x] Be able to explain, in your own words: node vs index vs shard vs document, and why a single-node dev cluster still has shards

**Deep dive:** now that a real index exists, go deeper on shards — what a shard actually is (a self-contained Lucene index), why data gets split into shards at all (parallelism, scaling beyond one node's disk/memory), what a replica actually protects against and why a single-node cluster can't allocate any (no second node to put it on), and what the cluster health colors (green/yellow/red) really mean underneath. This should set up why adding a second node later would immediately change shard allocation.

- [x] Closing hands-on: inspect shard allocation via `GET _cat/shards`, then create a second index that requests one replica and observe the cluster turn yellow — explain why, using what you just learned

**Deliverable:** a running cluster you can hit at `localhost:9200`, and a Kibana instance you can reach in the browser.

---

## Session 2 — Model and load data

**Goal:** define an explicit mapping for a log document (no relying on Elasticsearch's dynamic mapping), then write a Python script that generates and bulk-loads a realistic synthetic log dataset.

**Concepts to cover before the tasks:** what a mapping is and why it matters (it's not just "schema" — briefly note that analyzers make `text` vs `keyword` behave differently, without going deep yet), what dynamic mapping does automatically and why relying on it is risky, and what the bulk API is for and why it's faster than indexing documents one at a time. Keep this pass light — the analyzer mechanics get their own pass after the hands-on work.

**Tasks:**
- [ ] Design a log document schema: `timestamp`, `level`, `service`, `message`, `status_code` (add fields if useful, but keep it small)
- [ ] Create the index with an explicit mapping (correct field types — `date`, `keyword` vs `text`, `integer` — chosen deliberately, not left to dynamic mapping)
- [ ] Write a Python script generating ~5,000 synthetic log lines across a handful of fake services, log levels, and status codes
- [ ] Bulk-index them using the Python Elasticsearch client's bulk helper, and verify the doc count matches what you generated

**Deep dive:** now that real documents exist, go deeper on what actually happens to them at index time — tokenization and the standard analyzer (lowercasing, splitting on word boundaries, stopword handling if enabled), why `keyword` fields skip analysis entirely and get stored as a single exact token, and why mappings are effectively immutable once a field is written (changing a field's type means reindexing into a new index, not an in-place update — this sets up why the schema decisions made above matter). Also unpack the bulk API's NDJSON request format and what happens on a partial failure mid-batch.

- [ ] Closing hands-on: run `GET <index>/_analyze` against the `message` field and against a `keyword` field to see the actual tokens each produces, then deliberately try to change a mapped field's type on the existing index and observe the error, to feel the immutability constraint firsthand

**Deliverable:** an index with ~5,000 real documents in it, mapped explicitly, generated by a script you can re-run.

---

## Session 3 — Search fundamentals

**Goal:** learn the Query DSL by running real searches against your own log data — full-text match, exact-value filtering, and combining conditions with `bool`.

**Concepts to cover before the tasks:** what a query is at a basic level (a JSON request describing what you're looking for) and the high-level difference between matching on free text (`match`) versus an exact value (`term`) — just enough to run the first queries. The scoring mechanics come in the deep dive, once there are real query results to look at.

**Tasks:**
- [ ] Run a `match` query against the `message` field
- [ ] Run a `term` query filtering on an exact field like `level` (understand why this needs a `keyword` field, not `text`)
- [ ] Combine both in a `bool` query using `must` and `filter` — and be able to explain the difference between them (scoring vs no scoring)
- [ ] Add sorting and pagination (`from`/`size`, or `search_after` for larger result sets)

**Deep dive:** now that there are real scored results on screen, go deeper on how that score was actually computed — the inverted index as the data structure making full-text search fast, and relevance scoring via BM25 (term frequency, inverse document frequency, field-length normalization, in plain terms). Then unpack query context vs filter context properly: why a filter can be cached as a bitset and skip scoring entirely, why that makes `filter` faster than an equivalent `must`, and when you'd deliberately still want `must` for its scoring even when filtering would work.

- [ ] Closing hands-on: run the same query through `GET <index>/_explain/<doc_id>` (or the `explain` search parameter) to see the actual BM25 score breakdown for one result, and rewrite one `must` clause as `filter` to confirm the result set doesn't change but the score does

**Deliverable:** a handful of saved queries (in Kibana Dev Tools or a `.http`/`.md` scratch file) covering match, term, bool, sort, and pagination against the session 2 dataset.

---

## Session 4 — Aggregations

**Goal:** move from finding documents to summarizing them — build the kind of aggregations that power a real log dashboard.

**Concepts to cover before the tasks:** the distinction between bucket aggregations (grouping) and metric aggregations (computing a number over a group) — just enough to build the first ones. How aggregations actually execute, and where they can go approximate at scale, is the deep dive's job once there are real results to question.

**Tasks:**
- [ ] Build a `terms` aggregation for the top error-producing services
- [ ] Build a `date_histogram` aggregation for request volume over time
- [ ] Nest a metric aggregation (`avg` or `percentiles`) inside a bucket aggregation
- [ ] Sanity-check one aggregation result by manually counting/filtering the same thing a different way, to confirm you trust the result

**Deep dive:** now that real aggregation results exist, go deeper on how they run — over `doc_values` (a columnar, on-disk data structure built at index time specifically to make aggregations fast, distinct from the inverted index used for search), and why that's how aggregations execute over the same data structures used for search rather than needing a separate analytics system. Then unpack why a `terms` aggregation over a sharded index can be approximate — `shard_size`, `doc_count_error_upper_bound`, and what's actually happening when each shard only returns its own top N terms before they're merged.

- [ ] Closing hands-on: rerun the `terms` aggregation from the tasks with a deliberately small `size`/`shard_size`, inspect the resulting `doc_count_error_upper_bound`, and explain in your own words what that number represents

**Deliverable:** 3–4 aggregation queries that could plausibly back a real log-monitoring dashboard.

---

## Session 5 — Ship a TypeScript API

**Goal:** wrap what you've built in a small TypeScript service, so Elasticsearch becomes something you call from code, not just from Kibana's console.

**Concepts to cover before the tasks:** what the official client libraries add on top of raw HTTP calls to Elasticsearch (request building, connection handling) — enough to get the client set up. Retries and error-handling behavior get the deeper pass once there's a running endpoint to actually break.

**Tasks:**
- [ ] Set up a minimal TypeScript project using the `@elastic/elasticsearch` client
- [ ] Build a `/search` endpoint wrapping the session 3 queries (accepting basic query params — text, level, date range)
- [ ] Build a `/stats` endpoint wrapping the session 4 aggregations
- [ ] Add a `.env.example` documenting the Elasticsearch connection config (host, port, any auth), consistent with keeping config explicit rather than hardcoded

**Deep dive:** now that the endpoints exist, go deeper on what the client is actually doing on every request — connection pooling, its default retry/backoff behavior on a transient failure, and how it surfaces Elasticsearch-side errors (e.g. a mapping error, a missing index) versus a network-level failure, so the API can eventually tell those apart instead of returning a generic 500 for everything. Also revisit how the query/aggregation JSON from sessions 3 and 4 maps directly onto the client's request objects — this should feel like translation, not new material.

- [ ] Closing hands-on: add basic error handling to both endpoints that distinguishes an Elasticsearch error (e.g. bad query params) from a connection failure, and returns a sensible status code for each

**Deliverable:** a running local API with two endpoints, backed by the cluster from session 1 and the data from session 2.

---

## Stretch (optional, after session 5)

Once the fundamentals above are solid, good next directions: index lifecycle management, snapshots/restore, reindexing after a mapping change, and basic security (enabling auth, API keys) — this last one ties naturally into the IAM/secrets work already done in the DevOps final project.

---

## Optional session — Postgres's built-in full-text search

**Goal:** get hands-on with Postgres's own full-text search (`tsvector`/`tsquery`, GIN indexes) and `pg_trgm` for fuzzy/substring matching, to answer a practical question: what can you actually get out of Postgres alone, without standing up a separate Elasticsearch service, and where does that stop being enough — so the choice to add Elasticsearch to a project (or not) is a real trade-off decision, not a default.

This is a side project, not a continuation of the main one — it doesn't feed into session 5's deliverable, but it deliberately runs the same kind of query against the same log data so the comparison is concrete rather than theoretical.

**Concepts to cover before the tasks:** what `tsvector` and `tsquery` are (Postgres's own text-search types), how a GIN index over a `tsvector` column is Postgres's version of an inverted index, and what `pg_trgm` adds (trigram-based fuzzy/substring matching) — just enough to run the first comparison queries. Where Postgres's approach actually stops scaling like Elasticsearch's is the deep dive's job, once there are real results from both systems to compare.

**Tasks:**
- [ ] Add a `tsvector` column (or a generated column) to a Postgres table holding the same log data used in Session 2
- [ ] Create a GIN index on it and run a `tsquery` search, comparing syntax and results to the Elasticsearch `match` query from Session 3
- [ ] Install `pg_trgm` and run a substring/fuzzy search, comparing to Elasticsearch's `wildcard`/`fuzzy` queries from the same session

**Deep dive:** now that both systems have answered the same queries, go deeper on where they actually diverge and why: `ts_rank`'s ranking model versus BM25 (simpler, no field-length normalization by default), that Postgres FTS runs on a single node with no built-in equivalent of Elasticsearch's distributed aggregation framework (a `GROUP BY` can approximate a bucket aggregation, but there's no native nested bucket/metric pattern), and the operational cost on the other side of the trade-off — running and maintaining a second stateful system versus staying inside a database you're already operating. Land this on a concrete decision framework: at what point (data volume, query complexity, need for real aggregations, need for horizontal scaling) does that operational cost start being worth paying.

- [ ] Closing hands-on: write a short comparison note answering, for this project's actual dataset and query patterns, whether a standalone Elasticsearch would be worth deploying or whether Postgres FTS would have been enough — and why

**Deliverable:** a short written comparison of Postgres full-text search vs Elasticsearch, backed by hands-on queries against the same dataset, that lands on an actual recommendation for when each is the right call.
