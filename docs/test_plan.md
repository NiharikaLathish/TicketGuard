# Test plan and results

Every case below was executed against the running system (50,000 synthetic transactions) and the **Actual result** column is what was observed. Cases that create data delete it afterwards, so the dataset is unchanged.

**How to repeat a case by hand:** open http://localhost:8000/docs, expand the endpoint named in *Steps*, click *Try it out* and *Execute*. Screenshots for the report can be taken there and saved in `docs/screenshots/`.

| ID | Test case | Steps | Expected result | Actual result | Status |
|---|---|---|---|---|---|
| T01 | Health check | GET /health | Both databases report up | cassandra=up, neo4j=up | Pass |
| T02 | Dataset loaded | GET /stats | 50,000 transactions in Cassandra and Neo4j | Cassandra 50,000; Neo4j 50,000 transactions, 8,480 accounts, 46,130 tickets | Pass |
| T03 | Insert a transaction (Create) | POST /transactions with a resale of 100 -> 140 | 201 Created and a transaction_id | HTTP 201, transaction_id e222f5b4... | Pass |
| T04 | Retrieve by id (Read) | GET /transactions/{id} | 200 and the same prices | HTTP 200, resale_price=140.0 | Pass |
| T05 | Query each Cassandra table | GET /transactions?buyer_id= / ?ticket_id= / ?day= | The row is found via all three query tables | by buyer: 1 row; by ticket: 1 row; by day: found=True | Pass |
| T06 | Update a transaction | PUT /transactions/{id} with resale_price 999 | 200, and every table shows 999 | HTTP 200, by_id=999.0, by_buyer table=999.0 | Pass |
| T07 | Sync new data to Neo4j | POST /sync then GET /tickets/{id}/history | At least 1 record synced; the transfer appears in the graph | synced=1, history HTTP 200, transfers=1 | Pass |
| T08 | Sync is idempotent | POST /sync again | 0 records synced (nothing new) | synced=0 | Pass |
| T09 | Delete a transaction | DELETE /transactions/{id} | 204; then 404 in Cassandra and the ticket is removed from Neo4j | delete HTTP 204; GET transaction HTTP 404; ticket history HTTP 404 | Pass |
| T10 | Input validation | POST negative price; POST unknown type; GET /transactions with no filter | 422, 422, 400 | 422, 422, 400 | Pass |
| T11 | Unknown ids | GET a random transaction id and account id | 404 for both | 404, 404 | Pass |
| T12 | Account CRUD in Neo4j | POST, GET, PUT (flagged=true), DELETE, GET /accounts/{id} | 201, name returned, flagged=true, 204, then 404 | 201, name='Test User', flagged=True, 204, 404 | Pass |
| T13 | Detect circular resale | GET /fraud/cycles | Finds the 25 injected rings; each has a reason | 69 loops found; recall 1.0, precision 1.0; sample: "Ticket 480a202f was resold around a closed loop of 3 accounts and returned to its starting account." | Pass |
| T14 | Detect bot rings | GET /fraud/communities | Finds the 6 injected bot rings (11 accounts each) | 6 communities; sizes [11, 11, 11, 11, 11, 11]; recall 1.0, precision 1.0 | Pass |
| T15 | Detect hub accounts | GET /fraud/hubs | Finds the 5 injected hubs | 5 hubs; degrees [75, 70, 55, 53, 42]; recall 1.0 | Pass |
| T16 | Detect price manipulation | GET /fraud/pricing | Flags the 150 injected tickets resold at 3-8x | 150 flagged; max ratio 7.93x; recall 1.0, precision 1.0 | Pass |
| T17 | Fraud summary | GET /fraud/summary | Counts match the individual detectors | {"circular_resale": 69, "bot_rings": 6, "hub_accounts": 5, "price_anomalies": 150, "flagged_accounts": 169} | Pass |

**Summary:** 17 of 17 cases passed.

## Automated tests

`pytest -q` runs 19 automated tests (10 in `tests/test_ticketguard.py`, 9 in `tests/test_extra.py`), covering the CRUD lifecycles, validation, sync behaviour, detection accuracy against the ground truth, and the background sync. All 19 pass.

## Detection accuracy against ground truth

| Pattern | Injected | Found | Precision | Recall |
|---|---|---|---|---|
| Circular resale (accounts) | 98 | 98 | 1.0 | 1.0 |
| Bot ring (accounts) | 66 | 66 | 1.0 | 1.0 |
| Hub account (accounts) | 5 | 5 | 1.0 | 1.0 |
| Price manipulation (tickets) | 150 | 150 | 1.0 | 1.0 |

The data is synthetic and cleanly separated, so perfect scores are expected. They show each detector finds what was planted; they do not predict accuracy on real data.

## Known limitation

The incremental sync uses a timestamp watermark, so a transaction back-dated to before the newest synced one is not picked up. Run `POST /sync?full=true` in that case.