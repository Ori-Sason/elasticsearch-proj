import os
import sqlite3
from pathlib import Path

import psycopg
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

SQLITE_PATH = (PROJECT_ROOT / os.environ["SQLITE_PATH"]).resolve()
PG_DSN = (
    f"host={os.environ['PG_HOST']} port={os.environ['PG_PORT']} "
    f"dbname={os.environ['PG_DB']} user={os.environ['PG_USER']} "
    f"password={os.environ['PG_PASSWORD']}"
)

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    level TEXT NOT NULL,
    service TEXT NOT NULL,
    message TEXT NOT NULL,
    status_code INTEGER NOT NULL
);
"""


def main() -> None:
    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    rows = sqlite_conn.execute(
        "SELECT id, timestamp, level, service, message, status_code FROM logs"
    ).fetchall()
    sqlite_conn.close()

    with psycopg.connect(PG_DSN) as pg_conn:
        with pg_conn.cursor() as cur:
            cur.execute(CREATE_TABLE)
            cur.execute("TRUNCATE TABLE logs") # Clears the table (delete rows)
            with cur.copy(
                "COPY logs (id, timestamp, level, service, message, status_code) "
                "FROM STDIN"
            ) as copy:
                for row in rows:
                    copy.write_row(row)
        pg_conn.commit()

    print(f"Loaded {len(rows)} rows from {SQLITE_PATH} into Postgres logs_fts.logs")


if __name__ == "__main__":
    main()
