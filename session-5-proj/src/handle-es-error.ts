import { errors } from "@elastic/elasticsearch";
import type { Response } from "express";

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
