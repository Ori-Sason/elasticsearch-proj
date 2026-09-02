# Session 1 — Cluster fundamentals

## TL;DR

Stood up a single-node Elasticsearch + Kibana cluster with Docker Compose, checked its health, created a test index by hand, and watched it go yellow until we told it not to expect a replica it had nowhere to place. Covered what a node, cluster, index, document, and shard actually are, and traced where the cluster's 28 starting shards came from.

## What we covered

- **Document** — one record, a single JSON object. Same idea as a row in a SQL table or a document in MongoDB, though unlike a SQL row it has no fixed schema unless one is explicitly defined (that's the mapping — covered in Session 2).

- **Index** — a named collection of documents that share a mapping. Same idea as a table, or a MongoDB collection. The analogy breaks down at the storage layer: a SQL table is one physical structure, but an index is never stored as a single blob — it's always split into shards from the moment it's created.

- **Node** — one running Elasticsearch process (one JVM). It stores data and serves requests. Nothing more exotic than any other server process — just this one happens to speak the Elasticsearch protocol.

- **Cluster** — one or more nodes working together as one logical system, sharing cluster state (which indices exist, which shards live where, etc.). A single-node setup is technically "a cluster of one," which is why a fresh single-node deployment still reports a `cluster_name` and has cluster-level health.

- **Shard** — an index is split into shards, and shards, not indices, are the actual unit Elasticsearch distributes across nodes. Each is a self-contained Lucene index under the hood. Two roles:
  - **Primary** — holds the authoritative copy of a slice of the index's documents.
  - **Replica** — a live copy of a primary, kept for fault tolerance and to spread out read load. Not a snapshot taken periodically — every write is applied to the replica as part of the same indexing operation, so it never falls behind the way an async read-replica would.

**Replica placement is a hard allocator rule, not a resource or performance setting.** A replica shard is never allowed to live on the same node as its primary — Elasticsearch's shard allocator enforces this unconditionally. The reasoning is pure fault tolerance: a replica exists so that if the node holding the primary dies, the data survives elsewhere. A replica sitting on the same node as its primary would die with it, providing zero protection, so the allocator refuses to place one there — no exceptions.

Consequence for a single-node cluster: a normal index, created with its defaults (1 replica), will always have that replica stuck **unassigned**, because there's no second node to host it. Cluster health reports **yellow**, not green — not broken, just not redundant. The dev fix (used here) is to explicitly set `number_of_replicas: 0` on the index and treat that as a deliberate, documented "no redundancy" choice for local development, not a default to carry into anything real.

One place the AWS RDS read-replica analogy breaks: RDS read replicas replicate asynchronously and can lag behind the primary by some interval. Elasticsearch doesn't work that way — a write isn't considered acknowledged until it's been applied to all in-sync replicas too, so replicas stay in lockstep with the primary rather than trailing it.

**There's no separate "orchestrator" process — any node can act as the coordinating node** for a given request, meaning whichever node the client happens to talk to plays that role for that one request. Writes and reads are routed differently:
- **Writes**: which primary shard owns a given document is deterministic — `hash(document_id) % number_of_primary_shards`. Every write for a specific document ID always lands on the same primary shard, which processes it and then forwards the write to its replicas. Because a document is always owned by exactly one primary, two primaries can never race over the same document — this is how Elasticsearch avoids needing a traditional lock manager. There are no cross-document transactions, which is the trade-off for that simplicity.
- **Reads**: the coordinating node can serve the request from any copy of the relevant shard — primary or replica — typically round-robin, which is the actual point of having replicas: spreading out query load, not just safety.

On a larger cluster, nodes can specialize (dedicated data nodes, master-eligible nodes that manage cluster state, coordinating-only nodes that just route traffic); on this single-node dev cluster every one of those roles collapses onto the one node.

**Elasticsearch is not an in-memory store like Redis.** Redis requires its entire dataset to fit in RAM. Elasticsearch's data lives on disk in Lucene segment files and is never required to fit in memory. Speed comes from two separate mechanisms, not from keeping everything resident in RAM:
1. The **inverted index** — a lookup table mapping each term to the documents containing it — is an algorithmically better structure for text search than a linear scan, true even with zero caching involved.
2. The OS **page cache** does most of the "feels like memory" work: Elasticsearch deliberately caps its JVM heap small (commonly around 50% of available RAM) precisely so the rest of RAM is left free for the operating system to cache the Lucene segment files being read from disk. Some structures (like the term dictionary) are also memory-mapped directly.

So it's closer to "a disk-backed index that's very well cached by the OS" than "an in-memory store." Durability is also stronger by default than a plain in-memory store: every write goes through a write-ahead log (the **translog**) covering the window between the write and the next periodic flush to disk, so a crash between flushes doesn't lose acknowledged writes.

## What we did

Wrote [`/docker-compose.yaml`](/docker-compose.yaml) for a single-node Elasticsearch + Kibana stack. Key settings and why each is there:
- `discovery.type=single-node` — normally nodes discover each other and elect a master via quorum vote; with one node that process doesn't apply, so this tells Elasticsearch to self-elect as master immediately instead of waiting for peers that will never show up.
- `xpack.security.enabled=false` — disables auth/TLS between client and Elasticsearch. Explicitly a dev-only shortcut, called out as such rather than left implicit — a real deployment needs this on (a stretch-goal task in the curriculum revisits it).
- `ES_JAVA_OPTS=-Xms512m -Xmx512m` — an explicit, fixed JVM heap size rather than letting Elasticsearch auto-size it, consistent with the project's "config explicit over defaulted" convention and with wanting RAM left over for the OS page cache (see the Redis comparison above).
- A named volume for the Elasticsearch data directory, so `docker compose down` doesn't wipe the index.

Logged into Kibana at [http://localhost:5601/](http://localhost:5601/) and used Dev Tools (Management → Dev Tools) — a console built into Kibana for sending raw HTTP requests to Elasticsearch, the same way `curl` would, just with syntax highlighting and history.

Ran `GET _cluster/health` first, before creating anything: `status: green`, `active_primary_shards: 28`. That's 28 shards that existed before any user index was created — turned out to be Elasticsearch's own internal system indices, explained in [Questions I had](#questions-i-had) below.

Created a plain index with no explicit settings:

```
PUT test-logs
```
returned:
```json
{
  "acknowledged": true,
  "shards_acknowledged": true,
  "index": "test-logs"
}
```

Then `GET _cluster/health` again:

```json
{
  "cluster_name": "docker-cluster",
  "status": "yellow",
  "timed_out": false,
  "number_of_nodes": 1,
  "number_of_data_nodes": 1,
  "active_primary_shards": 29,
  "active_shards": 29,
  "relocating_shards": 0,
  "initializing_shards": 0,
  "unassigned_shards": 1,
  "delayed_unassigned_shards": 0,
  "number_of_pending_tasks": 0,
  "number_of_in_flight_fetch": 0,
  "task_max_waiting_in_queue_millis": 0,
  "active_shards_percent_as_number": 96.66666666666667
}
```

`status: yellow`, `active_primary_shards: 29`, `unassigned_shards: 1` — exactly the replica-placement rule from above showing up live. `test-logs` was created with Elasticsearch's default `number_of_replicas: 1`, and that replica had nowhere valid to go on a single-node cluster. Yellow here specifically means "healthy but not redundant, not broken" — the primary shard is active, so the index is fully readable and writable the whole time.

Fix applied:

```
PUT test-logs/_settings
{
  "number_of_replicas": 0
}
```

After that, `GET _cluster/health` returned `status: green`, `unassigned_shards: 0`.

Worth noting *why* this can be changed on a live index with zero downtime: `number_of_replicas` is a **dynamic** setting — changing it just tells Elasticsearch to stop wanting a copy it can't place (or to start wanting more). Contrast with `number_of_shards`, which is fixed permanently at index-creation time, because it determines the very hash routing (`hash(document_id) % number_of_primary_shards`) that decides which primary shard owns each document — changing that after the fact would mean physically relocating every document in the index.

One subtlety confirmed hands-on: setting `number_of_replicas: 0` doesn't mean "no replica exists *yet*" — it means "this index is configured to want zero replicas." Adding a second node to the cluster later would **not** retroactively cause a replica for `test-logs` to appear on its own; only explicitly raising `number_of_replicas` again would make Elasticsearch start placing one.

Inspected the result in Kibana's UI (Menu → Stack Management → Index Management → `test-logs`): 1 primary shard, 0 replicas, 0 docs, matching the Dev Tools output exactly — the UI is just a view over the same cluster state, not a separate source of truth.

<div align="center">
  <img src="/learning-notes/images/session1-1.png" width="1000">
</div>

## Questions I had

**Where did the original 28 shards come from?**

`GET _cat/indices?v` and `GET _cat/shards?v` show what those first 28 shards actually were: indices named `.kibana_8.15.0_001`, `.kibana_task_manager_8.15.0_001`, `.internal.alerts-*`, `.apm-agent-configuration`, `.slo-observability.*`, and similar — all created by **Kibana**, the moment it first connected to the empty cluster and initialized itself.

Kibana isn't a separate database with its own storage — it's itself just another Elasticsearch client. All of its own application state (dashboards, saved searches, alerting rule definitions, background task scheduling, ILM history, per-feature config for APM/ML/security/observability/SLO, even for features never touched) is stored as ordinary documents in ordinary Elasticsearch indices. The instant Kibana boots against a fresh cluster, it bootstraps dozens of these indices to hold its own metadata — that's the 28 shards present before any user index was created.

Two conventions visible in that output:
- A **leading dot** (`.kibana...`, `.internal...`) marks a system index — internal plumbing, not user data. These are hidden from normal index listings and excluded from wildcard patterns like `GET */_search` by default, so ordinary queries don't accidentally sweep them in.
- Every one of them has `rep` (replicas) = **0**, which is why the cluster started `green` rather than `yellow` before anything was touched. Elasticsearch's defaults deliberately set these system indices to 0 replicas out of the box (low-stakes, easily regenerated metadata), unlike the `number_of_replicas: 1` default a plain user-created index like `test-logs` gets.
