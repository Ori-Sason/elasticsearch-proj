import { Router } from "express";
import { db } from "../sqlite-client.js";
import { esClient, INDEX_NAME } from "../es-client.js";
import { handleEsError } from "../handle-es-error.js";
import { handleSqliteError } from "../handle-sqlite-error.js";

export const logsRouter = Router();

const insertLog = db.prepare(
  "INSERT INTO logs (timestamp, level, service, message, status_code) VALUES (@timestamp, @level, @service, @message, @status_code)"
);

// POST /logs { timestamp, level, service, message, status_code }
logsRouter.post("/logs", async (req, res) => {
  const { timestamp, level, service, message, status_code } = req.body;

  if (
    typeof timestamp !== "string" ||
    typeof level !== "string" ||
    typeof service !== "string" ||
    typeof message !== "string" ||
    typeof status_code !== "number"
  ) {
    res.status(400).json({ error: "invalid_body", reason: "timestamp, level, service, message, status_code are all required" });
    return;
  }

  const doc = { timestamp, level, service, message, status_code };

  // 1. SQLite write — source of truth, commits first
  let id: number | bigint;
  try {
    const result = insertLog.run(doc);
    id = result.lastInsertRowid;
  } catch (err) {
    handleSqliteError(err, res);
    return;
  }

  // 2. ES write — derived copy, same id as SQLite's row
  try {
    await esClient.index({ index: INDEX_NAME, id: String(id), document: doc });
  } catch (err) {
    handleEsError(err, res);
    return;
  }

  res.status(201).json({ id, ...doc });
});
