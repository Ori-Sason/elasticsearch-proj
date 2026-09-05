"""One-time backfill: copy existing ES documents into SQLite, making SQLite the source of truth."""
import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv
from elasticsearch import Elasticsearch
from elasticsearch.helpers import scan

PROJECT_ROOT = Path(__file__).resolve().parent.parent  # session-5-proj/
load_dotenv(PROJECT_ROOT / ".env")

ES_URL = os.environ.get("ES_URL", "http://localhost:9200")
SQLITE_PATH = PROJECT_ROOT / os.environ.get("SQLITE_PATH", "db/logs.db")
INDEX_NAME = "logs-app"


def main():
    es = Elasticsearch(ES_URL)
    conn = sqlite3.connect(SQLITE_PATH)
    cur = conn.cursor()

    count = 0
    for doc in scan(es, index=INDEX_NAME, query={"query": {"match_all": {}}}):
        source = doc["_source"]
        cur.execute(
            "INSERT INTO logs (timestamp, level, service, message, status_code) VALUES (?, ?, ?, ?, ?)",
            (source["timestamp"], source["level"], source["service"], source["message"], source["status_code"]),
        )
        count += 1

    conn.commit()
    conn.close()
    print(f"Backfilled {count} rows into {SQLITE_PATH}")


if __name__ == "__main__":
    main()