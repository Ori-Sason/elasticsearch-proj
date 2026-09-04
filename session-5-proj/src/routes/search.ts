import { Router } from "express";
import { esClient, INDEX_NAME } from "../es-client.js";
import { handleEsError } from "../handle-es-error.js";

export const searchRouter = Router();

// GET /search?q=<custome text>&level=ERROR&from_date=...&to_date=...&from=0&size=20
searchRouter.get("/search", async (req, res) => {
  const { q, level, from_date, to_date, from, size } = req.query;

  const must: object[] = [];
  const filter: object[] = [];

  if (typeof q === "string" && q.length > 0) {
    must.push({ match: { message: q } });
  }

  if (typeof level === "string" && level.length > 0) {
    filter.push({ term: { level } });
  }

  if (typeof from_date === "string" || typeof to_date === "string") {
    filter.push({
      range: {
        timestamp: {
          ...(typeof from_date === "string" ? { gte: from_date } : {}),
          ...(typeof to_date === "string" ? { lte: to_date } : {}),
        },
      },
    });
  }

  try {
    const result = await esClient.search({
      index: INDEX_NAME,
      query: { bool: { must, filter } },
      sort: [{ timestamp: "desc" }],
      from: from ? +from : 0,
      size: size ? +size : 20,
    });

    res.json({
      total: result.hits.total,
      hits: result.hits.hits.map((hit) => hit._source),
    });
  } catch (err) {
    handleEsError(err, res);
  }
});
