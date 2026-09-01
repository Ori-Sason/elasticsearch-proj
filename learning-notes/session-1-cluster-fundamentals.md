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
