# TicketGuard API

Base URL `http://localhost:8000`. Interactive Swagger UI at `/docs`, OpenAPI JSON at `/openapi.json`.
IDs are UUIDs. Timestamps are ISO-8601 UTC.

## System
| Method | Path | Description |
|---|---|---|
| GET | `/health` | Connectivity of Cassandra and Neo4j |
| GET | `/stats` | Transaction count in Cassandra; node/edge counts in Neo4j |

## Transactions (Cassandra CRUD)
| Method | Path | Description |
|---|---|---|
| POST | `/transactions` | Create. Body: `event_id, ticket_id, buyer_id, seller_id, purchase_price, resale_price, transaction_type (Purchase\|Resale\|Transfer), fraud_pattern?, ts?`. Returns 201 |
| GET | `/transactions/{id}` | Retrieve one |
| GET | `/transactions?buyer_id=` / `?ticket_id=` / `?day=YYYY-MM-DD` | Query by exactly one key, `limit` (max 1000). Each routes to its own Cassandra table |
| PUT | `/transactions/{id}` | Update `purchase_price, resale_price, transaction_type, fraud_pattern`; also refreshes the graph |
| DELETE | `/transactions/{id}` | Delete from all Cassandra tables and from Neo4j. Returns 204 |

## Accounts and tickets (Neo4j CRUD)
| Method | Path | Description |
|---|---|---|
| POST | `/accounts` | Create/upsert. Body: `name, account_id?` |
| GET | `/accounts?limit=&skip=` | List |
| GET | `/accounts/{id}` | Account with incoming/outgoing transfer counts |
| PUT | `/accounts/{id}` | Update `name, flagged, notes` |
| DELETE | `/accounts/{id}` | Delete node and its relationships |
| GET | `/tickets/{id}/history` | Ordered ownership transfers of a ticket |

## Synchronisation
A background worker also runs this sync automatically every `SYNC_INTERVAL_SECONDS` (default 60, set 0 to disable), so calling the endpoint is only needed for an immediate sync or a full re-sync.

| Method | Path | Description |
|---|---|---|
| POST | `/sync?full=false` | Copy transactions newer than the stored watermark from Cassandra into Neo4j. `full=true` re-syncs everything. Idempotent |

## Fraud detection
| Method | Path | Parameters | Returns |
|---|---|---|---|
| GET | `/fraud/summary` | - | Counts per pattern and total flagged accounts |
| GET | `/fraud/cycles` | `min_len=2, max_len=6` | Ticket, accounts in the loop, reason |
| GET | `/fraud/communities` | `min_size=5, min_avg_degree=1.8` | Account groups, density, rapid buyers, reason |
| GET | `/fraud/hubs` | `z_threshold=4, min_degree=20` | Account, degree, z-score, PageRank, reason |
| GET | `/fraud/pricing` | `ratio=2.0, limit=500` | Transactions resold at >= ratio x face price, reason |
| GET | `/fraud/graph` | `pattern=all\|circular_resale\|bot_ring\|hub_account` | vis-network nodes/edges for the console |

## Errors
`400` bad query combination, `404` not found, `422` validation failure (e.g. unknown `transaction_type`, negative price).

## Example
```bash
curl -X POST localhost:8000/transactions -H "Content-Type: application/json" -d '{
  "event_id":"11111111-1111-1111-1111-111111111111","ticket_id":"22222222-2222-2222-2222-222222222222",
  "buyer_id":"33333333-3333-3333-3333-333333333333","seller_id":"44444444-4444-4444-4444-444444444444",
  "purchase_price":100,"resale_price":140,"transaction_type":"Resale"}'
curl localhost:8000/fraud/summary
```
