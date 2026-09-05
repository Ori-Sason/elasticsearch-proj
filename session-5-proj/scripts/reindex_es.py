"""Rebuild the ES index from SQLite. SQLite is the source of truth; this recomputes the derived copy."""
import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv
from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk

PROJECT_ROOT = Path(__file__).resolve().parent.parent  # session-5-proj/
load_dotenv(PROJECT_ROOT / ".env")

ES_URL = os.environ.get("ES_URL", "http://localhost:9200")
SQLITE_PATH = PROJECT_ROOT / os.environ.get("SQLITE_PATH", "db/logs.db")
INDEX_NAME = "logs-app"

MAPPINGS = {
    "properties": {
        "timestamp": {"type": "date"},
        "level": {"type": "keyword"},
        "service": {"type": "keyword"},
        "message": {"type": "text"},
        "status_code": {"type": "integer"},
    }
}


def row_to_action(row):
    row_id, timestamp, level, service, message, status_code = row
    return {
        "_index": INDEX_NAME,
        "_id": row_id,
        "_source": {
            "timestamp": timestamp,
            "level": level,
            "service": service,
            "message": message,
            "status_code": status_code,
        },
    }


def main():
    es = Elasticsearch(ES_URL)
    conn = sqlite3.connect(SQLITE_PATH)

    if es.indices.exists(index=INDEX_NAME):
        es.indices.delete(index=INDEX_NAME)
    es.indices.create(index=INDEX_NAME, mappings=MAPPINGS)

    rows = conn.execute("SELECT id, timestamp, level, service, message, status_code FROM logs")
    actions = (row_to_action(row) for row in rows)

    success, errors = bulk(es, actions, raise_on_error=False)
    conn.close()

    print(f"Reindexed {success} docs into {INDEX_NAME}")
    if errors:
        print(f"Errors: {len(errors)}")
        for error in errors[:5]:
            print(error)


if __name__ == "__main__":
    main()