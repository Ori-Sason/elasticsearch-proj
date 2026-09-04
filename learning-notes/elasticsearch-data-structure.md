# Data structures in Elasticsearch

## The Elasticsearch Polyglot Storage Architecture

```
                      ┌──► [Inverted Index] ──► Text (Tokens -> Doc IDs)
                      ├──► [BKD Trees]      ──► Numbers, Dates & Geo-points (Spatial Trees)
Your JSON Document ───┼──► [HNSW Graphs]    ──► Vector Embeddings (Nearest-Neighbor Graphs)
                      ├──► [Doc Values]     ──► Columnar Store (Doc ID -> Field Value) [Like ClickHouse]
                      └──► [Stored Fields]  ──► Document Store (Doc ID -> Compressed Raw JSON)
```
## The Five Parallel Worlds of an Elasticsearch Shard
When you send a JSON document to an index, Elasticsearch shreds it and writes it into these five distinct structural systems:
1. The Whole Document "Database" (`_source`)
    * **What it is:** A row-based document store. It takes your entire original JSON document, compresses it, and stores it on disk mapped to a Lucene internal document ID.
    * **Purpose:** It does not participate in searching or sorting. Its only job is to be read at the very end of a query to return the final JSON payload to the user.

2. The Text Search Engine (Inverted Index)
    * **What it is:** A `Token -> List of Doc IDs` map.
    * **Purpose:** Highly optimized for full-text search, stemming, synonyms, and fuzzy matching.

3. The Numeric & Date Engine (BKD Trees)
    * **What it is:** A multi-dimensional tree data structure (Block KD-Trees).
    * **Purpose:** If you tried to put numbers into an inverted index, range queries (like `price > 10 AND price < 50`) would be incredibly slow. BKD trees allow Elasticsearch to pinpoint numbers and geographic coordinates instantly using spatial coordinates.

4. The AI & Machine Learning Engine (HNSW Graphs)
    * **What it is:** Hierarchical Navigable Small World graphs.
    * **Purpose:** Used for dense vectors (KNN search). It maps text embeddings into a multi-dimensional geometric space so you can do semantic searches (e.g., searching for "feline" and finding documents about "cats").

5. The Analytics Engine (Doc Values)
    * **What it is:** A `Doc ID -> Field Value` columnar store.
    * **Purpose:** This is a column store (like ClickHouse). It ignores the text fields and organizes numbers, dates, and keywords into tightly packed, contiguous columns on disk for rapid sorting and math aggregations.

## Why did they build it this way?
No single data structure can be fast at everything.
* A column store (ClickHouse) is terrible at full-text search.
* An inverted index is terrible at mathematical averages and sorting.
* A row database (PostgreSQL/MongoDB) is slow at massive aggregations and text search.

Elasticsearch's "secret sauce" is that it forces you to pay the performance cost **at the moment of write (indexing)**. It takes a bit longer and uses more disk space to build all 5 of these data structures at once, but it means that **at read time (searching)**, it can answer any complex query in milliseconds by combining the strengths of all five structures.

To conclude:
* **The Cost:** Higher storage use and slower writes (because it builds all 5 structures simultaneously).
* **The Benefit:** Blazing-fast reads (because it instantly picks the perfect structure for the query).
