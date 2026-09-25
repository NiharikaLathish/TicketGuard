"""Cassandra layer: schema + CRUD.

Cassandra tables are modelled per query (one table per access path), all
sharing the same columns. Every write goes to all four tables.

  transactions_by_id      PK (transaction_id)                       -> point lookup / update / delete
  transactions_by_buyer   PK ((buyer_id), ts DESC, transaction_id)  -> an account's purchase history
  transactions_by_ticket  PK ((ticket_id), ts DESC, transaction_id) -> a ticket's ownership chain
  transactions_by_day     PK ((day), ts, transaction_id)            -> time-window scans (used by sync)
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from cassandra.cluster import Cluster
from cassandra.concurrent import execute_concurrent_with_args
from cassandra.query import BatchStatement, BatchType

from app import config

COLUMNS = ["transaction_id", "event_id", "ticket_id", "buyer_id", "seller_id",
           "ts", "purchase_price", "resale_price", "transaction_type", "fraud_pattern"]
COL_LIST = ", ".join(COLUMNS)
PLACEHOLDERS = ", ".join("?" for _ in COLUMNS)

_COLS_DDL = """
    transaction_id uuid, event_id uuid, ticket_id uuid, buyer_id uuid, seller_id uuid,
    ts timestamp, purchase_price decimal, resale_price decimal,
    transaction_type text, fraud_pattern text, day text"""

KEYSPACE_DDL = (f"CREATE KEYSPACE IF NOT EXISTS {config.CASSANDRA_KEYSPACE} "
                "WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1}")
TABLE_DDL = [
    f"CREATE TABLE IF NOT EXISTS transactions_by_id ({_COLS_DDL}, PRIMARY KEY (transaction_id))",
    f"""CREATE TABLE IF NOT EXISTS transactions_by_buyer ({_COLS_DDL},
        PRIMARY KEY ((buyer_id), ts, transaction_id))
        WITH CLUSTERING ORDER BY (ts DESC, transaction_id ASC)""",
    f"""CREATE TABLE IF NOT EXISTS transactions_by_ticket ({_COLS_DDL},
        PRIMARY KEY ((ticket_id), ts, transaction_id))
        WITH CLUSTERING ORDER BY (ts DESC, transaction_id ASC)""",
    f"""CREATE TABLE IF NOT EXISTS transactions_by_day ({_COLS_DDL},
        PRIMARY KEY ((day), ts, transaction_id))
        WITH CLUSTERING ORDER BY (ts ASC, transaction_id ASC)""",
]
TABLES = ["transactions_by_id", "transactions_by_buyer", "transactions_by_ticket", "transactions_by_day"]

_cluster = None
_session = None
_prepared: dict = {}


def get_session():
    global _cluster, _session
    if _session is None:
        _cluster = Cluster(config.CASSANDRA_HOSTS, port=config.CASSANDRA_PORT)
        _session = _cluster.connect()
    if _session.keyspace != config.CASSANDRA_KEYSPACE:
        try:
            _session.set_keyspace(config.CASSANDRA_KEYSPACE)
        except Exception:
            pass  # keyspace not created yet (init_schema will create it)
    return _session


def init_schema():
    s = get_session()
    s.execute(KEYSPACE_DDL)
    s.set_keyspace(config.CASSANDRA_KEYSPACE)
    for ddl in TABLE_DDL:
        s.execute(ddl)


def _prep(key: str, cql: str):
    if key not in _prepared:
        _prepared[key] = get_session().prepare(cql)
    return _prepared[key]


def day_of(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%d")


def _to_uuid(v):
    return v if isinstance(v, uuid.UUID) else uuid.UUID(str(v))


def _utc(ts: datetime) -> datetime:
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts


def _row_to_dict(r) -> dict:
    d = {c: getattr(r, c) for c in COLUMNS}
    for k in ("transaction_id", "event_id", "ticket_id", "buyer_id", "seller_id"):
        d[k] = str(d[k])
    d["ts"] = _utc(d["ts"])
    return d


def _values(tx: dict) -> list:
    ts = _utc(tx["ts"])
    return [_to_uuid(tx["transaction_id"]), _to_uuid(tx["event_id"]), _to_uuid(tx["ticket_id"]),
            _to_uuid(tx["buyer_id"]), _to_uuid(tx["seller_id"]), ts,
            Decimal(str(tx["purchase_price"])), Decimal(str(tx["resale_price"])),
            tx["transaction_type"], tx.get("fraud_pattern") or "none", day_of(ts)]


def _insert_stmt(table: str):
    return _prep(f"ins_{table}", f"INSERT INTO {table} ({COL_LIST}, day) VALUES ({PLACEHOLDERS}, ?)")


# ---------------------------------------------------------------- CREATE
def insert_transaction(tx: dict) -> dict:
    """Write one transaction to all four query tables atomically (logged batch)."""
    vals = _values(tx)
    batch = BatchStatement(batch_type=BatchType.LOGGED)
    for t in TABLES:
        batch.add(_insert_stmt(t), vals)
    get_session().execute(batch)
    return get_transaction(vals[0])


def bulk_insert(transactions, concurrency: int = 64) -> int:
    """High-throughput ingestion: concurrent async writes (idempotent by primary key)."""
    s = get_session()
    rows = [_values(t) for t in transactions]
    for t in TABLES:
        results = execute_concurrent_with_args(s, _insert_stmt(t), rows, concurrency=concurrency,
                                               raise_on_first_error=False)
        for ok, res in results:
            if not ok:
                raise res
    return len(rows)


# ---------------------------------------------------------------- READ
def get_transaction(tx_id) -> dict | None:
    r = get_session().execute(
        _prep("get_id", f"SELECT {COL_LIST} FROM transactions_by_id WHERE transaction_id=?"),
        [_to_uuid(tx_id)]).one()
    return _row_to_dict(r) if r else None


def list_by_buyer(buyer_id, limit: int = 50) -> list[dict]:
    rows = get_session().execute(
        _prep("by_buyer", f"SELECT {COL_LIST} FROM transactions_by_buyer WHERE buyer_id=? LIMIT ?"),
        [_to_uuid(buyer_id), limit])
    return [_row_to_dict(r) for r in rows]


def list_by_ticket(ticket_id, limit: int = 50) -> list[dict]:
    rows = get_session().execute(
        _prep("by_ticket", f"SELECT {COL_LIST} FROM transactions_by_ticket WHERE ticket_id=? LIMIT ?"),
        [_to_uuid(ticket_id), limit])
    return [_row_to_dict(r) for r in rows]


def list_by_day(day: str, limit: int = 100000) -> list[dict]:
    rows = get_session().execute(
        _prep("by_day", f"SELECT {COL_LIST} FROM transactions_by_day WHERE day=? LIMIT ?"), [day, limit])
    return [_row_to_dict(r) for r in rows]


def list_day_range(start: datetime, end: datetime):
    """Yield every transaction in the day-partitions covering [start, end]."""
    d = _utc(start).replace(hour=0, minute=0, second=0, microsecond=0)
    end = _utc(end)
    while d <= end:
        yield from list_by_day(day_of(d))
        d += timedelta(days=1)


def distinct_days() -> list[str]:
    rows = get_session().execute("SELECT DISTINCT day FROM transactions_by_day")
    return sorted(r.day for r in rows)


def count_all() -> int:
    return get_session().execute("SELECT COUNT(*) FROM transactions_by_id", timeout=120).one()[0]


# ---------------------------------------------------------------- UPDATE
_MUTABLE = ("purchase_price", "resale_price", "transaction_type", "fraud_pattern")


def _key_clauses(cur: dict):
    tid, ts = _to_uuid(cur["transaction_id"]), cur["ts"]
    return {
        "transactions_by_id": ("transaction_id=?", [tid]),
        "transactions_by_buyer": ("buyer_id=? AND ts=? AND transaction_id=?", [_to_uuid(cur["buyer_id"]), ts, tid]),
        "transactions_by_ticket": ("ticket_id=? AND ts=? AND transaction_id=?", [_to_uuid(cur["ticket_id"]), ts, tid]),
        "transactions_by_day": ("day=? AND ts=? AND transaction_id=?", [day_of(ts), ts, tid]),
    }


def update_transaction(tx_id, changes: dict) -> dict | None:
    """Update mutable columns in every table. Key columns (ids, ts) are immutable."""
    current = get_transaction(tx_id)
    if not current:
        return None
    allowed = {k: v for k, v in changes.items() if k in _MUTABLE and v is not None}
    if not allowed:
        return current
    sets = ", ".join(f"{k}=?" for k in allowed)
    vals = [Decimal(str(v)) if k.endswith("price") else v for k, v in allowed.items()]
    batch = BatchStatement(batch_type=BatchType.LOGGED)
    for table, (where, kv) in _key_clauses(current).items():
        batch.add(_prep(f"upd_{table}_{sets}", f"UPDATE {table} SET {sets} WHERE {where}"), vals + kv)
    get_session().execute(batch)
    return get_transaction(tx_id)


# ---------------------------------------------------------------- DELETE
def delete_transaction(tx_id) -> bool:
    current = get_transaction(tx_id)
    if not current:
        return False
    batch = BatchStatement(batch_type=BatchType.LOGGED)
    for table, (where, kv) in _key_clauses(current).items():
        batch.add(_prep(f"del_{table}", f"DELETE FROM {table} WHERE {where}"), kv)
    get_session().execute(batch)
    return True


def truncate_all():
    s = get_session()
    for t in TABLES:
        s.execute(f"TRUNCATE {t}")
