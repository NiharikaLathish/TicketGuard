CREATE CONSTRAINT account_id IF NOT EXISTS FOR (a:Account) REQUIRE a.account_id IS UNIQUE;
CREATE CONSTRAINT ticket_id IF NOT EXISTS FOR (t:Ticket) REQUIRE t.ticket_id IS UNIQUE;
CREATE CONSTRAINT event_id IF NOT EXISTS FOR (e:Event) REQUIRE e.event_id IS UNIQUE;
CREATE CONSTRAINT tx_id IF NOT EXISTS FOR (x:Transaction) REQUIRE x.transaction_id IS UNIQUE;
CREATE INDEX tx_ts IF NOT EXISTS FOR (x:Transaction) ON (x.ts);
CREATE INDEX tx_fraud IF NOT EXISTS FOR (x:Transaction) ON (x.fraud_pattern);
CREATE INDEX transfer_ticket IF NOT EXISTS FOR ()-[r:TRANSFERRED_TO]-() ON (r.ticket_id);
