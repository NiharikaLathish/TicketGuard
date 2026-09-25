"""Additional tests: validation, error handling, query ordering, sync behaviour and the background sync.

Same requirements as test_ticketguard.py (both databases running with the dataset loaded).
"""
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import sync_worker
from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _body(**over):
    body = {"event_id": str(uuid.uuid4()), "ticket_id": str(uuid.uuid4()), "buyer_id": str(uuid.uuid4()),
            "seller_id": str(uuid.uuid4()), "purchase_price": 100, "resale_price": 120,
            "transaction_type": "Resale"}
    body.update(over)
    return body


# ------------------------------------------------ validation
def test_negative_resale_price_rejected(client):
    assert client.post("/transactions", json=_body(resale_price=-1)).status_code == 422


def test_missing_and_malformed_fields_rejected(client):
    body = _body()
    del body["buyer_id"]
    assert client.post("/transactions", json=body).status_code == 422
    assert client.post("/transactions", json=_body(ticket_id="not-a-uuid")).status_code == 422


def test_unknown_ids_return_404(client):
    missing = str(uuid.uuid4())
    assert client.put(f"/transactions/{missing}", json={"resale_price": 5}).status_code == 404
    assert client.delete(f"/transactions/{missing}").status_code == 404
    assert client.delete(f"/accounts/{missing}").status_code == 404
    assert client.get(f"/tickets/{missing}/history").status_code == 404


# ------------------------------------------------ Cassandra query behaviour
def test_buyer_history_is_newest_first(client):
    buyer = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    ids = []
    for days_ago in (3, 1, 2):
        r = client.post("/transactions", json=_body(buyer_id=buyer, ts=(now - timedelta(days=days_ago)).isoformat()))
        assert r.status_code == 201
        ids.append(r.json()["transaction_id"])
    try:
        times = [t["ts"] for t in client.get("/transactions", params={"buyer_id": buyer}).json()]
        assert len(times) == 3
        assert times == sorted(times, reverse=True)  # CLUSTERING ORDER BY ts DESC
    finally:
        for tid in ids:
            client.delete(f"/transactions/{tid}")


def test_update_changes_only_requested_fields(client):
    created = client.post("/transactions", json=_body(resale_price=120)).json()
    tid = created["transaction_id"]
    try:
        updated = client.put(f"/transactions/{tid}", json={"transaction_type": "Transfer"}).json()
        assert updated["transaction_type"] == "Transfer"
        assert updated["resale_price"] == 120  # untouched
    finally:
        client.delete(f"/transactions/{tid}")


# ------------------------------------------------ sync and graph
def test_sync_twice_does_not_change_counts(client):
    client.post("/sync")
    before = client.get("/stats").json()
    assert client.post("/sync").json()["synced"] == 0
    assert client.get("/stats").json() == before


# ------------------------------------------------ detection parameters
def test_higher_price_ratio_flags_fewer(client):
    default = client.get("/fraud/pricing", params={"limit": 5000}).json()
    strict = client.get("/fraud/pricing", params={"ratio": 10, "limit": 5000}).json()
    assert len(default) > 0
    assert len(strict) < len(default)


def test_cycle_length_filter(client):
    assert client.get("/fraud/cycles", params={"min_len": 6, "max_len": 6}).json() == []


# ------------------------------------------------ background sync
def test_background_sync_moves_new_transaction_without_calling_sync(client):
    body = _body(transaction_type="Resale")
    tid = client.post("/transactions", json=body).json()["transaction_id"]
    _, stop = sync_worker.start(1)
    try:
        for _ in range(20):  # up to about 20 seconds
            if client.get(f"/tickets/{body['ticket_id']}/history").status_code == 200:
                break
            time.sleep(1)
        assert client.get(f"/tickets/{body['ticket_id']}/history").status_code == 200
    finally:
        stop.set()
        client.delete(f"/transactions/{tid}")
