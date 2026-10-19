# Review 2 demo script (about 8 minutes)

The live demo page (`/demo`) runs a scenario one step at a time. After each step you can point at three things:
the **steps** on the left, the **graph** read back from Neo4j on the right, and the **commands** underneath
(the exact API request, CQL and Cypher that ran).

## Before you start (do this 15 minutes early)

1. Start Docker Desktop, then in the project folder: `docker compose up -d`. Wait about 2 minutes (Neo4j is slow to start).
2. `.venv\Scripts\activate`, then `uvicorn app.main:app`. Leave that window open.
3. Open two browser tabs: http://localhost:8000/ (console) and http://localhost:8000/demo (live demo).
   Both pages load their fonts and the graph library from the internet, so check the connection.
4. Optional, for the "show the real tools" part: open Neo4j Browser at http://localhost:7474 (user `neo4j`, password `ticketguard123`)
   and a terminal running `docker exec -it ticketguard-cassandra cqlsh` followed by `USE ticketguard;`.
5. Do one dry run: press **Run all**, then **Start over**. The four numbers must return to 50,000 / 8,480 / 3,870 / 69.

## 1. The console (1 minute)

Open http://localhost:8000/.
- "Cassandra holds 50,000 synthetic transactions. Neo4j holds the same activity as a graph: 8,480 accounts, 46,130 tickets."
- "The detectors found 69 circular resales, 6 bot rings, 5 hub accounts and 150 price anomalies. Every case has a reason."
- Click a case in the list: the map zooms to that ring.

## 2. Live demo: circular resale (3 minutes)

Switch to the `/demo` tab. Note the four numbers at the top; they are the starting point.

| Press | What happens | What to say |
|---|---|---|
| **Run first step** | Alice buys a ticket from the platform | "One API call. Look at the log: Cassandra gets four INSERTs, one per table, because each table answers a different question. Then the sync copies it into Neo4j with a MERGE, and the graph on the right is read back from Neo4j." |
| **Run next step** (Alice to Bob) | A new arrow appears | "A normal resale. The Cassandra count and the Neo4j transfer count each go up by one. Nothing is flagged." |
| **Run next step** (Bob to Carol) | The chain gets longer | "Still a chain." |
| **Run next step** (Carol to Alice) | The chain closes into a red loop; **Detected** appears | "The ticket is back with the account that started it. The cycle query finds it and explains why. The circular-resale counter goes from 69 to 70." |

Point at the log's colours: grey = API request, green = Cassandra, yellow = sync, blue = Neo4j, red = detection.

**Optional: show the same thing in the real tools** (before you press Start over). In the log, find the line
`GET /demo/graph?ticket_id=...` and copy the id. Then:

- In `cqlsh`:
  ```sql
  SELECT ts, seller_id, buyer_id, resale_price, transaction_type FROM transactions_by_ticket WHERE ticket_id = <paste id>;
  ```
- In Neo4j Browser:
  ```cypher
  MATCH p = (a:Account)-[:TRANSFERRED_TO*3..5 {ticket_id: '<paste id>'}]->(a) RETURN p LIMIT 1
  ```

Press **Start over**. This deletes only the demo's own transactions (labelled `demo`) from both databases;
the 50,000 sample transactions are never touched.

## 3. Live demo: price spike (1 minute)

Click the **Price spike** tab and press **Run all**. "Here the graph looks ordinary: one edge. What gives it away is the
price: 500 against a face value of 100. That is a different detector, a rule on the price ratio." Anomalies go from 150 to 151.
Press **Start over** again.

## 4. Close (1 minute)

- "All four detectors found every planted case, and each result explains itself. The data is synthetic, so those perfect scores
  show the detectors work, not how they would perform on real data. Review 3 adds noisier cases."
- If asked, run `pytest -q` (19 tests, plus the demo tests).

## Questions you may get

- **Why two databases?** Cassandra is built for fast writes and for reads along one key. Neo4j is built for following relationships.
  Loops and clusters are relationship questions, which are awkward in tables. Each store does the job it is best at.
- **Why four Cassandra tables with the same data?** Cassandra only reads efficiently along the partition key. One table per question
  (by id, buyer, ticket, day) means every query reads one partition, with no joins. The cost is storing the data four times.
- **How do the two stay consistent?** A sync job copies new transactions from Cassandra to Neo4j using a time watermark and MERGE,
  so it can be repeated safely. It runs automatically every 60 seconds and on demand.
- **What if Neo4j is down?** Cassandra keeps accepting transactions. The sync catches up when Neo4j returns.
- **Is it machine learning?** No. It uses a Cypher path query for loops, Louvain community detection for bot rings, a degree statistic
  for hubs and a price-ratio rule. Every finding has a plain-language reason.
- **Why are the scores perfect?** The fraud is synthetic and clearly separated from normal traffic. It shows each detector finds what
  was planted. Noisier data is planned for Review 3.
- **What are the limits?** Single-node databases; thresholds tuned on synthetic data only; an incremental sync that misses a
  back-dated transaction until a full sync (`POST /sync?full=true`). See Section 14 of the report.
- **Who did what?** Answer with the real split from Section 12.1 of the report.

## If something goes wrong

- **The graph area is empty or says the library could not load:** no internet. The steps and the log still work.
- **An ERROR line appears in the log:** a database is not running. Check `docker ps`, wait a minute, press **Start over**.
- **The numbers look off:** press **Start over**; it removes anything a previous run left behind.
- **The page does not load at all:** the app is not running. Restart `uvicorn app.main:app`.
