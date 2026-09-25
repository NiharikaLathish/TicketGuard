"""Cassandra -> Neo4j synchronisation.

Incremental: a watermark (max transaction timestamp already synced) is stored in Neo4j.
Each run reads the Cassandra day-partitions from the watermark's day onwards and keeps rows
newer than the watermark. Graph writes are MERGE-based, so re-running is idempotent.
"""
import time
from datetime import datetime, timezone

from app.db import cassandra_db, neo4j_db

BATCH = 2000


def run_sync(full: bool = False) -> dict:
    t0 = time.time()
    watermark_ms = 0 if full else neo4j_db.get_watermark()
    days = cassandra_db.distinct_days()
    if not days:
        return {"synced": 0, "watermark": watermark_ms, "seconds": 0.0}
    start = datetime.fromtimestamp(watermark_ms / 1000, tz=timezone.utc) if watermark_ms else \
        datetime.strptime(days[0], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end = datetime.strptime(days[-1], "%Y-%m-%d").replace(tzinfo=timezone.utc)

    synced, max_ms, buf = 0, watermark_ms, []
    for tx in cassandra_db.list_day_range(start, end):
        ms = int(tx["ts"].timestamp() * 1000)
        if ms <= watermark_ms and not full:
            continue
        buf.append(tx)
        max_ms = max(max_ms, ms)
        if len(buf) >= BATCH:
            synced += neo4j_db.upsert_transactions(buf)
            buf = []
    synced += neo4j_db.upsert_transactions(buf)
    neo4j_db.set_watermark(max_ms)
    return {"synced": synced, "watermark": max_ms, "seconds": round(time.time() - t0, 2)}
