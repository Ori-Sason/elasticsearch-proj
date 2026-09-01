# Learning Elasticsearch: log search & analytics project

## Purpose of this file

This is a session-by-session curriculum for learning Elasticsearch hands-on. It's meant to be read by Claude Code running in this project's folder, and used as the spec/context for guiding implementation, one session at a time.

**How to use this with Claude Code:** work through sessions in order. Don't skip ahead — each session's deliverable is a dependency for the next one. At the start of each session, tell Claude Code which session number you're on and paste in that section.

**Instruction to Claude Code: teach, don't just execute.** Each session has two parts — concepts and practice — and both matter. Before writing any code or running any command:

- Explain the relevant concept first, in plain language: what it is, why it exists, and what problem it solves. Don't skip straight to syntax.
- Connect new ideas to things already covered in earlier sessions, so the mental model builds session over session instead of resetting each time.
- When introducing a command or a piece of code, briefly say what it does and why this is the right tool for the job before running it — not just paste it and move on.
- Prefer asking "do you know why we're doing it this way?" and letting the learner answer, over lecturing uninterrupted — check understanding as you go, not just at the end.
- It's fine for a session to feel a little slower because of this. The goal is understanding Elasticsearch, not just finishing the checklist.

## Introduction — what is Elasticsearch, and why use it

Before session 1 starts, Claude Code should walk through this, adapting depth to the learner's questions rather than reading it verbatim:

- What Elasticsearch actually is (a distributed search and analytics engine built on Apache Lucene) and what "distributed" and "search engine" mean concretely
- The core problem it solves: finding relevant results in large volumes of text or structured data fast, including full-text search that a traditional relational database isn't built for, plus real-time aggregation over that same data
- Where it's actually used in the industry — log and metrics analysis (the ELK/Elastic Stack), application and product search, security and observability platforms — so the learner sees why this project's "log search" theme was chosen, not just that it was
- How it compares at a high level to a relational database (documents vs rows, inverted index vs B-tree index, eventual consistency trade-offs) — enough to place it mentally, not a full deep dive
- A one-paragraph preview of where this specific project is headed, so the learner knows what the 5 sessions build toward

## Environment

- Ubuntu VM
- Docker installed (Docker Compose will be used for Elasticsearch + Kibana)
- Python installed (used for data generation / ingestion)
- TypeScript installed (used for the final API layer)

## The project

A small log search and analytics stack: a single-node Elasticsearch cluster holding synthetic application logs, queried first through Kibana's Dev Tools console, then through a small TypeScript API.

No Kibana dashboards, no cluster scaling, no security hardening in this version — those are good candidates for a stretch session once the fundamentals are solid, not before.

---

## Session 1 — Stand up the cluster

**Goal:** get a single-node Elasticsearch + Kibana cluster running via Docker Compose, and understand what a node, index, document, and shard actually are before touching any real data.

**Concepts to cover before the tasks:** node, cluster, index, document, shard (primary vs replica), and what Kibana is for versus Elasticsearch itself. Use a concrete analogy (e.g. index-as-database-table, document-as-row) but also explain where that analogy breaks down.

**Tasks:**
- [x] Write a `docker-compose.yaml` for a single-node Elasticsearch cluster + Kibana (security/auth can stay disabled for local dev — note this explicitly as a dev-only choice, not a default)
- [x] Start it and confirm cluster health is green via `curl` (`GET _cluster/health`)
- [x] Create one index by hand and inspect it in Kibana
- [x] Be able to explain, in your own words: node vs index vs shard vs document, and why a single-node dev cluster still has shards

**Deliverable:** a running cluster you can hit at `localhost:9200`, and a Kibana instance you can reach in the browser.

---

## Session 2 — Model and load data

**Goal:** define an explicit mapping for a log document (no relying on Elasticsearch's dynamic mapping), then write a Python script that generates and bulk-loads a realistic synthetic log dataset.

**Concepts to cover before the tasks:** what a mapping is and why it matters (it's not just "schema" — explain analyzers and why `text` vs `keyword` produces different search behavior, not just different storage), what dynamic mapping does automatically and why relying on it is risky, and what the bulk API is for and why it's faster than indexing documents one at a time.

**Tasks:**
- [ ] Design a log document schema: `timestamp`, `level`, `service`, `message`, `status_code` (add fields if useful, but keep it small)
- [ ] Create the index with an explicit mapping (correct field types — `date`, `keyword` vs `text`, `integer` — chosen deliberately, not left to dynamic mapping)
- [ ] Write a Python script generating ~5,000 synthetic log lines across a handful of fake services, log levels, and status codes
- [ ] Bulk-index them using the Python Elasticsearch client's bulk helper, and verify the doc count matches what you generated

**Deliverable:** an index with ~5,000 real documents in it, mapped explicitly, generated by a script you can re-run.

---

## Session 3 — Search fundamentals

**Goal:** learn the Query DSL by running real searches against your own log data — full-text match, exact-value filtering, and combining conditions with `bool`.

**Concepts to cover before the tasks:** how full-text search actually works under the hood (the inverted index, tokenization, relevance scoring via TF-IDF/BM25) at a level that explains why `match` behaves the way it does, and the conceptual difference between a query (affects relevance score) and a filter (yes/no, cached, no scoring) — this is the "why" behind `must` vs `filter` in `bool`.

**Tasks:**
- [ ] Run a `match` query against the `message` field
- [ ] Run a `term` query filtering on an exact field like `level` (understand why this needs a `keyword` field, not `text`)
- [ ] Combine both in a `bool` query using `must` and `filter` — and be able to explain the difference between them (scoring vs no scoring)
- [ ] Add sorting and pagination (`from`/`size`, or `search_after` for larger result sets)

**Deliverable:** a handful of saved queries (in Kibana Dev Tools or a `.http`/`.md` scratch file) covering match, term, bool, sort, and pagination against the session 2 dataset.

---

## Session 4 — Aggregations

**Goal:** move from finding documents to summarizing them — build the kind of aggregations that power a real log dashboard.

**Concepts to cover before the tasks:** the distinction between bucket aggregations (grouping) and metric aggregations (computing a number over a group), how aggregations execute over the same data structures used for search rather than requiring a separate analytics system, and why nesting a metric inside a bucket is the pattern behind most real-world dashboards.

**Tasks:**
- [ ] Build a `terms` aggregation for the top error-producing services
- [ ] Build a `date_histogram` aggregation for request volume over time
- [ ] Nest a metric aggregation (`avg` or `percentiles`) inside a bucket aggregation
- [ ] Sanity-check one aggregation result by manually counting/filtering the same thing a different way, to confirm you trust the result

**Deliverable:** 3–4 aggregation queries that could plausibly back a real log-monitoring dashboard.

---

## Session 5 — Ship a TypeScript API

**Goal:** wrap what you've built in a small TypeScript service, so Elasticsearch becomes something you call from code, not just from Kibana's console.

**Concepts to cover before the tasks:** what the official client libraries add on top of raw HTTP calls to Elasticsearch (request building, retries, connection pooling), and how the query/aggregation JSON from sessions 3 and 4 maps directly onto the client's request objects — this should feel like translation, not new material.

**Tasks:**
- [ ] Set up a minimal TypeScript project using the `@elastic/elasticsearch` client
- [ ] Build a `/search` endpoint wrapping the session 3 queries (accepting basic query params — text, level, date range)
- [ ] Build a `/stats` endpoint wrapping the session 4 aggregations
- [ ] Add a `.env.example` documenting the Elasticsearch connection config (host, port, any auth), consistent with keeping config explicit rather than hardcoded

**Deliverable:** a running local API with two endpoints, backed by the cluster from session 1 and the data from session 2.

---

## Stretch (optional, after session 5)

Once the fundamentals above are solid, good next directions: index lifecycle management, snapshots/restore, reindexing after a mapping change, and basic security (enabling auth, API keys) — this last one ties naturally into the IAM/secrets work already done in the DevOps final project.

---

## Optional session — Postgres's built-in full-text search

**Goal:** get hands-on with Postgres's own full-text search (`tsvector`/`tsquery`, GIN indexes) and `pg_trgm` for fuzzy/substring matching, so you can compare it directly against Elasticsearch and know when each is the right tool — not just in theory, but by running the same kind of query against the same data in both.

**Concepts to cover before the tasks:** what `tsvector` and `tsquery` are (Postgres's own text-search types), how a GIN index over a `tsvector` column is Postgres's version of an inverted index, what `pg_trgm` adds (trigram-based fuzzy/substring matching) and how that compares to Elasticsearch's n-gram analyzers and `fuzzy`/`wildcard` queries, and — the main point of this session — where Postgres FTS is genuinely enough and where Elasticsearch's distributed model and aggregation framework actually earn their extra complexity.

**Tasks:**
- [ ] Add a `tsvector` column (or a generated column) to a Postgres table holding the same log data used in Session 2
- [ ] Create a GIN index on it and run a `tsquery` search, comparing syntax and results to the Elasticsearch `match` query from Session 3
- [ ] Install `pg_trgm` and run a substring/fuzzy search, comparing to Elasticsearch's `wildcard`/`fuzzy` queries from the same session
- [ ] Write a short comparison note: query syntax, relevance ranking, and scaling differences between Postgres FTS and Elasticsearch

**Deliverable:** a short written comparison (a few bullet points) of Postgres full-text search vs Elasticsearch, backed by hands-on queries against the same dataset.
