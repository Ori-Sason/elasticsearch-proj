# Session 5 — Ship a TypeScript API

## TL;DR

Wrapped the cluster in a small Express + `@elastic/elasticsearch` API: a `/search` endpoint translating session 3's `bool`/`match`/`term`/`filter` queries, and a `/stats` endpoint translating session 4's `terms` + nested `avg` + `date_histogram` aggregations.

Hit two real infrastructure bugs along the way — a client/server major-version mismatch, and a TypeScript literal-type narrowing issue on `calendar_interval` — both fixed, both worth understanding since they're the kind of thing that only shows up once code, not Dev Tools, is driving the queries.

Closed by making the client's two distinct failure modes — never reaching Elasticsearch versus Elasticsearch answering with an error — visible as different, sensible HTTP status codes instead of raw stack traces.

## Request flow

```
Browser / curl
      │
      ▼
Express route (/search or /stats)
      │  builds a Query DSL object, conditionally
      ▼
@elastic/elasticsearch Client
      │  connection pool (1 node here) — reused keep-alive socket
      │  retries: up to 3x, only on ConnectionError/Timeout or 502/503/504
      ▼
Elasticsearch :9200 (logs-app index)
      │
      ├─ reachable, valid request  → 200, real hits/aggregations
      ├─ reachable, bad request    → ResponseError, ES's own status code (e.g. 400)
      └─ unreachable / timed out   → ConnectionError / TimeoutError, no ES status code at all
```

## Walkthrough

### What the client adds over a raw HTTP call

Every query run through Kibana Dev Tools in sessions 1–4 was, underneath, a plain HTTP `POST` with a JSON body to `/logs-app/_search`. The Node client adds three things on top of that:

- **Connection pooling** — keeps a pool of persistent, keep-alive connections instead of a fresh TCP handshake per request. With one node in this cluster, the pool is one connection, reused.
- **Typed request builders** — the client's request object is close to 1:1 with the same Query DSL JSON already written by hand. `client.search({ index, query: {...}, aggs: {...} })` — the `query`/`aggs` keys are literally the same shape as the Dev Tools body.
- **Retry/backoff on transient failures** — checked directly in `node_modules/@elastic/transport/lib/Transport.js` rather than assumed, since this is library behavior, not Query DSL syntax that context7 covers. Default is `maxRetries: 3`, exponential backoff, and it only retries a `ConnectionError` or a `502`/`503`/`504` response — never a `400` or `404`, since those aren't transient.

Node discovery ("sniffing" — the client learning about a cluster's other nodes) exists in the library but doesn't do anything meaningful on a single-node dev cluster. Matters once a real multi-node cluster exists, skipped here.

**Bottom line:** the client doesn't change what gets sent to Elasticsearch. It changes how the *connection* to Elasticsearch is managed, and it gives query bodies a typed home in code instead of a JSON string.

### `/search` — conditional query assembly

The one genuinely new piece of logic this session needed: request params are optional and string-typed, but session 3's hardcoded queries always had every clause present.

[`session-5-proj/src/routes/search.ts`](/session-5-proj/src/routes/search.ts):

```ts
const must: object[] = [];
const filter: object[] = [];

if (typeof q === "string" && q.length > 0) {
  must.push({ match: { message: q } });
}
if (typeof level === "string" && level.length > 0) {
  filter.push({ term: { level } });
}
```

`q` becomes a `match` on `message` (scored, session 3's `must`), `level` becomes a `term` on `level` (unscored, session 3's `filter`), and an optional `from_date`/`to_date` pair becomes a `range` filter on `timestamp`. `from`/`size` map straight onto the search request's own pagination fields, sorted `timestamp: desc` by default.

`GET /search?q=connection&level=DEBUG&size=3` returns the same shape session 3's Dev Tools queries returned — `hits.total`, then each hit's `_source`.

### `/stats` — reusing session 4's aggregations

[`session-5-proj/src/routes/stats.ts`](/session-5-proj/src/routes/stats.ts) is a direct translation: `by_service` is the `terms` bucket with `avg_status` nested inside it (session 4's nested-metric pattern), `logs_over_time` is the `date_histogram`. An optional `level` query param reproduces session 4's "top error-producing services" hands-on exactly — `GET /stats?level=ERROR`.

`interval` (`hour`/`day`/`week`/`month`, defaulting to `day`) hit a real TypeScript error: `calendar_interval` isn't typed as `string` in the client, it's a literal union —

```ts
export type AggregationsCalendarInterval = 'second' | '1s' | 'minute' | '1m' | 'hour' | '1h' | 'day' | '1d' | 'week' | '1w' | 'month' | '1M' | 'quarter' | '1q' | 'year' | '1y';
```

— confirmed by grepping the installed package's `.d.ts` directly rather than guessing. A plain `string` (which is what a `req.query` value widens to) doesn't satisfy that, so `tsc` refused the call with "no overload matches."

Fix: validate the param against an explicit allow-list, and derive the type from the same array instead of typing it twice:

```ts
const VALID_INTERVALS = ["hour", "day", "week", "month"] as const;
type Interval = (typeof VALID_INTERVALS)[number];

function isValidInterval(value: string): value is Interval {
  return (VALID_INTERVALS as readonly string[]).includes(value);
}
```

`typeof VALID_INTERVALS` is the tuple type `readonly ["hour", "day", "week", "month"]`. `[number]` is TypeScript's indexed-access syntax — "the type at any numeric index" — which resolves to the union of every element's type, `"hour" | "day" | "week" | "month"`. Same mechanism as `arr[0]` returning one element's type, generalized to "any index."

None of that line survives to JavaScript. `type Interval = ...` is erased entirely at compile time — deleting it changes nothing about the emitted `.js`. The only part that's real, running JS is `VALID_INTERVALS.includes(value)` inside `isValidInterval` — an actual array scan, on every request, checking the param against the four allowed strings. The `as const` on the array is what makes the type-level derivation possible in the first place: without it, the array's type would widen to plain `string[]`, and `(typeof VALID_INTERVALS)[number]` would come out as just `string`, not the four-way union needed.

### The client/server version mismatch

When we started the project, we've used the most recent version of the ES client, `9.5.1`. We did that by not mentioning the version in `package.json` file.
Simply ran `npm install @elastic/elasticsearch` with no version pin → installed the latest major, `9.5.1`. The cluster (`docker-compose.yaml`) runs Elasticsearch `8.15.0`. 

First request threw:

```
ResponseError: media_type_header_exception
    Caused by:
        status_exception: Accept version must be either version 8 or 7, but found 9. Accept=application/vnd.elasticsearch+json; compatible-with=9
```

The client sends `compatible-with=<major>` on its `Accept`/`Content-Type` headers. Elasticsearch 8.15 only accepts `compatible-with=7` or `8`, and rejects `9` outright. 

Fixed by pinning the client to the matching major: `npm install @elastic/elasticsearch@8`.

**Bottom line:** the ES client and the ES server carry a major-version contract that raw HTTP calls don't enforce. An unpinned `npm install` against a pinned-version cluster is a real, easy-to-hit failure mode, not a hypothetical one.

### Deep dive: telling connection failures from Elasticsearch errors

*NOTE: At this point, we didn't have error handling in our endpoints. So, there were no try-catch blocks in [search.ts](/session-5-proj/src/routes/search.ts) and [stats.ts](/session-5-proj/src/routes/stats.ts), and also [handle-es-error.ts](/session-5-proj/src/handle-es-error.ts) didn't exist.*

The client throws two structurally different errors depending on where things went wrong:

| | `ConnectionError` / `TimeoutError` | `ResponseError` |
|---|---|---|
| Meaning | Never reached Elasticsearch, or it didn't answer in time | Elasticsearch answered, and the answer was an error |
| Example cause | Wrong host/port, ES container down | Bad query syntax, unparseable field value |
| Retried automatically | Yes, up to 3x | No — a bad query won't fix itself on retry |
| Has ES's own status code | No — there was no ES response to read one from | Yes, via `err.statusCode` (a getter over `err.meta.statusCode`) |

Hands-on, pointing `ES_URL` at a dead port produced (we've changed the port in `.env` file to `9201`):

```
ConnectionError
    at SniffingTransport._request (.../Transport.ts:717:17)
```

And `GET /search?from_date=not-a-real-date` produced a real `ResponseError` from ES's own date parser:

```
ResponseError: search_phase_execution_exception
    Root causes:
        parse_exception: failed to parse date field [no-real-date] with format [strict_date_optional_time||epoch_millis]
```

[`session-5-proj/src/handle-es-error.ts`](/session-5-proj/src/handle-es-error.ts) turns that distinction into real status codes, shared by both routes since the logic is identical either place:

```ts
export function handleEsError(err: unknown, res: Response) {
  if (err instanceof errors.ResponseError) {
    res.status(err.statusCode ?? 400).json({
      error: "elasticsearch_error",
      reason: err.message,
    });
    return;
  }
  if (err instanceof errors.ConnectionError || err instanceof errors.TimeoutError) {
    res.status(503).json({
      error: "elasticsearch_unavailable",
      reason: "Could not reach Elasticsearch",
    });
    return;
  }
  console.error(err);
  res.status(500).json({ error: "internal_error", reason: "Unexpected error" });
}
```

Re-running both scenarios through the wrapped routes:

```json
{"error":"elasticsearch_unavailable","reason":"Could not reach Elasticsearch"}
```

```json
{"error":"elasticsearch_error","reason":"search_phase_execution_exception\n\tRoot causes:\n\t\tparse_exception: ..."}
```

`503` for the unreachable case — the caller's request wasn't the problem, the upstream was down. ES's own code (here effectively a `400`-class parse failure) passed through for the bad-input case — the caller's request was the problem.

## Questions I Had

### Is the ES client's connection pool a single endpoint, or does it talk to each node directly?

No single endpoint — the client talks directly to whichever node processes it's given, and does its own client-side load balancing across them.

```
Single-node dev cluster (this project):
  Client → connection pool = [ node1:9200 ]  (nothing to balance across)

Real multi-node cluster:
  Client → connection pool = [ node1:9200, node2:9200, node3:9200 ]
             │
             ├─ round-robins requests across all three
             ├─ marks a node "dead" on failure, skips it, retries elsewhere
             └─ any node can answer any query — it's a coordinating node,
                internally fans out to whichever shards actually hold the data
```

Two ways the client learns the node list:

1. **Static** — the full list is passed in `node: [...]` at construction.
2. **Sniffing** — one seed node is passed, the client calls the cluster's `_nodes` API against it, and adds every node it discovers to the pool automatically. This is the "sniffing" flagged earlier as skipped-for-now — it only does something once there's more than one node to discover.

Any single node in an ES cluster can serve as the entry point for a query touching data on *other* nodes — that's the coordinating-node role from session 3's request-lifecycle diagram, just one level up. Hitting node1 alone still gets correct cluster-wide results. The pool's job is performance and failover, not correctness — all nodes don't need to be reachable for any one query to succeed, only parallelism/redundancy is lost if some are down.

**Contrast with a load balancer:** production ES deployments often instead put a real LB (ALB, nginx) in front of the whole cluster and give every client just that one VIP. In that setup the client's own pool collapses to size 1 again — pointed at the LB — and node-level balancing happens outside the client entirely, invisibly. Both models are legitimate; Elastic's clients support client-side balancing so the extra infra piece is optional, not required.

### How does Kibana talk to Elasticsearch — same way as this session's Node client?

Yes — literally the same client library, `@elastic/elasticsearch`, just embedded inside Kibana's own backend instead of this session's Express app.

Kibana's server is a Node.js/TypeScript app. Its data-access layer uses the identical npm package installed in `session-5-proj`, configured with the `ELASTICSEARCH_HOSTS`/auth settings from its own environment (see `docker-compose.yaml`'s `ELASTICSEARCH_HOSTS=http://elasticsearch:9200`). Same connection pool mechanics, same retry/backoff defaults, same `ConnectionError`/`ResponseError` distinction under the hood — none of that is custom-built for Kibana, it's the same library doing the same job.

Concretely, for Dev Tools specifically: typing a query into the console and hitting the ▶ button sends that raw request from the browser to a Kibana backend endpoint (`/api/console/proxy`), and Kibana's server takes that JSON body and issues it to Elasticsearch through its own instance of the same client — not a special bypass path.

**Bottom line:** Kibana isn't a different way of talking to Elasticsearch. It's the same client, the same wire protocol, wrapped in a UI. This session's `session-5-proj` API and Kibana are both just "a Node process holding an `@elastic/elasticsearch` client pointed at this cluster" — one has a web UI on top, one has two routes.
