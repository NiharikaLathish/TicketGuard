# Review 2 demo script (about 6 minutes)

You only need **two pages**:

| Page | Address | What it is for |
|---|---|---|
| **Console** | http://localhost:8000/ | The results: the numbers, the map of detected fraud, and the reason for every flagged case |
| **Live feed** | http://localhost:8000/live | The input: type a transaction and watch the commands and the graph react |

(There is also an older step-by-step page at `/demo`. You do not need it.)

Both pages update by themselves, so anything entered on one shows up on the other without reloading.

## Before you start (15 minutes early)

1. Start Docker Desktop, then in the project folder: `docker compose up -d`. Wait about 2 minutes (Neo4j is slow to start).
2. `.venv\Scripts\activate`, then `uvicorn app.main:app`. Leave that window open.
3. Open the two pages in two browser windows side by side (Windows key + Left arrow for one, Right arrow for the other):
   console on the left, live feed on the right. Both load fonts and the graph library from the internet, so check the connection.
4. Check the live feed shows a green pulsing dot and the numbers **50,000 / 8,480 / 3,870 / 69 / 150**.

## What to say first (10 seconds)

"This system detects fraud in ticket resale. Cassandra stores the transactions, Neo4j stores how accounts are connected, and
the graph shows fraud that single transactions cannot."

## 1. The console (1 minute), left window

- "50,000 transactions in Cassandra, 8,480 accounts in Neo4j. The detectors found 69 circular resales, 6 bot rings, 5 hub
  accounts and 150 price anomalies."
- Click a case in the list: the map zooms to that ring, and every case has a reason.

## 2. Type a transaction and watch it land (3 minutes), right window

Click each button, press **Send**, and wait about 3 seconds each time.

| Click | What to say |
|---|---|
| **Alice buys a ticket**, then Send | "One transaction. In the log: the API request, four green Cassandra INSERTs (one per table, because Cassandra needs one table for each way we read the data), then the automatic sync, then the blue Neo4j command that builds the graph." |
| **Alice to Bob**, then Send | "A new arrow. A normal resale, so nothing is flagged." |
| **Bob to Carol**, then Send | "Still a chain." |
| **Carol to Alice (closes the loop)**, then Send | "The ticket is back with Alice. The graph closes into a loop, turns red, and the system flags it and says why. Loops flagged goes from 69 to 70." |

Point at the counters: +4 transactions, +3 accounts, +3 transfers, +1 loop.

## 3. Everything updates (1 minute)

Look at the console on the left. Without touching it, it has changed: **70** circular resales and **172** accounts flagged.
"I did not reload anything. Anything entered anywhere updates every page."

Then let ma'am choose: ask for any names and a price and type them in the live feed, or on the console click **Log transaction**,
**Example: 5x price spike**, **Save and analyse**. The live feed picks it up by itself and shows
`POST /transactions (from the console)` in the log. Price anomalies goes from 150 to 151.

## 4. Clean up and close (1 minute)

On the live feed click **Clear session**, then check the console is back to **50,000 / 8,480 / 69 / 150**.

- "All four detectors found every planted case, and each result explains itself. The data is synthetic, so those perfect scores
  show the detectors work, not how they would perform on real data. Review 3 adds noisier cases."
- If asked, run `pytest -q` (31 tests).

## Questions you may get

- **Is it really real time?** The pages check for new commands every second, sync Cassandra to Neo4j as soon as they see a new
  write, and redraw from Neo4j, so a change shows within about one to three seconds. The background sync (every 60 seconds) is the safety net.
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

- **The live feed says "Disconnected, retrying":** a database or the app is down. Run `docker ps` and check both containers are up.
- **The graph area is empty with no error:** no internet. The log and the counters still work.
- **The numbers look off:** click **Clear session** on the live feed, then reload both pages.
- **A page does not load at all:** the app is not running. Restart `uvicorn app.main:app`.
- **Do not type directly into `cqlsh` or Neo4j Browser during the demo.** Only input that goes through the app appears on the pages.
