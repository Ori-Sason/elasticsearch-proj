# Session 6 — Add a database of record

## TL;DR

SQLite becomes the system of record for logs, and Elasticsearch turns into a derived, search-tuned copy kept in sync via an explicit reindex script.

The session 5 TypeScript API gets a write path (`POST /logs`) that writes to SQLite first, then to ES, demonstrating the dual-write pattern and its exact failure mode — including a hands-on drill that breaks it on purpose and recovers from it.

A follow-on discussion covers why a full index rebuild doesn't scale, and what production systems do instead.

## Architecture

Same shape as an app DB in front of a Redis cache, with ES playing Redis's role:

```
   writes                          writes
     │                                │
     ▼                                ▼
┌─────────┐   backfill/sync    ┌──────────────┐
│ SQLite  │ ─────────────────► │  logs-app    │
│(source  │                    │  (derived,   │
│of truth)│                    │ search-tuned)│
└─────────┘                    └──────────────┘
```

One source of truth, one derived copy tuned for a different access pattern.

The analogy breaks in one important place: Redis self-heals.

A Redis cache miss falls back to the DB and silently repopulates itself; TTLs expire entries automatically.

ES has no such fallback — it doesn't expire or evict its own data, and there's no "cache miss → refetch" path built into a search request.

If SQLite and ES drift apart, ES serves stale or missing data indefinitely until something notices and repairs it deliberately.

That "something" is the reindex script built later in this session.

**Bottom line:** ES here is a search index over data that actually lives in SQLite, not a database in its own right.

## Why ES isn't a system of record

Three concrete reasons ES can't be the primary store:

| Property needed for "source of truth" | What ES gives you |
|---|---|
| ACID transactions | No multi-document transactions — a bulk request is a batch of independent writes |
| Immediate read-your-write consistency | A document isn't searchable until the next refresh cycle (default ~1s), not synchronously |
| Stable schema | A mapping is close to write-once — changing a field's type means a new index and a full reindex |

None of this is a flaw. ES trades away transactional guarantees for full-text search and fast aggregation over millions of documents.

## Task 1 — SQLite schema design

The schema mirrors the session 2 ES mapping field-for-field, with one structural difference in how each store enforces types.

| ES field | ES type | SQLite column | SQLite type |
|---|---|---|---|
| `timestamp` | `date` | `timestamp` | `TEXT` (ISO-8601 — SQLite has no native date type) |
| `level` | `keyword` | `level` | `TEXT` |
| `service` | `keyword` | `service` | `TEXT` |
| `message` | `text` | `message` | `TEXT` |
| `status_code` | `integer` | `status_code` | `INTEGER` |
| — | — | `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` (new — ES docs get an auto `_id`, SQLite needs an explicit PK) |

ES's mapping and SQLite's typing are opposite failure modes. ES locks a field's type down hard at index time and refuses a mismatched value. SQLite uses type affinity — a preference, not a guarantee — and stays permissive at insert time even against a typed column. For exmaple: if we attend to write a string to an integer column with SQLite, it will write it without throwing an error. Explicit typing in SQLite still documents intent and picks the right storage class; it just isn't the same hard guarantee session 2's mapping was.  

**Hands-on:**

```sql
CREATE TABLE logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  timestamp TEXT NOT NULL,
  level TEXT NOT NULL,
  service TEXT NOT NULL,
  message TEXT NOT NULL,
  status_code INTEGER NOT NULL
);

CREATE INDEX idx_logs_timestamp ON logs(timestamp);
```

The index on `timestamp` is a plain B-tree — the same structure already familiar from Postgres/MySQL. It's added because the API's `/search` endpoint already filters and sorts by date range, and SQLite will need to serve that same access pattern once it becomes authoritative.

## Task 2 — backfill script
Goal: writing the documents stored on ES in SQLite.

Reading every document out of an ES index is a different problem than querying it. A plain `search` request caps out at `index.max_result_window` (default 10,000) because it holds the whole result set in memory for scoring and sorting. To solve that, `elasticsearch.helpers.scan` wraps the scroll API instead — it pages through results in batches, never materializing more than one batch at a time, and is the correct tool for a full index dump regardless of how big the index actually is.

**Hands-on:** `session-5-proj/scripts/backfill_sqlite.py` reads every document from `logs-app` via `scan()` and inserts it into `logs`, making SQLite authoritative for the first time. Each row gets a fresh `AUTOINCREMENT` id — nothing carries over from ES's old, randomly-generated `_id`. That new id was flagged at the time to matter later: it becomes ES's explicit `_id` once the reindex script exists, which is what makes reindexing idempotent instead of duplicating documents on every run.

When we first tried to run the python script, a real gotcha surfaced. `load_dotenv()` with no arguments searches upward from the current working directory, not from the script's own location. `SQLITE_PATH` lives in `session-5-proj/.env`, so the script only worked because it happened to be run with that directory as the cwd — run it from anywhere else and it would silently miss the file. The fix pins the `.env` lookup explicitly:

```python
PROJECT_ROOT = Path(__file__).resolve().parent.parent  # session-5-proj/
load_dotenv(PROJECT_ROOT / ".env")
SQLITE_PATH = PROJECT_ROOT / os.environ.get("SQLITE_PATH", "db/logs.db")
```

This resolves `db/logs.db` relative to the project root, not the shell's cwd — explicit, not defaulted, matching this project's config convention.

```
$ sqlite3 logs.db "SELECT COUNT(*) FROM logs;"
5000
```

Matches the ES doc count exactly.

## Task 3 — reindex script

`session-5-proj/scripts/reindex_es.py` rebuilds `logs-app` from SQLite: delete the index, recreate it with the explicit mapping, bulk-load every row back in. That's a full rebuild, not an incremental upsert — a deliberate choice, because it's the only approach that guarantees ES ends up in exactly the state SQLite says it should, with no stale or orphaned leftovers from some earlier bad state. At 5,000 rows this costs nothing; the trade-off it makes gets revisited later in this session once "5,000 rows" turns into "a huge table."

Every bulk action carries an explicit `_id`, set to the row's SQLite id, instead of letting ES generate one. That's what makes reruns idempotent — we can easily match rows in SQLite to documents in ES.

Current `elasticsearch-py` docs (checked via context7, since ES client syntax drifts across versions) confirm `indices.create` takes `mappings` as a direct keyword argument now, not nested inside `body={"mappings": {...}}`:

```python
es.indices.create(index=INDEX_NAME, mappings=MAPPINGS)
```

**Hands-on:**

```
uv run python session-5-proj/scripts/reindex_es.py

$ curl -s "http://localhost:9200/logs-app/_count" | python3 -m json.tool
{ "count": 5000, ... }

$ curl -s "http://localhost:9200/logs-app/_doc/1" | python3 -m json.tool
{
    "_index": "logs-app",
    "_id": "1",
    "_source": {
        "timestamp": "2026-08-27T21:17:55.801773+00:00",
        "level": "INFO",
        "service": "auth",
        "message": "cache hit for key key-7354",
        "status_code": 204
    }
}
```

`_id: "1"` is the explicit-id linkage from SQLite, not ES's default. By default ES generates a random ~20-character, URL-safe base64 string for `_id` — not an autoincrement integer. Autoincrement isn't the default because ES is sharded: coordinating a single incrementing counter across shards would require cross-shard coordination on every write (need to look for the latest ID), defeating the parallelism sharding exists to provide. The plain integer `_id` shown here only appears because `reindex_es.py` explicitly passes SQLite's row id instead of letting ES generate its own.

This is similar in spirit to MongoDB's default `_id`, which is also auto-generated rather than incrementing — but the two aren't built the same way. A MongoDB `ObjectId` is structured: it embeds a timestamp, a machine/process identifier, and a counter, all packed into 12 bytes, so two ObjectIds can be roughly ordered by creation time just by comparing them. ES's default `_id` has no such structure — it's just random bytes, base64-encoded, with nothing embedded in it.

## Task 4 — the API's write path

### Choosing a SQLite driver

Three real options for SQLite access from Node/TS:

| | `node:sqlite` | `better-sqlite3` | `sqlite3` (mapbox) |
|---|---|---|---|
| Install | Built into Node — zero dependency | npm package, native bindings | npm package, native bindings |
| API style | Synchronous | Synchronous | Async/callback |
| Stability | Node's own label: "Active Development" — can shift across Node versions | Mature, stable API for years | Superseded, callback style adds friction |

Sync vs. async matters more than the package choice. Every SQLite operation here is a local, in-process file read or write — no network round-trip like ES — so there's nothing to gain from wrapping it in a `Promise`. That's why `better-sqlite3` displaced the older callback-based `sqlite3` as the ecosystem default.

`node:sqlite` was confirmed working unflagged on this VM's Node 24.15.0, and was the first recommendation — zero new dependency, matching this project's "explicit over defaulted" convention by using the platform directly.

However, we chose using `better-sqlite3` instead, for a reason specific to this project: it runs on a VM that gets revisited intermittently, sometimes after long gaps, and the VM's Node version drifts between those visits. A pinned dependency in `package-lock.json` behaves identically regardless of what Node version the VM has drifted to by then. A runtime built-in's behavior is whatever that future Node version happens to ship — and Node's own stability index explicitly flags `node:sqlite` as not guaranteed stable across releases. This reframes "dev vs. production" as really being about how many uncontrolled environment changes something needs to survive — a learning project revisited later on a drifting VM behaves more like long-lived production in that one dimension than like a throwaway script.

### A bug fixed

**`ts(4023)` — `"Exported variable 'db' has or is using name 'BetterSqlite3.Database' ... but cannot be named."`**  
At first we had the following line in [sqlite-client.ts](session-5-proj/src/sqlite-client.ts), which caused the IDE error above
```typescript
export const db = new Database(SQLITE_PATH);
```

`tsconfig.json` has `declaration: true`, so every file gets a companion `.d.ts`. `better-sqlite3`'s types export `Database` as a merged constructor function plus namespace — the actual class type lives at the nested `Database.Database`, and TS can't print a reference to that nested type into the generated declaration file on its own. The fix is a direct annotation:

```typescript
export const db: Database.Database = new Database(SQLITE_PATH);
```

Naming the type explicitly gives TS something concrete to write, instead of asking it to infer and print one.

### The write path itself

`session-5-proj/src/routes/logs.ts`, `POST /logs`: validate the body, insert into SQLite inside a `try/catch` → `handleSqliteError` on failure, then index into ES with `_id: String(id)` inside its own `try/catch` → `handleEsError` on failure.

Deliberately missing: what if a row is written to SQLite and then we fail writing to ES. Dual-write has no transaction spanning both stores — there's nothing to "roll back" to, since the SQLite insert already committed by the time ES is attempted. We will discuss about that in the [deep dive session](#deep-dive--the-dual-write-failure-mode).

**Hands-on:**

```
$ curl -s -X POST http://localhost:3000/logs \
  -H "Content-Type: application/json" \
  -d '{"timestamp":"2026-09-05T12:00:00Z","level":"ERROR","service":"checkout","message":"test dual write","status_code":500}'

$ sqlite3 session-5-proj/db/logs.db "SELECT * FROM logs ORDER BY id DESC LIMIT 1;"
5001|2026-09-05T12:00:00Z|ERROR|checkout|test dual write|500

$ curl -s "http://localhost:9200/logs-app/_doc/5001" | python3 -m json.tool
{ "_id": "5001", "found": true, "_source": { "timestamp": "2026-09-05T12:00:00Z", ... } }
```

Both stores agree on the same id, written through the API in one request.

## Deep dive — the dual-write failure mode

If the ES write fails (or the process crashes) after the SQLite write already committed, SQLite has the row and ES doesn't — and only SQLite's version is trustworthy. This is inherent to dual-write, not a bug to code around: there's no transaction spanning both stores, so retries reduce how often this happens but can't close the window to zero.

**Contrast with CDC (log-based sync).** The app makes exactly one write — to the database only. There is no "app writes to the CDC connector" step at all. A separate connector (e.g. Debezium, reading Postgres's or MySQL's write-ahead log) tails the database's own commit log, completely out of band from the request:

```
Dual-write:                              CDC:
  request → SQLite  ─┐                     request → SQLite   ← the only write.
           → ES      ┘                                          Succeeds or fails
  (two independent calls,                                       atomically, like any
   either can fail alone)                                       normal single write.

                                          (out of band, separate process:)
                                          connector reads DB's write-ahead log
                                                  │
                                                  ▼
                                                 ES
```

If the connector is down, the app's single write still succeeds normally — nothing about ES's or the connector's availability touches it. The database's write-ahead log is durable and retained (via a replication slot); the connector tracks its own durable read-offset and resumes exactly where it left off when it comes back, replaying every commit it missed with zero lost writes. This is bounded: if the connector is down longer than the log is retained, replay is no longer possible and a full resync is needed — the same tool as dual-write's recovery, just needed far less often.

The real distinction from dual-write isn't "no lag" — CDC is still eventually consistent. It's that CDC's catch-up is systematic and automatic, driven by durable log position tracking, while dual-write's recovery depends on a human noticing silent drift and running a reconciliation script by hand. CDC trades two lines of application code for a connector that's its own distributed system to run and monitor — exactly why **dual-write is still the default most projects, small ones and plenty of real production ones**, reach for first. CDC being adopted is the exception when volume/consistency needs justify the extra infrastructure, not the production default.

**"Eventually consistent," made concrete for this system:** SQLite is always immediately correct. ES is correct as of the last successful sync. `reindex_es.py` isn't a convenience script — it's the actual recovery mechanism this architecture depends on.

## Closing hands-on — recovery drill

```
$ docker compose stop elasticsearch # simulates ES is down, while SQLite is still up

$ curl -s -X POST http://localhost:3000/logs \
  -H "Content-Type: application/json" \
  -d '{"timestamp":"2026-09-05T13:00:00Z","level":"ERROR","service":"billing","message":"simulated ES outage","status_code":500}'
{"error":"elasticsearch_unavailable","reason":"Could not reach Elasticsearch"}

$ sqlite3 session-5-proj/db/logs.db "SELECT * FROM logs ORDER BY id DESC LIMIT 1;"
5002|2026-09-05T13:00:00Z|ERROR|billing|simulated ES outage|500

# At this point we have a record in SQLite that wasn't written to ES

$ docker compose start elasticsearch
$ uv run python session-5-proj/scripts/reindex_es.py
Reindexed 5002 docs into logs-app

$ curl -s "http://localhost:9200/logs-app/_doc/5002" | python3 -m json.tool
{ "_id": "5002", "found": true, "_source": { "service": "billing", "message": "simulated ES outage", ... } }
```

The row existed in SQLite while ES had nothing. Reindexing from SQLite caught ES back up — the exact drift the deep dive described, reproduced and repaired by hand.

## Beyond the curriculum — full rebuild vs. updating only what's missing

Question regarding `reindex_es.py`'s design: if a huge table is only missing or wrong on a single row, does it really make sense to delete and rebuild the *entire* index for that one document? And on the other side, isn't looping through every row to find what's missing also expensive?

**The problem with full rebuild.** Its cost is `O(entire table)`, completely independent of how much actually drifted. One wrong row out of 5,000 costs exactly the same as one wrong row out of 10 million — the script always pays for reindexing everything, because it has no way to know in advance that only one row is wrong. At this project's scale (5,000 rows) that cost is genuinely nothing, which is why it was the right call for `reindex_es.py` as written. It stops being the right call the moment "everything" gets big enough that rewriting it becomes slow or expensive to run routinely.

**The problem with brute-force diffing.** Looping through every row in SQLite, checking whether the matching document exists correctly in ES, and only touching what's missing sounds cheaper — but it isn't, in the way that matters. It's still `O(entire table)`: instead of paying to *rewrite* everything, it pays to *read and compare* everything. Same order of cost, just moved from the write side to the read side. At scale, this is barely better than a full rebuild — you've avoided rewriting documents that were already correct, but you still scanned the whole table to find that out.

**The actual fix: track what changed, don't discover it by scanning.** Both of the above share the same flaw — they treat "what needs to be synced" as something that has to be *discovered* by touching every row. The fix is to make that information available directly, so the sync job only ever looks at rows that changed:

```sql
ALTER TABLE logs ADD COLUMN updated_at TEXT NOT NULL DEFAULT (datetime('now'));
-- set/refresh updated_at on every INSERT and UPDATE
```

The sync job keeps a stored watermark — the timestamp of the last row it successfully synced — and on each run does:

```sql
SELECT * FROM logs WHERE updated_at > :last_synced_at;
```

Only rows that actually changed since the last run come back. Bulk-upsert just those into ES using the same explicit-`_id` trick already in use (so it overwrites the matching document instead of duplicating it), then advance the watermark to the newest `updated_at` just processed. This is sometimes called "poor man's CDC" — polling a change marker on a schedule instead of tailing the database's actual write-ahead log — and it's a completely reasonable middle ground when standing up real CDC infrastructure (a Debezium-style connector, a broker to run and monitor) isn't worth the operational cost yet.

A concrete sense of the difference: with 10 million rows in SQLite and exactly one of them changed, full rebuild reindexes all 10 million documents into a fresh index; brute-force diffing reads all 10 million rows to discover that only one needs touching; timestamp polling reads and writes exactly one document, because the `WHERE updated_at > :last_synced_at` filter already knows which row that is without touching the other 9,999,999.

| | Full rebuild | Brute-force diffing | Timestamp polling | True CDC |
|---|---|---|---|---|
| Cost when 1 row changed out of 10M | Reindex all 10M | Read all 10M to find the 1 | Read/write ~1 doc | Read/write ~1 doc |
| Handles deletes? | Trivially — deleted rows just aren't reinserted | Yes, if the diff also checks for ES docs with no matching SQLite row | Not by itself — a deleted row just disappears from the query, nothing signals "remove this from ES" | Yes — the log carries an actual delete event |
| Extra infra needed | None | None | None (a column + a stored watermark) | A connector (e.g. Debezium) plus something to run and monitor it |
| When it's the right tool | Small dataset, or drift too large/unknown in scope to trust anything incremental | Rarely the best choice — usually dominated by one of the other three | Routine day-to-day sync once dataset size makes full rebuild expensive | Same as polling, at higher write volume or when reliable delete-tracking matters |

**When a full rebuild is still genuinely necessary — don't delete the live index for it.** Some situations do call for rebuilding everything: a mapping change (session 2's immutability constraint — a changed field type needs a new index regardless of how sync normally works), or drift bad enough that trusting an incremental catch-up feels risky. Production systems still avoid `reindex_es.py`'s exact approach here, because deleting the live index first creates a real window where `logs-app` doesn't exist or is only half-populated, and anything querying it during that window gets wrong answers or outright errors. The standard fix is a new index plus an alias swap:

```
Before:  alias "logs-app" → index "logs-app-v1"        (queries go through the alias, never the raw index name)

Build:   create "logs-app-v2"
         bulk-load everything into it from SQLite
         verify doc count / spot-check before cutting over

Swap:    atomically repoint alias "logs-app" → "logs-app-v2"   (one atomic API call — no in-between state visible to readers)

Cleanup: delete "logs-app-v1"
```

Readers never see a gap, because the alias always points at a fully-built index — there's no moment where "logs-app" resolves to something empty or half-loaded. This project has queried `logs-app` by its raw name throughout, since aliases haven't come up yet in the curriculum; this is a natural next building block once a mapping change or a large full rebuild actually needs to happen for real, not something implemented in this session.

**What if there are many indexes, not just one?** Same principle, applied per index instead of globally. The fix isn't "loop through every index checking for drift" — that's the brute-force-diffing problem again, just multiplied by however many indices exist. Each index gets its own targeted sync path, driven by its own change marker (its own `updated_at` column, or its own CDC stream tied to its own source table). Total cost scales with how much data actually changed across all those domains, not with how many indices happen to be running — a quiet index with no writes costs nothing to keep in sync, regardless of how many other indices exist alongside it.

## Questions I Had

**In `reindex-es.py`, why is the reindex script's bulk variable called `actions`, not `documents`?** `actions` matches the bulk API's own vocabulary — each dict carries `_index`/`_id` metadata alongside a `_source` body, so it's an instruction (`index`/`create`/`delete`/`update`), not just a document. `_source` alone is the document; the dict as a whole is the operation to perform. The same reasoning applies retroactively to session 2's `action_stream()` in `scripts/generate_logs.py`.

**Why does `PROJECT_ROOT / "db/logs.db"` work without an f-string?** `pathlib.Path` overloads `__truediv__`, so `/` isn't string concatenation here — it's operator overloading, the same mechanism as overloading `+` on a custom class. `PROJECT_ROOT / "db/logs.db"` calls `PROJECT_ROOT.__truediv__(...)`, returning a new `Path` with the segments joined using the OS-correct separator. `sqlite3.connect()` accepts that `Path` object directly, since `Path` implements `__fspath__`.

*REMINDER: Operator overloading in Python allows you to redefine how built-in operators (like +, -, \*, ==, or <) behave when used with your custom objects*

## Deliverable

SQLite holds the log data as source of truth. `logs-app` is kept in sync with it via `reindex_es.py`, an explicit reindex script rather than an implicit assumption. The TypeScript API's `/logs` write path demonstrates the dual-write pattern end to end — and, via the closing hands-on, demonstrates recovering from its exact failure mode.
