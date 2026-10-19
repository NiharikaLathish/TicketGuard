"""Tests for the live demo page: the command log, the demo endpoints and the demo reset.

The first group needs no database. The second group needs both databases running (like the other tests).
"""
import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app import commandlog, config, sync
from app.db import cassandra_db, neo4j_db
from app.main import app


# ------------------------------------------------------------------ no database needed
def test_commandlog_returns_only_newer_entries_and_honours_limit():
    start = commandlog.since(0, 0)["last_id"]
    commandlog.record("sync", "first")
    commandlog.record("neo4j", "second")
    out = commandlog.since(start)
    assert [c["text"] for c in out["commands"]] == ["first", "second"]
    assert out["last_id"] == start + 2
    assert [c["text"] for c in commandlog.since(start, 1)["commands"]] == ["second"]
    assert commandlog.since(start, 0)["commands"] == []


def test_logged_cql_and_cypher_are_readable_statements():
    cql = cassandra_db._fill("UPDATE t SET resale_price=? WHERE ticket_id=? AND day=?;",
                             [Decimal("999"), uuid.UUID(int=1), "2026-09-10"])
    assert cql == "UPDATE t SET resale_price=999 WHERE ticket_id=00000000-0000-0000-0000-000000000001 AND day='2026-09-10';"
    row = {"buyer_id": "B", "seller_id": "S", "ticket_id": "T", "event_id": "E", "transaction_id": "X",
           "transaction_type": "Resale", "resale_price": 105.0}
    cypher = neo4j_db._cypher_for_row(row)
    assert "MERGE (b:Account {account_id: 'B'})" in cypher
    assert "TRANSFERRED_TO {tx_id: 'X', ticket_id: 'T', price: 105.0}" in cypher
    row["seller_id"] = config.PLATFORM_ACCOUNT_ID  # a primary purchase has no transfer between accounts
    assert "TRANSFERRED_TO" not in neo4j_db._cypher_for_row(row)


def test_demo_endpoints_work_with_a_stubbed_database(monkeypatch):
    client = TestClient(app)  # not used as a context manager, so no database connection is opened
    assert client.get("/demo").status_code == 200
    assert "Watch a command become a graph" in client.get("/demo").text

    ticket = str(uuid.uuid4())
    monkeypatch.setattr(neo4j_db, "run", lambda q, **p: [
        {"type": "Purchase", "seller": None, "buyer": "A", "face": 100.0, "price": 0.0, "ts": 1},
        {"type": "Resale", "seller": "A", "buyer": "B", "face": 100.0, "price": 105.0, "ts": 2}])
    start = client.get("/commands", params={"limit": 0}).json()["last_id"]
    g = client.get("/demo/graph", params={"ticket_id": ticket}).json()
    assert g["transfers"][0]["seller"] == g["platform"] == config.PLATFORM_ACCOUNT_ID  # missing seller means the platform
    assert g["transfers"][1]["seller"] == "A"
    cmds = client.get("/commands", params={"after": start}).json()["commands"]
    assert cmds and cmds[0]["store"] == "neo4j" and ticket in cmds[0]["text"]

    deleted = []
    monkeypatch.setattr(sync, "run_sync", lambda *a, **k: {"synced": 0})
    monkeypatch.setattr(neo4j_db, "demo_transaction_ids", lambda: ["newest", "oldest"])
    monkeypatch.setattr(cassandra_db, "delete_transaction", lambda t: deleted.append(("cassandra", t)) or True)
    monkeypatch.setattr(neo4j_db, "delete_transaction", lambda t: deleted.append(("neo4j", t)))
    assert client.post("/demo/reset").json() == {"deleted": 2}
    assert deleted == [("cassandra", "newest"), ("neo4j", "newest"), ("cassandra", "oldest"), ("neo4j", "oldest")]


def test_demo_endpoints_are_hidden_from_the_api_docs():
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    assert not {"/demo", "/commands", "/demo/graph", "/demo/reset"} & set(paths)


# ------------------------------------------------------------------ needs both databases running
@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _body(**over):
    body = {"event_id": str(uuid.uuid4()), "ticket_id": str(uuid.uuid4()), "buyer_id": str(uuid.uuid4()),
            "seller_id": config.PLATFORM_ACCOUNT_ID, "purchase_price": 100, "resale_price": 0,
            "transaction_type": "Purchase", "fraud_pattern": "demo"}
    body.update(over)
    return body


def test_command_log_shows_the_real_cql_and_cypher(client):
    start = client.get("/commands", params={"limit": 0}).json()["last_id"]
    try:
        assert client.post("/transactions", json=_body()).status_code == 201
        client.post("/sync")
        cmds = client.get("/commands", params={"after": start}).json()["commands"]
        cql = [c["text"] for c in cmds if c["store"] == "cassandra"]
        assert len(cql) == 4  # one write, four query tables
        assert {t.split()[2] for t in cql} == {"transactions_by_id", "transactions_by_buyer",
                                               "transactions_by_ticket", "transactions_by_day"}
        assert any(c["store"] == "neo4j" and "MERGE" in c["text"] for c in cmds)
        assert any(c["store"] == "sync" for c in cmds)
    finally:
        client.post("/demo/reset")


def test_demo_ticket_graph_then_reset_restores_the_databases(client):
    client.post("/demo/reset")
    before = client.get("/stats").json()
    ticket, event, alice, bob = (str(uuid.uuid4()) for _ in range(4))
    try:
        client.post("/transactions", json=_body(ticket_id=ticket, event_id=event, buyer_id=alice))
        client.post("/transactions", json=_body(ticket_id=ticket, event_id=event, buyer_id=bob, seller_id=alice,
                                                resale_price=105, transaction_type="Resale"))
        client.post("/sync")
        g = client.get("/demo/graph", params={"ticket_id": ticket}).json()
        assert [t["type"] for t in g["transfers"]] == ["Purchase", "Resale"]
        assert g["transfers"][0]["seller"] == g["platform"]
        assert (g["transfers"][1]["seller"], g["transfers"][1]["buyer"]) == (alice, bob)
    finally:
        reset = client.post("/demo/reset").json()
    assert reset["deleted"] >= 2
    assert client.get("/stats").json() == before  # no leftover accounts, tickets or events
