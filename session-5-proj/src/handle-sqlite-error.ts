import Database from "better-sqlite3";
import type { Response } from "express";

export function handleSqliteError(err: unknown, res: Response) {
  if (err instanceof Database.SqliteError) {
    if (err.code.startsWith("SQLITE_CONSTRAINT")) {
      res.status(400).json({
        error: "sqlite_bad_input",
        reason: err.message,
      });
      return;
    }

    res.status(503).json({
      error: "sqlite_unavailable",
      reason: err.message,
    });
    return;
  }

  console.error(err);
  res.status(500).json({ error: "internal_error", reason: "Unexpected error" });
}
