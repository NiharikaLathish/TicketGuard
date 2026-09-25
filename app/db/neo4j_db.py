"""Neo4j layer: constraints/indexes, graph upserts, and CRUD for accounts/tickets/events.

Graph model
  (:Account {account_id, name, is_platform})
  (:Ticket  {ticket_id, event_id})
  (:Event   {event_id, name})
  (:Transaction {transaction_id, ts, purchase_price, resale_price, transaction_type, fraud_pattern})

  (Account)-[:PURCHASED]->(Ticket)            buyer bought ticket
  (Account)-[:SOLD]->(Ticket)                 seller sold ticket
  (Account)-[:TRANSFERRED_TO {ticket_id, tx_id, ts, price}]->(Account)   ticket changed hands
  (Transaction)-[:INVOLVES]->(Ticket)
  (Transaction)-[:MADE_BY]->(Account)         the buyer
  (Ticket)-[:BELONGS_TO]->(Event)
"""
from neo4j import GraphDatabase

from app import config

_driver = None


def get_driver():
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(config.NEO4J_URI, auth=(config.NEO4J_USER, config.NEO4J_PASSWORD),
                                      notifications_min_severity="OFF")
    return _driver


def run(cypher: str, **params) -> list[dict]:
    with get_driver().session() as s:
        return [r.data() for r in s.run(cypher, **params)]


SCHEMA = [
    "CREATE CONSTRAINT account_id IF NOT EXISTS FOR (a:Account) REQUIRE a.account_id IS UNIQUE",
    "CREATE CONSTRAINT ticket_id IF NOT EXISTS FOR (t:Ticket) REQUIRE t.ticket_id IS UNIQUE",
    "CREATE CONSTRAINT event_id IF NOT EXISTS FOR (e:Event) REQUIRE e.event_id IS UNIQUE",
    "CREATE CONSTRAINT tx_id IF NOT EXISTS FOR (x:Transaction) REQUIRE x.transaction_id IS UNIQUE",
    "CREATE INDEX tx_ts IF NOT EXISTS FOR (x:Transaction) ON (x.ts)",
    "CREATE INDEX tx_fraud IF NOT EXISTS FOR (x:Transaction) ON (x.fraud_pattern)",
    "CREATE INDEX transfer_ticket IF NOT EXISTS FOR ()-[r:TRANSFERRED_TO]-() ON (r.ticket_id)",
]


def init_schema():
    for stmt in SCHEMA:
        run(stmt)


# ---------------------------------------------------------------- sync upsert
UPSERT_TX = """
UNWIND $rows AS row
MERGE (b:Account {account_id: row.buyer_id})
MERGE (s:Account {account_id: row.seller_id})
MERGE (t:Ticket {ticket_id: row.ticket_id})
MERGE (e:Event {event_id: row.event_id})
MERGE (t)-[:BELONGS_TO]->(e)
SET t.event_id = row.event_id,
    s.is_platform = (row.seller_id = $platform), b.is_platform = coalesce(b.is_platform, false)
MERGE (x:Transaction {transaction_id: row.transaction_id})
SET x.ts = row.ts_ms, x.purchase_price = row.purchase_price, x.resale_price = row.resale_price,
    x.transaction_type = row.transaction_type, x.fraud_pattern = row.fraud_pattern
MERGE (x)-[:INVOLVES]->(t)
MERGE (x)-[:MADE_BY]->(b)
MERGE (b)-[:PURCHASED]->(t)
MERGE (s)-[:SOLD]->(t)
FOREACH (_ IN CASE WHEN row.seller_id <> $platform THEN [1] ELSE [] END |
    MERGE (s)-[r:TRANSFERRED_TO {tx_id: row.transaction_id}]->(b)
    SET r.ticket_id = row.ticket_id, r.ts = row.ts_ms, r.price = row.resale_price)
"""


def upsert_transactions(rows: list[dict]) -> int:
    """Idempotent MERGE of a batch of transactions (dicts from cassandra_db) into the graph."""
    if not rows:
        return 0
    payload = [{
        "transaction_id": r["transaction_id"], "event_id": r["event_id"], "ticket_id": r["ticket_id"],
        "buyer_id": r["buyer_id"], "seller_id": r["seller_id"],
        "ts_ms": int(r["ts"].timestamp() * 1000),
        "purchase_price": float(r["purchase_price"]), "resale_price": float(r["resale_price"]),
        "transaction_type": r["transaction_type"], "fraud_pattern": r["fraud_pattern"],
    } for r in rows]
    run(UPSERT_TX, rows=payload, platform=config.PLATFORM_ACCOUNT_ID)
    return len(rows)


def delete_transaction(tx_id: str):
    """Remove a transaction from the graph, plus any edges/nodes that only it justified."""
    info = run("""MATCH (x:Transaction {transaction_id:$id})-[:INVOLVES]->(t:Ticket), (x)-[:MADE_BY]->(b:Account)
                  OPTIONAL MATCH (s:Account)-[:TRANSFERRED_TO {tx_id:$id}]->(b)
                  RETURN t.ticket_id AS t, b.account_id AS b, s.account_id AS s""", id=tx_id)
    run("MATCH (x:Transaction {transaction_id:$id}) DETACH DELETE x", id=tx_id)
    run("MATCH ()-[r:TRANSFERRED_TO {tx_id:$id}]->() DELETE r", id=tx_id)
    if not info:
        return
    t, b, s = info[0]["t"], info[0]["b"], info[0]["s"] or config.PLATFORM_ACCOUNT_ID
    run("""MATCH (b:Account {account_id:$b})-[p:PURCHASED]->(t:Ticket {ticket_id:$t})
           WHERE NOT EXISTS { MATCH (x:Transaction)-[:MADE_BY]->(b) WHERE (x)-[:INVOLVES]->(t) }
           DELETE p""", b=b, t=t)
    run("""MATCH (s:Account {account_id:$s})-[o:SOLD]->(t:Ticket {ticket_id:$t})
           WHERE NOT EXISTS { MATCH (s)-[:TRANSFERRED_TO {ticket_id:$t}]->() }
             AND NOT EXISTS { MATCH (x:Transaction {transaction_type:'Purchase'})-[:INVOLVES]->(t) WHERE s.is_platform }
           DELETE o""", s=s, t=t)
    run("""MATCH (t:Ticket {ticket_id:$t}) WHERE NOT EXISTS { MATCH (:Transaction)-[:INVOLVES]->(t) }
           DETACH DELETE t""", t=t)
    run("MATCH (e:Event) WHERE NOT EXISTS { MATCH (e)<-[:BELONGS_TO]-() } DETACH DELETE e")
    run("""MATCH (a:Account) WHERE a.account_id IN [$b, $s] AND NOT coalesce(a.is_platform, false)
             AND a.name IS NULL
             AND NOT EXISTS { MATCH (:Transaction)-[:MADE_BY]->(a) }
             AND NOT EXISTS { MATCH (a)-[:TRANSFERRED_TO]-() }
             AND NOT EXISTS { MATCH (a)-[:PURCHASED|SOLD]->(:Ticket) }
           DETACH DELETE a""", b=b, s=s)


# ---------------------------------------------------------------- sync state
def get_watermark() -> int:
    r = run("MATCH (s:SyncState {name:'cassandra'}) RETURN s.last_ts AS ts")
    return r[0]["ts"] if r else 0


def set_watermark(ts_ms: int):
    run("MERGE (s:SyncState {name:'cassandra'}) SET s.last_ts = $ts, s.updated = timestamp()", ts=ts_ms)


# ---------------------------------------------------------------- Account CRUD
def create_account(account_id: str, name: str) -> dict:
    return run("""MERGE (a:Account {account_id:$id}) ON CREATE SET a.created = true
                  SET a.name=$name, a.is_platform = coalesce(a.is_platform, false)
                  RETURN properties(a) AS account""", id=account_id, name=name)[0]["account"]


def get_account(account_id: str) -> dict | None:
    r = run("""MATCH (a:Account {account_id:$id})
               OPTIONAL MATCH (a)-[out:TRANSFERRED_TO]->()
               OPTIONAL MATCH ()-[inn:TRANSFERRED_TO]->(a)
               RETURN properties(a) AS account, count(DISTINCT out) AS sold_to_count,
                      count(DISTINCT inn) AS bought_from_count""", id=account_id)
    return {**r[0]["account"], "transfers_out": r[0]["sold_to_count"], "transfers_in": r[0]["bought_from_count"]} if r else None


def list_accounts(limit: int = 50, skip: int = 0) -> list[dict]:
    return [r["a"] for r in run(
        "MATCH (a:Account) RETURN properties(a) AS a ORDER BY a.account_id SKIP $skip LIMIT $limit",
        skip=skip, limit=limit)]


def update_account(account_id: str, changes: dict) -> dict | None:
    changes = {k: v for k, v in changes.items() if k in ("name", "flagged", "notes") and v is not None}
    r = run("MATCH (a:Account {account_id:$id}) SET a += $ch RETURN properties(a) AS a", id=account_id, ch=changes)
    return r[0]["a"] if r else None


def delete_account(account_id: str) -> bool:
    r = run("MATCH (a:Account {account_id:$id}) DETACH DELETE a RETURN count(*) AS n", id=account_id)
    return bool(r and r[0]["n"])


# ---------------------------------------------------------------- Ticket
def ticket_history(ticket_id: str) -> dict | None:
    r = run("""MATCH (t:Ticket {ticket_id:$id})
               OPTIONAL MATCH (t)-[:BELONGS_TO]->(e:Event)
               OPTIONAL MATCH (s:Account)-[r:TRANSFERRED_TO {ticket_id:$id}]->(b:Account)
               WITH t, e, s, r, b ORDER BY r.ts
               RETURN t.ticket_id AS ticket_id, e.event_id AS event_id,
                      [x IN collect({from: s.account_id, to: b.account_id, ts: r.ts, price: r.price})
                       WHERE x.from IS NOT NULL] AS transfers""", id=ticket_id)
    return r[0] if r else None


def stats() -> dict:
    r = run("""MATCH (a:Account) WITH count(a) AS accounts
               MATCH (t:Ticket) WITH accounts, count(t) AS tickets
               MATCH (x:Transaction) WITH accounts, tickets, count(x) AS transactions
               MATCH ()-[r:TRANSFERRED_TO]->() RETURN accounts, tickets, transactions, count(r) AS transfers""")
    return r[0] if r else {"accounts": 0, "tickets": 0, "transactions": 0, "transfers": 0}


def clear_graph():
    while run("MATCH (n) WITH n LIMIT 10000 DETACH DELETE n RETURN count(*) AS c")[0]["c"] > 0:
        pass
