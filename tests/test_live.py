"""Tests for the live feed page: name-based input, the session clear guard, the incoming-write log and the end-to-end flow.

The first group needs no database. The last test needs both databases running (like the other tests).
"""
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from app import commandlog, config
from app.db import cassandra_db
from app.main import app


# ------------------------------------------------------------------ no database needed
def test_live_transaction_turns_names_into_stable_ids(monkeypatch):
    saved = []
    monkeypatch.setattr(cassandra_db, "insert_transaction", lambda tx: saved.append(tx) or {
        **tx, "transaction_id": str(tx["transaction_id"]), "ts": tx["ts"]})
    client = TestClient(app)
    body = {"seller": "Alice", "buyer": "Bob", "ticket": "T1", "face": 100, "price": 105, "type": "Resale"}
    assert client.post("/live/transaction", json=body).status_code == 201
    assert client.post("/live/transaction", json={**body, "seller": "  alice ", "buyer": "BOB"}).status_code == 201
    first, second = saved
    assert (first["seller_id"], first["buyer_id"], first["ticket_id"]) == (second["seller_id"], second["buyer_id"], second["ticket_id"])
    assert first["transaction_id"] != second["transaction_id"] and first["fraud_pattern"] == "demo"
    assert str(first["seller_id"]) != str(first["buyer_id"])


def test_live_transaction_blank_seller_is_a_platform_purchase_and_bad_input_is_refused(monkeypatch):
    saved = []
    monkeypatch.setattr(cassandra_db, "insert_transaction", lambda tx: saved.append(tx) or {
        **tx, "transaction_id": str(tx["transaction_id"]), "ts": tx["ts"]})
    client = TestClient(app)
    ok = client.post("/live/transaction", json={"seller": "", "buyer": "Alice", "ticket": "T1", "price": 55, "type": "Resale"})
    assert ok.status_code == 201
    assert str(saved[0]["seller_id"]) == config.PLATFORM_ACCOUNT_ID
    assert saved[0]["transaction_type"] == "Purchase" and saved[0]["resale_price"] == 0
    assert client.post("/live/transaction", json={"seller": "Alice", "buyer": "alice", "ticket": "T1"}).status_code == 400
    assert client.post("/live/transaction", json={"seller": "Alice", "buyer": "platform", "ticket": "T1"}).status_code == 400
    assert client.post("/live/transaction", json={"seller": "Alice", "buyer": "Bob", "ticket": "T1", "type": "Purchase"}).status_code == 400
    assert client.post("/live/transaction", json={"seller": "Alice", "buyer": "", "ticket": "T1"}).status_code == 422
    assert len(saved) == 1  # nothing invalid reached Cassandra


def test_live_clear_refuses_to_reach_back_into_the_sample_data():
    client = TestClient(app)
    assert client.post("/live/clear", params={"since_ms": 0}).status_code == 400
    old = int((time.time() - 3 * 24 * 3600) * 1000)
    assert client.post("/live/clear", params={"since_ms": old}).status_code == 400


def test_writes_from_other_tools_are_shown_in_the_command_log_with_their_source(monkeypatch):
    monkeypatch.setattr(cassandra_db, "delete_transaction", lambda tid: False)  # keeps this test off the database
    client = TestClient(app)
    start = commandlog.since(0, 0)["last_id"]
    target = f"/transactions/{uuid.uuid4()}"
    client.delete(target, headers={"referer": "http://localhost:8000/docs"})
    client.delete(target, headers={"referer": "http://localhost:8000/"})
    client.delete(target)
    client.delete(target, headers={"referer": "http://localhost:8000/live"})  # the live page logs its own lines
    client.delete(target, headers={"referer": "http://localhost:8000/demo"})
    lines = [c["text"] for c in commandlog.since(start)["commands"] if c["store"] == "api"]
    assert [l.split("   ")[1] for l in lines] == ["(from Swagger)", "(from the console)", "(from a direct call)"]
    assert all(l.startswith("DELETE /transactions/") for l in lines)


def test_live_endpoints_are_hidden_from_the_api_docs():
    paths = set(TestClient(app).get("/openapi.json").json()["paths"])
    assert not {"/live", "/live/now", "/live/transaction", "/live/graph", "/live/clear"} & paths


# ------------------------------------------------------------------ needs both databases running
def test_live_feed_end_to_end_then_clear_restores_the_databases():
    with TestClient(app) as client:
        client.post("/demo/reset")
        before = client.get("/stats").json()
        since = client.get("/live/now").json()["now_ms"]
        try:
            for seller, buyer, price in [("", "Alice", 0), ("Alice", "Bob", 105), ("Bob", "Carol", 108), ("Carol", "Alice", 110)]:
                r = client.post("/live/transaction", json={"seller": seller, "buyer": buyer, "ticket": "T1", "price": price})
                assert r.status_code == 201
            client.post("/sync")
            g = client.get("/live/graph", params={"since_ms": since}).json()
            assert len(g["transfers"]) == 4
            assert g["transfers"][0]["seller"] == g["platform"]
            assert {g["names"][t["buyer"]] for t in g["transfers"][1:]} == {"Bob", "Carol", "Alice"}
            ticket = g["transfers"][0]["ticket"]
            assert any(c["ticket_id"] == ticket for c in client.get("/fraud/cycles").json())  # the loop is detected
        finally:
            cleared = client.post("/live/clear", params={"since_ms": since}).json()
        assert cleared["deleted"] == 4
        assert client.get("/stats").json() == before
