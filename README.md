# TicketGuard

Ticket-fraud detection using **Apache Cassandra** (high-volume transaction store) and **Neo4j** (relationship analysis).
Course: BCSE406L NoSQL Databases. Review 2 prototype.

```
Synthetic generator -> Cassandra -> Sync -> Neo4j -> Graph algorithms -> Fraud findings -> Visualisation
```

## Quick start

```bash
docker compose up -d                       # Cassandra + Neo4j (first start takes a few minutes)
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env                     # then edit credentials if you changed them

python -m generator.generate --transactions 50000 --load --sync --reset
uvicorn app.main:app --reload              # API docs: http://localhost:8000/docs
```

Open http://localhost:8000/ for the fraud console (graph of detected rings and the reasons they were flagged).

Tests (both databases must be up and loaded): `pytest -v`
Database dump: `python -m scripts.dump` (writes to `dumps/`).

## Layout

| Path | Purpose |
|---|---|
| `app/db/cassandra_db.py` | Cassandra schema and CRUD (four query-driven tables) |
| `app/db/neo4j_db.py` | Neo4j constraints/indexes, graph upsert, account/ticket CRUD |
| `app/sync.py` | Incremental Cassandra -> Neo4j sync (watermark, idempotent MERGE) |
| `app/detection.py` | Cycles, community detection, hub centrality, pricing anomalies |
| `app/main.py` | FastAPI endpoints (see `docs/API.md`) |
| `generator/generate.py` | Synthetic data with labelled fraud patterns |
| `static/index.html` | Visualisation |
| `tests/` | pytest integration tests, including detection recall/precision vs. ground truth |
| `dumps/` | Sample dataset, ground truth, database exports |

## Data model

**Cassandra** - one table per query, same columns in each. Partition and clustering keys:

| Table | Primary key | Serves |
|---|---|---|
| `transactions_by_id` | `(transaction_id)` | point lookup, update, delete |
| `transactions_by_buyer` | `((buyer_id), ts DESC, transaction_id)` | an account's history, newest first |
| `transactions_by_ticket` | `((ticket_id), ts DESC, transaction_id)` | a ticket's ownership chain |
| `transactions_by_day` | `((day), ts, transaction_id)` | time-window scans, used by sync |

Day-bucketing keeps partitions bounded and gives time-range reads. Writes go to all four tables (logged batch for single writes,
concurrent async writes for bulk load).

**Neo4j** - `Account`, `Ticket`, `Event`, `Transaction` nodes; relationships `PURCHASED`, `SOLD`, `TRANSFERRED_TO`
(carries `ticket_id`, `tx_id`, `ts`, `price`), `INVOLVES`, `MADE_BY`, `BELONGS_TO`. Uniqueness constraints on every id;
indexes on `Transaction.ts`, `Transaction.fraud_pattern` and `TRANSFERRED_TO.ticket_id`.

## Fraud detection

| Pattern | Method |
|---|---|
| Circular resale | Cypher variable-length path, same ticket returning to its starting account |
| Coordinated bot ring | Louvain community detection (GDS, NetworkX fallback) + internal density + rapid-purchase evidence |
| Hub account | Distinct-counterparty degree z-score, plus PageRank |
| Price manipulation | Resale price >= 2x face price |

Every finding includes a plain-language `reason`. No machine learning is used.
