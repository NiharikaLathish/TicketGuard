# Query showcase

Every query below was run against the live TicketGuard databases (50,000 synthetic transactions). The output shown is the real output, trimmed to the first few rows. The IDs are from the generated dataset, so run `python -m generator.generate --transactions 50000 --load --sync --reset` to regenerate the data. The IDs are the same every time (the generator uses a fixed seed), but the dates shift to whichever day you run it.

How to run them:

- **CQL:** `docker exec -it ticketguard-cassandra cqlsh`, then `USE ticketguard;`
- **Cypher:** open http://localhost:7474 (user `neo4j`, password `ticketguard123`) and paste the query.


---

## Part 1: Cassandra (CQL)

Cassandra tables are designed around the question each one answers. The partition key decides which node stores a row and is the only thing you may filter on without extra work.


### C1. One day's transactions

Reads a single `day` partition of `transactions_by_day`, sorted oldest first by `ts`. This is the query the sync job uses.

```sql
SELECT transaction_id, buyer_id, transaction_type, resale_price, ts
FROM transactions_by_day WHERE day = '2026-09-10' LIMIT 5;
```

Output:

```text
transaction_id                       | buyer_id                             | transaction_type | resale_price | ts                        
-------------------------------------+--------------------------------------+------------------+--------------+---------------------------
27740bdf-2cb3-44d5-87b4-8071da2f65a3 | 659e2deb-ec28-4a93-b5a4-f270eadeae69 | Purchase         | 0.0          | 2026-09-10 00:01:06.762000
e261cd1e-c889-4301-ba5e-b25053975925 | c8794a56-a795-4d2b-9296-81b00d5979bf | Purchase         | 0.0          | 2026-09-10 00:01:48.827000
5c6f469b-e02b-42ac-9d39-e972939cb854 | ec78342e-f52d-42cc-b02d-8d1fa555dfa1 | Purchase         | 0.0          | 2026-09-10 00:02:15.123000
9955d065-784f-49ee-8342-03830fc0fa95 | f3c1114d-4e8a-40cb-a77b-71ea16f1e5cb | Resale           | 261.74       | 2026-09-10 00:05:28.795000
9f29d7e4-29e9-4475-a079-81f35d8f2794 | 3f5e3b8c-c058-4da5-a757-075bd47f83b1 | Purchase         | 0.0          | 2026-09-10 00:05:58.483000
```


### C2. A buyer's purchase history

`buyer_id` is the partition key of `transactions_by_buyer`, so the lookup touches one partition. Rows come back newest first because of `CLUSTERING ORDER BY (ts DESC)`.

```sql
SELECT ts, ticket_id, transaction_type, resale_price
FROM transactions_by_buyer WHERE buyer_id = 659e2deb-ec28-4a93-b5a4-f270eadeae69 LIMIT 5;
```

Output:

```text
ts                         | ticket_id                            | transaction_type | resale_price
---------------------------+--------------------------------------+------------------+-------------
2026-09-17 00:27:50.825000 | 466c9854-3d94-4f32-84ee-41f5f27b26e4 | Resale           | 606.99      
2026-09-13 18:09:57.191000 | 41417f15-9299-4f46-bc08-bc5a8481110c | Purchase         | 0.0         
2026-09-10 00:01:06.762000 | 8dfe56bb-e5f5-4077-beb7-a8ab601b2fa6 | Purchase         | 0.0         
2026-09-09 11:08:32.765000 | d98096fc-b901-4eba-bb56-3c769eefca23 | Purchase         | 0.0         
```


### C3. A ticket's ownership chain

Every resale of one ticket lives in the same partition of `transactions_by_ticket`. This ticket (`480a202f`) is one of the injected circular-resale tickets, so you can see it pass through several accounts.

```sql
SELECT ts, seller_id, buyer_id, resale_price, transaction_type
FROM transactions_by_ticket WHERE ticket_id = 480a202f-1cde-4b69-b8fb-04f3cbbc04a3;
```

Output:

```text
ts                         | seller_id                            | buyer_id                             | resale_price | transaction_type
---------------------------+--------------------------------------+--------------------------------------+--------------+-----------------
2026-09-14 09:30:31.695000 | 4f2e8a08-63b3-4fd0-8ef9-0bcc8988266f | 1c179c69-9535-49c6-8379-b61d1a9e82f5 | 46.51        | Resale          
2026-09-14 09:11:27.885000 | 8e67d7d8-431b-4c70-93a3-b34e87e504ce | 4f2e8a08-63b3-4fd0-8ef9-0bcc8988266f | 44.26        | Resale          
2026-09-14 08:45:18.548000 | 1c179c69-9535-49c6-8379-b61d1a9e82f5 | 8e67d7d8-431b-4c70-93a3-b34e87e504ce | 46.02        | Resale          
2026-09-14 08:27:23.717000 | 00000000-0000-0000-0000-000000000001 | 1c179c69-9535-49c6-8379-b61d1a9e82f5 | 0.0          | Purchase        
```


### C4. Fetch a single transaction

Point lookup by primary key on `transactions_by_id`. This is what `GET /transactions/{id}` uses.

```sql
SELECT transaction_id, ticket_id, buyer_id, seller_id, purchase_price, resale_price, fraud_pattern
FROM transactions_by_id WHERE transaction_id = 27740bdf-2cb3-44d5-87b4-8071da2f65a3;
```

Output:

```text
transaction_id                       | ticket_id                            | buyer_id                             | seller_id                            | purchase_price | resale_price | fraud_pattern
-------------------------------------+--------------------------------------+--------------------------------------+--------------------------------------+----------------+--------------+--------------
27740bdf-2cb3-44d5-87b4-8071da2f65a3 | 8dfe56bb-e5f5-4077-beb7-a8ab601b2fa6 | 659e2deb-ec28-4a93-b5a4-f270eadeae69 | 00000000-0000-0000-0000-000000000001 | 267.25         | 0.0          | none         
```


### C5. Time-window query inside one day

Because `ts` is a clustering column, a range on it inside one partition is efficient (a sequential read, no scan).

```sql
SELECT transaction_type, resale_price, ts FROM transactions_by_day
WHERE day = '2026-09-10' AND ts >= '2026-09-10 12:00:00+0000' AND ts < '2026-09-10 12:30:00+0000';
```

Output:

```text
transaction_type | resale_price | ts                        
-----------------+--------------+---------------------------
Purchase         | 0.0          | 2026-09-10 12:00:06.560000
Purchase         | 0.0          | 2026-09-10 12:01:30.306000
Purchase         | 0.0          | 2026-09-10 12:02:00.189000
Purchase         | 0.0          | 2026-09-10 12:02:43.010000
Purchase         | 0.0          | 2026-09-10 12:03:56.291000
```


### C6. Count the rows in a day partition

Counting one partition is fine. Counting the whole table (`SELECT COUNT(*) FROM transactions_by_id`) scans every node, so avoid it in production.

```sql
SELECT COUNT(*) AS rows_in_day FROM transactions_by_day WHERE day = '2026-09-10';
```

Output:

```text
rows_in_day
-----------
2053       
```


### C7. List the day partitions

How many day partitions exist (each is a bounded partition, which is the point of day-bucketing).

```sql
SELECT DISTINCT day FROM transactions_by_day;
```

Output (29 partitions, first 5 shown):

```text
day       
----------
2026-08-26
2026-08-27
2026-08-28
2026-08-29
2026-08-30
```


### C8. A query Cassandra refuses (and why)

`transactions_by_id` is partitioned by `transaction_id`, so filtering it by `buyer_id` would need a scan of every partition. Cassandra rejects it instead of running slowly. The fix is the design principle of this project: use the table built for that question (`transactions_by_buyer`, query C2).

```sql
SELECT * FROM transactions_by_id WHERE buyer_id = 659e2deb-ec28-4a93-b5a4-f270eadeae69;
```

Output:

```text
Error from server: code=2200 [Invalid query] message="Cannot execute this query as it might involve data filtering and thus may have unpredictable performance. If you want to execute this query despite the performance unpredictability, use ALLOW FILTERING"
```


---

## Part 2: Neo4j (Cypher)

Neo4j answers questions about connections. Accounts, tickets, events and transactions are nodes; `TRANSFERRED_TO` links the seller to the buyer and carries the `ticket_id`, `price` and `ts`.


### N1. How big is the graph?

Node counts by label.

```cypher
MATCH (n) WHERE n:Account OR n:Ticket OR n:Event OR n:Transaction
RETURN labels(n)[0] AS label, count(*) AS nodes ORDER BY nodes DESC
```

Output:

```text
label       | nodes
------------+------
Transaction | 50000
Ticket      | 46130
Account     | 8480 
Event       | 60   
```


### N2. Relationship types

How many of each relationship exist.

```cypher
MATCH ()-[r]->() RETURN type(r) AS relationship, count(*) AS total ORDER BY total DESC
```

Output:

```text
relationship   | total
---------------+------
INVOLVES       | 50000
MADE_BY        | 50000
SOLD           | 50000
PURCHASED      | 49931
BELONGS_TO     | 46130
TRANSFERRED_TO | 3870 
```


### N3. Accounts with the most trading partners

Counts distinct counterparties (either direction). The injected hub accounts float to the top; this is the idea behind the hub detector.

```cypher
MATCH (a:Account)-[r:TRANSFERRED_TO]-(b:Account)
WHERE NOT coalesce(a.is_platform, false)
RETURN a.account_id AS account, count(DISTINCT b) AS partners
ORDER BY partners DESC LIMIT 5
```

Output:

```text
account                              | partners
-------------------------------------+---------
fbc7b2a5-a368-47fa-b958-397900747f3f | 75      
4e710f53-baec-4ca3-8fdc-8ac813958e2f | 70      
7013fa67-f244-481a-8e1f-e43215dcb535 | 55      
e4425217-d6d4-436b-92ee-f5bb16b3bada | 53      
bfeca531-7036-4ba0-9ad8-1d87c20ae0f1 | 42      
```


### N4. One ticket's full path

Follows a single ticket through its transfers in time order (ticket `480a202f`).

```cypher
MATCH (s:Account)-[r:TRANSFERRED_TO {ticket_id: '480a202f-1cde-4b69-b8fb-04f3cbbc04a3'}]->(b:Account)
RETURN s.account_id AS from_account, b.account_id AS to_account, r.price AS price, r.ts AS ts_ms
ORDER BY r.ts
```

Output:

```text
from_account                         | to_account                           | price | ts_ms        
-------------------------------------+--------------------------------------+-------+--------------
1c179c69-9535-49c6-8379-b61d1a9e82f5 | 8e67d7d8-431b-4c70-93a3-b34e87e504ce | 46.02 | 1789375518548
8e67d7d8-431b-4c70-93a3-b34e87e504ce | 4f2e8a08-63b3-4fd0-8ef9-0bcc8988266f | 44.26 | 1789377087885
4f2e8a08-63b3-4fd0-8ef9-0bcc8988266f | 1c179c69-9535-49c6-8379-b61d1a9e82f5 | 46.51 | 1789378231695
```


### N5. Find circular resales

A ticket that leaves an account and comes back to it through 3 to 5 hops. The property filter keeps the search to one ticket at a time, which is why it is fast. A ticket can appear more than once because the loop is found from each account on it; the application code removes these duplicates.

```cypher
MATCH (a:Account)-[f:TRANSFERRED_TO]->()
WITH DISTINCT a, f.ticket_id AS tid
MATCH p = (a)-[rs:TRANSFERRED_TO*3..5 {ticket_id: tid}]->(a)
RETURN tid AS ticket, length(p) AS hops LIMIT 5
```

Output:

```text
ticket                               | hops
-------------------------------------+-----
480a202f-1cde-4b69-b8fb-04f3cbbc04a3 | 3   
1e668738-becf-4316-866b-0a014f901410 | 3   
ac78dec5-d639-48aa-9650-e1f322315476 | 3   
480a202f-1cde-4b69-b8fb-04f3cbbc04a3 | 3   
1e668738-becf-4316-866b-0a014f901410 | 3   
```


### N6. Who bought the most for one event?

Accounts with the most purchases for the busiest event (`759cde66`). Bot accounts buy many tickets at once.

```cypher
MATCH (x:Transaction {transaction_type:'Purchase'})-[:MADE_BY]->(a:Account),
      (x)-[:INVOLVES]->(:Ticket)-[:BELONGS_TO]->(e:Event {event_id: '759cde66-bacf-43d0-8b1f-9163ce9ff57f'})
RETURN a.account_id AS account, count(x) AS tickets_bought ORDER BY tickets_bought DESC LIMIT 5
```

Output:

```text
account                              | tickets_bought
-------------------------------------+---------------
67753489-3bdc-4115-8148-e22463404548 | 10            
d1049948-5f6d-4884-84fb-cda0164e03e0 | 10            
d95d48ed-6a02-4dca-a566-a39e41a3e739 | 10            
923da956-9be2-4179-bf1d-8f89847ccb1d | 9             
e0788722-adef-4e74-a1a1-b34377a4802c | 8             
```


### N7. Rapid buyers (bot behaviour)

Accounts that bought 6 or more tickets for one event within 5 minutes. This is the evidence the bot-ring detector uses.

```cypher
MATCH (x:Transaction {transaction_type:'Purchase'})-[:MADE_BY]->(a:Account),
      (x)-[:INVOLVES]->(:Ticket)-[:BELONGS_TO]->(e:Event)
WITH a, e, count(x) AS n, min(x.ts) AS t0, max(x.ts) AS t1
WHERE n >= 6 AND (t1 - t0) <= 300000
RETURN a.account_id AS account, n AS tickets, (t1 - t0) / 1000 AS seconds_apart
ORDER BY n DESC LIMIT 5
```

Output:

```text
account                              | tickets | seconds_apart
-------------------------------------+---------+--------------
8ffbcc0f-0587-49f3-bc03-af356577aba9 | 10      | 99           
49a4582a-a153-4da4-a2a1-30524de26097 | 10      | 63           
7414d8f7-6d93-4815-aac0-ce2b819f7810 | 10      | 111          
5a18f557-8f24-43da-8141-c9c57f7eedaa | 10      | 106          
67753489-3bdc-4115-8148-e22463404548 | 10      | 111          
```


### N8. Biggest price markups

Resales priced at more than 2x the original price, highest first (the pricing detector).

```cypher
MATCH (x:Transaction {transaction_type:'Resale'})
WHERE x.purchase_price > 0 AND x.resale_price >= 2 * x.purchase_price
RETURN x.transaction_id AS transaction, x.purchase_price AS face, x.resale_price AS resale,
       round(x.resale_price / x.purchase_price * 10) / 10 AS ratio
ORDER BY ratio DESC LIMIT 5
```

Output:

```text
transaction                          | face   | resale  | ratio
-------------------------------------+--------+---------+------
f8a659fe-d6ba-40d7-acb8-85988f3fd6c5 | 92.13  | 723.45  | 7.9  
019c5d08-2648-470f-be42-6a8cb8ed9543 | 206.97 | 1636.67 | 7.9  
b5c81c42-a7fd-48ef-bca2-8c66a62be74f | 104.26 | 822.83  | 7.9  
4322d917-14a2-47c2-ae24-0f8be12c1734 | 76.21  | 604.6   | 7.9  
301e5da2-f440-4068-87ee-1ab4f8965e8c | 267.25 | 2106.67 | 7.9  
```


### N9. Everything one hub account touches

The number of tickets a known hub account (`e4425217`) sold, and to how many different buyers.

```cypher
MATCH (h:Account {account_id: 'e4425217-d6d4-436b-92ee-f5bb16b3bada'})-[r:TRANSFERRED_TO]->(b:Account)
RETURN count(r) AS tickets_sold, count(DISTINCT b) AS distinct_buyers
```

Output:

```text
tickets_sold | distinct_buyers
-------------+----------------
53           | 53             
```


### N10. Shortest link between two accounts

The shortest chain of ticket transfers connecting two accounts of the same bot ring. This kind of question is where a graph database is much simpler than SQL joins.

```cypher
MATCH (a:Account {account_id: '8ffbcc0f-0587-49f3-bc03-af356577aba9'}), (b:Account {account_id: '1344c2f6-469a-4da3-a7d7-3e5748c31385'})
MATCH p = shortestPath((a)-[:TRANSFERRED_TO*..6]-(b))
RETURN length(p) AS hops, [n IN nodes(p) | left(n.account_id, 8)] AS route
```

Output:

```text
hops | route                   
-----+-------------------------
1    | ['8ffbcc0f', '1344c2f6']
```


---

## Why two databases

| Question type | Best store | Reason |
|---|---|---|
| "Show me transactions for this buyer / ticket / day" | Cassandra | Single-partition reads; no joins; scales by adding nodes |
| "Which accounts form a loop / cluster / hub?" | Neo4j | The answer is a shape in the connections, found by traversal |
