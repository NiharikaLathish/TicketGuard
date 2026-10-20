"""TicketGuard backend API (FastAPI). Interactive docs at /docs."""
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app import commandlog, config, detection, sync, sync_worker
from app.db import cassandra_db, neo4j_db

STATIC = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    cassandra_db.init_schema()
    neo4j_db.init_schema()
    stop = None
    if config.SYNC_INTERVAL_SECONDS > 0:
        _, stop = sync_worker.start(config.SYNC_INTERVAL_SECONDS)
    yield
    if stop:
        stop.set()


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


# ---------------------------------------------------------------- live demo page (hidden from Swagger)
@app.get("/demo", include_in_schema=False)
def demo_page():
    return FileResponse(STATIC / "demo.html")


@app.get("/commands", include_in_schema=False)
def commands(after: int = 0, limit: int = 200):
    """Recent CQL / Cypher commands the app ran, for the demo page's command log."""
    return commandlog.since(after, limit)


@app.get("/demo/graph", include_in_schema=False)
def demo_graph(ticket_id: uuid.UUID):
    return neo4j_db.ticket_graph(str(ticket_id))


@app.post("/demo/reset", include_in_schema=False)
def demo_reset():
    """Delete every transaction the demo page created (fraud_pattern 'demo') from both databases."""
    sync.run_sync()  # make sure nothing is still waiting in Cassandra
    ids = neo4j_db.demo_transaction_ids()
    for tid in ids:  # newest first, so the graph cleanup unwinds in reverse order
        if cassandra_db.delete_transaction(tid):
            neo4j_db.delete_transaction(tid)
    return {"deleted": len(ids)}


# ---------------------------------------------------------------- live feed page (hidden from Swagger)
LIVE_NS = uuid.UUID("6f1c2b7e-0b0f-4f43-9c3a-5d1f0c0a7e11")
_live_names: dict[str, str] = {}  # account / ticket id -> the name typed on the live page


class LiveTransaction(BaseModel):
    seller: str | None = None  # blank (or "platform") means the platform sells: a primary purchase
    buyer: str = Field(min_length=1)
    ticket: str = Field(min_length=1)
    face: float = Field(default=100, ge=0)
    price: float = Field(default=0, ge=0)
    type: str = Field(default="Resale", pattern="^(Purchase|Resale|Transfer)$")


def _live_id(kind: str, name: str) -> uuid.UUID:
    """The same name always gives the same id, so typing "Alice" twice means the same account."""
    return uuid.uuid5(LIVE_NS, f"{kind}:{name.strip().lower()}")


def _live_account(name: str | None) -> uuid.UUID:
    if not name or not name.strip() or name.strip().lower() == "platform":
        return uuid.UUID(config.PLATFORM_ACCOUNT_ID)
    account = _live_id("account", name)
    _live_names.setdefault(str(account), name.strip())
    return account


@app.get("/live", include_in_schema=False)
def live_page():
    return FileResponse(STATIC / "live.html")


@app.get("/live/now", include_in_schema=False)
def live_now():
    return {"now_ms": int(datetime.now(timezone.utc).timestamp() * 1000)}


@app.post("/live/transaction", status_code=201, include_in_schema=False)
def live_transaction(body: LiveTransaction):
    """Insert one transaction described with names ("Alice", "T1"). Labelled 'demo' so Start over removes it."""
    seller, buyer = _live_account(body.seller), _live_account(body.buyer)
    platform = uuid.UUID(config.PLATFORM_ACCOUNT_ID)
    if buyer == platform:
        raise HTTPException(400, "the platform cannot be the buyer")
    if buyer == seller:
        raise HTTPException(400, "buyer and seller must be different accounts")
    if body.type == "Purchase" and seller != platform:
        raise HTTPException(400, "a purchase comes from the platform: leave From blank")
    ticket = _live_id("ticket", body.ticket)
    _live_names.setdefault(str(ticket), body.ticket.strip())
    kind = "Purchase" if seller == platform else body.type
    tx = {"transaction_id": uuid.uuid4(), "event_id": _live_id("event", "live"), "ticket_id": ticket,
          "buyer_id": buyer, "seller_id": seller, "ts": datetime.now(timezone.utc),
          "purchase_price": body.face, "resale_price": 0.0 if kind == "Purchase" else body.price,
          "transaction_type": kind, "fraud_pattern": "demo"}
    return _serialise(cassandra_db.insert_transaction(tx))


@app.get("/live/graph", include_in_schema=False)
def live_graph(since_ms: int, limit: int = Query(300, le=1000)):
    """Everything sent from the live feed (kept until cleared), plus anything stored since the page opened, read back from Neo4j."""
    return {**neo4j_db.live_graph(since_ms, limit), "names": _live_names}


@app.post("/live/clear", include_in_schema=False)
def live_clear(since_ms: int):
    """Delete everything sent from the live feed, plus anything stored since the page opened, from both databases."""
    if since_ms < int(datetime.now(timezone.utc).timestamp() * 1000) - 12 * 3600 * 1000:
        raise HTTPException(400, "since_ms is too old for a live session")  # never reach into the sample data
    sync.run_sync()
    ids = neo4j_db.live_transaction_ids(since_ms)
    for tid in ids:  # newest first, so the graph cleanup unwinds in reverse order
        if cassandra_db.delete_transaction(tid):
            neo4j_db.delete_transaction(tid)
    return {"deleted": len(ids)}


@app.middleware("http")
async def log_incoming_writes(request, call_next):
    """Show data changes sent from Swagger, the console or curl in the demo command log.

    Calls made by the demo and live pages are skipped: they print their own, more detailed, lines.
    """
    path = request.url.path
    if request.method in ("POST", "PUT", "DELETE") and not path.startswith(("/live", "/demo", "/commands")):
        ref = urlparse(request.headers.get("referer", "")).path
        if not ref.startswith(("/demo", "/live")):
            source = "Swagger" if ref.startswith("/docs") else "the console" if ref == "/" else "a direct call"
            query = f"?{request.url.query}" if request.url.query else ""
            commandlog.record("api", f"{request.method} {path}{query}   (from {source})")
    return await call_next(request)
