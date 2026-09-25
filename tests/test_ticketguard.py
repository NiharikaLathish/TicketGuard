"""Integration tests. Require both databases running (docker compose up -d).

Run:  pytest -v
The fraud-detection tests need the generated dataset loaded and synced first:
    python -m generator.generate --transactions 50000 --load --sync --reset
"""
import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _tx_body(**over):
    body = {"event_id": str(uuid.uuid4()), "ticket_id": str(uuid.uuid4()), "buyer_id": str(uuid.uuid4()),
            "seller_id": str(uuid.uuid4()), "purchase_price": 100, "resale_price": 120,
            "transaction_type": "Resale"}
    body.update(over)
    return body


def test_health(client):
    h = client.get("/health").json()
    assert h["cassandra"] == "up" and h["neo4j"] == "up"


# ------------------------------------------------ Cassandra CRUD
def test_transaction_crud_lifecycle(client):
    body = _tx_body()
    created = client.post("/transactions", json=body)
    assert created.status_code == 201
    tid = created.json()["transaction_id"]

    got = client.get(f"/transactions/{tid}")
    assert got.status_code == 200 and got.json()["resale_price"] == 120

    # every query table must see the row
    by_buyer = client.get("/transactions", params={"buyer_id": body["buyer_id"]}).json()
    by_ticket = client.get("/transactions", params={"ticket_id": body["ticket_id"]}).json()
    assert [t["transaction_id"] for t in by_buyer] == [tid]
    assert [t["transaction_id"] for t in by_ticket] == [tid]
    day = created.json()["ts"][:10]
    assert tid in [t["transaction_id"] for t in client.get("/transactions", params={"day": day}).json()]

    upd = client.put(f"/transactions/{tid}", json={"resale_price": 999})
    assert upd.status_code == 200 and upd.json()["resale_price"] == 999
    assert client.get("/transactions", params={"buyer_id": body["buyer_id"]}).json()[0]["resale_price"] == 999

    assert client.delete(f"/transactions/{tid}").status_code == 204
    assert client.get(f"/transactions/{tid}").status_code == 404
    assert client.get("/transactions", params={"buyer_id": body["buyer_id"]}).json() == []


def test_transaction_validation(client):
    assert client.post("/transactions", json=_tx_body(transaction_type="Bogus")).status_code == 422
    assert client.post("/transactions", json=_tx_body(purchase_price=-5)).status_code == 422
    assert client.get("/transactions").status_code == 400  # needs exactly one filter
    assert client.get(f"/transactions/{uuid.uuid4()}").status_code == 404


# ------------------------------------------------ Neo4j CRUD
def test_account_crud_lifecycle(client):
    aid = str(uuid.uuid4())
    assert client.post("/accounts", json={"account_id": aid, "name": "Test User"}).status_code == 201
    assert client.get(f"/accounts/{aid}").json()["name"] == "Test User"
    assert client.put(f"/accounts/{aid}", json={"flagged": True}).json()["flagged"] is True
    assert client.delete(f"/accounts/{aid}").status_code == 204
    assert client.get(f"/accounts/{aid}").status_code == 404


# ------------------------------------------------ sync
def test_sync_propagates_new_transaction_and_delete(client):
    body = _tx_body(transaction_type="Resale")
    tid = client.post("/transactions", json=body).json()["transaction_id"]
    assert client.post("/sync").json()["synced"] >= 1
    hist = client.get(f"/tickets/{body['ticket_id']}/history")
    assert hist.status_code == 200
    assert hist.json()["transfers"][0]["to"] == body["buyer_id"]
    assert client.post("/sync").json()["synced"] == 0  # idempotent: nothing new
    client.delete(f"/transactions/{tid}")
    assert client.get(f"/tickets/{body['ticket_id']}/history").json()["transfers"] == []


# ------------------------------------------------ fraud detection vs. ground truth
@pytest.fixture(scope="module")
def truth():
    p = ROOT / "dumps" / "ground_truth.json"
    if not p.exists():
        pytest.skip("run the generator first to create ground truth")
    return json.loads(p.read_text())


def _recall(found: set, expected: set) -> float:
    return len(found & expected) / len(expected) if expected else 1.0


def test_cycles_find_injected_rings(client, truth):
    found = {a for c in client.get("/fraud/cycles").json() for a in c["accounts"]}
    expected = {a for ring in truth["circular_resale"] for a in ring}
    assert _recall(found, expected) >= 0.9
    assert len(found - expected) / max(len(found), 1) <= 0.1  # precision >= 90%


def test_communities_find_bot_rings(client, truth):
    found = {a for c in client.get("/fraud/communities").json() for a in c["accounts"]}
    expected = {a for ring in truth["bot_ring"] for a in ring}
    assert _recall(found, expected) >= 0.8
    assert len(found - expected) / max(len(found), 1) <= 0.2


def test_hubs_found(client, truth):
    found = {h["account_id"] for h in client.get("/fraud/hubs").json()}
    assert _recall(found, set(truth["hub_account"])) >= 0.8


def test_pricing_anomalies_found(client, truth):
    found = {p["ticket_id"] for p in client.get("/fraud/pricing", params={"limit": 5000}).json()}
    assert _recall(found, set(truth["price_manipulation"])) >= 0.95


def test_every_finding_has_reason(client):
    for path in ("cycles", "communities", "hubs", "pricing"):
        for f in client.get(f"/fraud/{path}").json()[:20]:
            assert f["reason"]
