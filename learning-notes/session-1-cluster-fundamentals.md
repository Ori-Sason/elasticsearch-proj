# Session 1 — Cluster fundamentals notes

Concepts and troubleshooting covered while working through Session 1 (standing up the cluster). Kept as a reference, not required reading to continue.

## Core concepts: node, cluster, index, document, shard

- **Document** — the basic unit of data, a single JSON object. Analogous to a row in a relational table, or a document in MongoDB.
- **Index** — a named collection of documents sharing a mapping. Analogous to a table, or a MongoDB collection.
- **Node** — a single running Elasticsearch process (one JVM). It stores data and handles requests.
- **Cluster** — one or more nodes working together as one logical system. A single-node setup is technically a "cluster of one."
- **Shard** — an index isn't stored as one blob; it's split into shards, each a self-contained Lucene index. Shards are the actual unit Elasticsearch distributes across nodes.
  - **Primary shard** — holds the real data, one of N pieces the index is split into.
  - **Replica shard** — a copy of a primary shard, for fault tolerance and read scaling.

## Replica placement is a hard rule, not a performance tweak

A replica shard is **never** allowed to live on the same node as its primary — this is enforced by Elasticsearch's shard allocator regardless of CPU, threads, or disk space available. The reason: a replica's entire purpose is fault tolerance (if the node holding the primary dies, the data still exists elsewhere). A replica on the same node as its primary would provide zero protection, so Elasticsearch won't place one there.

Consequence: a fresh single-node cluster, using an index's default settings (1 replica), will have its replica shards sitting **unassigned** — there's nowhere valid to put them. Cluster health reports **yellow**, not green (not broken — just not fully redundant). Fix for a single-node dev cluster: explicitly set `number_of_replicas: 0` on the index, and treat that as a documented dev-only choice, not a default, since it means zero redundancy.

Replica shards are also *not* like an AWS RDS read-replica in one respect: RDS read-replicas lag asynchronously, while Elasticsearch keeps replica shards in near-lockstep — writes replicate to replicas as part of the same indexing operation, not on a separate lag.

## Request routing (I've asked about "orchestrator")

There's no separate orchestrator process. Any node can act as the **coordinating node** for a given request — whichever node a client happens to talk to plays that role for that one request.

- **Writes**: which primary shard owns a document is deterministic — `hash(document_id) % number_of_primary_shards`. Every write for a given document always routes to the same primary shard, which processes it and then forwards to its replicas. Since a specific document is always handled by exactly one primary, there's no race between primaries over the same document — this is how Elasticsearch avoids needing a traditional lock manager. There are no cross-document transactions.
- **Reads**: the coordinating node can pick any copy of the relevant shard — primary or replica — often round-robin, to spread query load. This is the read-scaling benefit of replicas.

In larger clusters nodes can specialize (data nodes, master-eligible nodes managing cluster state, coordinating-only nodes); on a single-node dev cluster every role collapses onto the one node.

## Why Elasticsearch is fast (and why it's not "in-memory" like Redis)

Redis is fundamentally in-memory — the dataset must fit in RAM. Elasticsearch is different: data lives on disk in Lucene segment files, and is not required to fit in RAM. Speed comes from two separate things:

1. The inverted index is an algorithmically better structure for text search (lookup instead of scan) — true even with zero caching.
2. The OS page cache does a lot of the "feels like memory" work. Elasticsearch deliberately keeps its JVM heap small (commonly capped around 50% of available RAM) so the rest of RAM is free for the OS to cache the actual Lucene segment files being read from disk. Some structures (like the term dictionary) are also memory-mapped.

So it's closer to "a well-cached disk-backed index" than "an in-memory store." Durability is also stronger by default than a plain in-memory store: writes go through a write-ahead log (the **translog**) covering the window between a write and the periodic flush to disk.

## The `docker-compose.yaml` for Session 1

Key settings and why each one is there:

- `discovery.type=single-node` — normally nodes discover each other and elect a master via quorum vote; with one node that doesn't apply, so this tells Elasticsearch to self-elect as master immediately rather than sit waiting for peers that don't exist.
- `xpack.security.enabled=false` — disables auth/TLS between client and Elasticsearch. Explicitly a dev-only shortcut; a real deployment needs this on (this is what the curriculum's Stretch "basic security" task revisits).
- Explicit JVM heap size (`ES_JAVA_OPTS=-Xms512m -Xmx512m`) — keeps the heap bounded and explicit rather than auto-sized, consistent with the project's "config explicit over defaulted" convention, and consistent with wanting RAM left over for OS page cache.
- A named volume for the Elasticsearch data directory — without it, `docker compose down` would wipe the index.

## Hands-on: creating an index and watching the replica rule happen

With the cluster up, we logged into Kibana UI on [http://localhost:5601/](http://localhost:5601/).
There go to Management → Dev Tools, there's a console there for sending raw requests to Elasticsearch — this is the standard way people interact with ES day-to-day, alongside curl.

Running `GET _cluster/health` first showed `status: green` with 28 active primary shards — these are Elasticsearch's own internal system indices, which are created with 0 replicas by default, so the replica-placement issue doesn't show up on them. More on that below.

Creating a plain index with no explicit settings makes the rule visible:

```
PUT test-logs
```

`GET _cluster/health` right after that returned `status: yellow`, `active_primary_shards: 29`, `unassigned_shards: 1` — the new index's default replica (Elasticsearch creates every index with `number_of_replicas: 1` unless told otherwise) had nowhere valid to be placed, exactly as predicted by the placement rule above. Yellow here means "healthy but not redundant," not broken — the primary shard is active and the index is fully readable/writable.

Fix applied:

```
PUT test-logs/_settings
{
  "number_of_replicas": 0
}
```

After that, `GET _cluster/health` returned `status: green`, `unassigned_shards: 0`. Worth noting *why* this setting can be changed on a live index with no downtime: `number_of_replicas` is a **dynamic** setting — changing it just tells Elasticsearch to stop wanting a copy it can't place (or to start wanting more copies). Contrast with `number_of_shards`, which is fixed at index-creation time, since it determines the very hash routing (`hash(document_id) % number_of_primary_shards`) that decides which primary shard owns each document — changing it after the fact would mean physically reorganizing where every document lives.

One subtlety confirmed hands-on: setting `number_of_replicas: 0` doesn't mean "no replica exists *yet*" — it means "this index is configured to want zero replicas." Adding a second node to the cluster later would **not** retroactively cause a replica for `test-logs` to appear; only explicitly raising `number_of_replicas` again would make Elasticsearch start placing one.

Inspected in Kibana's UI (Menu → Stack Management → Index Management → `test-logs`): 1 primary shard, 0 replicas, 0 docs, matching the Dev Tools output exactly — the UI is just a view over the same cluster state.

## Where the original 28 shards came from

`GET _cat/indices?v` and `GET _cat/shards?v` show what those first 28 shards actually were: indices named `.kibana_8.15.0_001`, `.kibana_task_manager_8.15.0_001`, `.internal.alerts-*`, `.apm-agent-configuration`, `.slo-observability.*`, and similar — all created by **Kibana**, the moment it first connected to the empty cluster and initialized itself.

Kibana isn't a separate database with its own storage — it's itself just another Elasticsearch client. All of its own application state (dashboards, saved searches, alerting rule definitions, background task scheduling, ILM history, per-feature config for APM/ML/security/observability/SLO, even for features never touched) is stored as ordinary documents in ordinary Elasticsearch indices. The instant Kibana boots against a fresh cluster, it bootstraps dozens of these indices to hold its own metadata — that's the 28 shards present before any user index was created.

Two conventions visible in that output:

- A **leading dot** (`.kibana...`, `.internal...`) marks a system index — internal plumbing, not user data. These are hidden from normal index listings and excluded from wildcard patterns like `GET */_search` by default, so user queries don't accidentally sweep them in.
- Every one of them has `rep` (replicas) = **0**, which is why the cluster started `green` rather than `yellow` before anything was touched. Elasticsearch's defaults deliberately set these system indices to 0 replicas out of the box (low-stakes, easily regenerated metadata), unlike the `number_of_replicas: 1` default a plain user-created index like `test-logs` gets.
