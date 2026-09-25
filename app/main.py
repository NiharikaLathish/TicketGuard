"""TicketGuard backend API (FastAPI). Interactive docs at /docs."""
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app import config, detection, sync
from app.db import cassandra_db, neo4j_db

STATIC = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    cassandra_db.init_schema()
    neo4j_db.init_schema()
    yield


app = FastAPI(title="TicketGuard API", version="0.2.0", lifespan=lifespan,
              description="Ticket fraud detection over Cassandra (transactions) and Neo4j (graph analysis).")


# ---------------------------------------------------------------- models
class TransactionIn(BaseModel):
    event_id: uuid.UUID
    ticket_id: uuid.UUID
    buyer_id: uuid.UUID
    seller_id: uuid.UUID
    purchase_price: float = Field(ge=0)
    resale_price: float = Field(default=0, ge=0)
    transaction_type: str = Field(pattern="^(Purchase|Resale|Transfer)$")
    fraud_pattern: str = "none"
    ts: datetime | None = None


class TransactionUpdate(BaseModel):
    purchase_price: float | None = Field(default=None, ge=0)
    resale_price: float | None = Field(default=None, ge=0)
    transaction_type: str | None = Field(default=None, pattern="^(Purchase|Resale|Transfer)$")
    fraud_pattern: str | None = None


class AccountIn(BaseModel):
    account_id: uuid.UUID | None = None
    name: str


class AccountUpdate(BaseModel):
    name: str | None = None
    flagged: bool | None = None
    notes: str | None = None


def _serialise(tx: dict) -> dict:
    return {**tx, "ts": tx["ts"].isoformat(), "purchase_price": float(tx["purchase_price"]),
            "resale_price": float(tx["resale_price"])}


# ---------------------------------------------------------------- health
@app.get("/health", tags=["system"])
def health():
    out = {"cassandra": "down", "neo4j": "down"}
    try:
        cassandra_db.get_session().execute("SELECT release_version FROM system.local")
        out["cassandra"] = "up"
    except Exception as e:
        out["cassandra_error"] = str(e)[:120]
    try:
        neo4j_db.run("RETURN 1")
        out["neo4j"] = "up"
    except Exception as e:
        out["neo4j_error"] = str(e)[:120]
    return out


@app.get("/stats", tags=["system"])
def stats():
    return {"cassandra_transactions": cassandra_db.count_all(), "neo4j": neo4j_db.stats()}


# ---------------------------------------------------------------- transactions (Cassandra CRUD)
@app.post("/transactions", status_code=201, tags=["transactions (Cassandra)"])
def create_transaction(body: TransactionIn):
    tx = body.model_dump()
    tx["transaction_id"] = uuid.uuid4()
    tx["ts"] = body.ts or datetime.now(timezone.utc)
    return _serialise(cassandra_db.insert_transaction(tx))


@app.get("/transactions/{transaction_id}", tags=["transactions (Cassandra)"])
def get_transaction(transaction_id: uuid.UUID):
    tx = cassandra_db.get_transaction(transaction_id)
    if not tx:
        raise HTTPException(404, "transaction not found")
    return _serialise(tx)


@app.get("/transactions", tags=["transactions (Cassandra)"],
         description="Query by exactly one of: buyer_id, ticket_id, or day (YYYY-MM-DD).")
def list_transactions(buyer_id: uuid.UUID | None = None, ticket_id: uuid.UUID | None = None,
                      day: str | None = None, limit: int = Query(50, le=1000)):
    given = [x for x in (buyer_id, ticket_id, day) if x]
    if len(given) != 1:
        raise HTTPException(400, "provide exactly one of buyer_id, ticket_id, day")
    if buyer_id:
        rows = cassandra_db.list_by_buyer(buyer_id, limit)
    elif ticket_id:
        rows = cassandra_db.list_by_ticket(ticket_id, limit)
    else:
        rows = cassandra_db.list_by_day(day, limit)
    return [_serialise(r) for r in rows]


@app.put("/transactions/{transaction_id}", tags=["transactions (Cassandra)"])
def update_transaction(transaction_id: uuid.UUID, body: TransactionUpdate):
    tx = cassandra_db.update_transaction(transaction_id, body.model_dump(exclude_none=True))
    if not tx:
        raise HTTPException(404, "transaction not found")
    neo4j_db.upsert_transactions([tx])  # keep graph consistent
    return _serialise(tx)


@app.delete("/transactions/{transaction_id}", status_code=204, tags=["transactions (Cassandra)"])
def delete_transaction(transaction_id: uuid.UUID):
    if not cassandra_db.delete_transaction(transaction_id):
        raise HTTPException(404, "transaction not found")
    neo4j_db.delete_transaction(str(transaction_id))


# ---------------------------------------------------------------- accounts & tickets (Neo4j CRUD)
@app.post("/accounts", status_code=201, tags=["graph (Neo4j)"])
def create_account(body: AccountIn):
    return neo4j_db.create_account(str(body.account_id or uuid.uuid4()), body.name)


@app.get("/accounts", tags=["graph (Neo4j)"])
def list_accounts(limit: int = Query(50, le=1000), skip: int = 0):
    return neo4j_db.list_accounts(limit, skip)


@app.get("/accounts/{account_id}", tags=["graph (Neo4j)"])
def get_account(account_id: uuid.UUID):
    a = neo4j_db.get_account(str(account_id))
    if not a:
        raise HTTPException(404, "account not found")
    return a


@app.put("/accounts/{account_id}", tags=["graph (Neo4j)"])
def update_account(account_id: uuid.UUID, body: AccountUpdate):
    a = neo4j_db.update_account(str(account_id), body.model_dump(exclude_none=True))
    if not a:
        raise HTTPException(404, "account not found")
    return a


@app.delete("/accounts/{account_id}", status_code=204, tags=["graph (Neo4j)"])
def delete_account(account_id: uuid.UUID):
    if not neo4j_db.delete_account(str(account_id)):
        raise HTTPException(404, "account not found")


@app.get("/tickets/{ticket_id}/history", tags=["graph (Neo4j)"])
def ticket_history(ticket_id: uuid.UUID):
    h = neo4j_db.ticket_history(str(ticket_id))
    if not h:
        raise HTTPException(404, "ticket not found in graph (run /sync?)")
    return h


# ---------------------------------------------------------------- sync
@app.post("/sync", tags=["sync"], description="Copy new Cassandra transactions into Neo4j. full=true re-syncs everything.")
def run_sync(full: bool = False):
    return sync.run_sync(full)


# ---------------------------------------------------------------- fraud detection
@app.get("/fraud/summary", tags=["fraud detection"])
def fraud_summary():
    return detection.summary()


@app.get("/fraud/cycles", tags=["fraud detection"])
def fraud_cycles(min_len: int = Query(2, ge=2, le=6), max_len: int = Query(6, ge=2, le=8)):
    return detection.detect_cycles(min_len, max_len)


@app.get("/fraud/communities", tags=["fraud detection"])
def fraud_communities(min_size: int = 5, min_avg_degree: float = 1.8):
    return detection.detect_communities(min_size, min_avg_degree)


@app.get("/fraud/hubs", tags=["fraud detection"])
def fraud_hubs(z_threshold: float = 4.0, min_degree: int = 20):
    return detection.detect_hubs(z_threshold, min_degree)


@app.get("/fraud/pricing", tags=["fraud detection"])
def fraud_pricing(ratio: float = 2.0, limit: int = Query(500, le=5000)):
    return detection.detect_pricing(ratio, limit)


@app.get("/fraud/graph", tags=["fraud detection"], description="Nodes/edges for the visualisation page.")
def fraud_graph(pattern: str = Query("all", pattern="^(all|circular_resale|bot_ring|hub_account)$")):
    return detection.visual_graph(pattern)


# ---------------------------------------------------------------- visualisation
@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")
