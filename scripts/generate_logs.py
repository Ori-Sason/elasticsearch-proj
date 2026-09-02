"""Generate synthetic application logs and bulk-index them into logs-app."""
import os
import random
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk

load_dotenv()

ES_URL = os.environ.get("ES_URL", "http://localhost:9200")
INDEX_NAME = "logs-app"
NUM_DOCS = 5000

SERVICES = ["auth", "billing", "checkout", "inventory", "notifications"]

# Weighted so most traffic looks healthy, like a real service's log volume. Numbers are percentages
LEVEL_WEIGHTS = {"INFO": 70, "DEBUG": 15, "WARN": 10, "ERROR": 5}

MESSAGES = {
    "INFO": [
        "request completed successfully",
        "processed {n} items in {ms}ms",
        "cache hit for key {key}",
        "user session started",
    ],
    "DEBUG": [
        "entering handler with payload size {n}",
        "cache miss for key {key}, fetching from source",
        "retrying connection, attempt {n}",
    ],
    "WARN": [
        "response time {ms}ms exceeded threshold",
        "retrying request after transient failure",
        "deprecated endpoint called",
    ],
    "ERROR": [
        "failed to connect to downstream service",
        "unhandled exception processing request",
        "database query timed out after {ms}ms",
    ],
}

STATUS_CODES_BY_LEVEL = {
    "INFO": [200, 200, 200, 201, 204],
    "DEBUG": [200, 200, 204],
    "WARN": [200, 429, 408],
    "ERROR": [500, 502, 503, 504],
}


def random_level():
    levels, weights = zip(*LEVEL_WEIGHTS.items())
    return random.choices(levels, weights=weights, k=1)[0]


def random_timestamp():
    now = datetime.now(timezone.utc)
    delta = timedelta(seconds=random.randint(0, 7 * 24 * 3600))
    return (now - delta).isoformat()


def random_message(level):
    template = random.choice(MESSAGES[level])
    return template.format(
        n=random.randint(1, 500),
        ms=random.randint(5, 3000),
        key=f"key-{random.randint(1000, 9999)}",
    )


def generate_doc():
    level = random_level()
    return {
        "timestamp": random_timestamp(),
        "level": level,
        "service": random.choice(SERVICES),
        "message": random_message(level),
        "status_code": random.choice(STATUS_CODES_BY_LEVEL[level]),
    }


def doc_stream():
    for _ in range(NUM_DOCS):
        yield {"_index": INDEX_NAME, "_source": generate_doc()}


def main():
    es = Elasticsearch(ES_URL)
    success, errors = bulk(es, doc_stream(), raise_on_error=False)
    print(f"Indexed: {success}")
    if errors:
        print(f"Errors: {len(errors)}")
        for error in errors[:5]:
            print(error)


if __name__ == "__main__":
    main()
