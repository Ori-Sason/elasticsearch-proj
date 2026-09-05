import path from "node:path";
import Database from "better-sqlite3";

const PROJECT_ROOT = path.resolve(import.meta.dirname, ".."); // session-5-proj/
const SQLITE_PATH = path.resolve(PROJECT_ROOT, process.env.SQLITE_PATH ?? "db/logs.db");

export const db: Database.Database = new Database(SQLITE_PATH);
