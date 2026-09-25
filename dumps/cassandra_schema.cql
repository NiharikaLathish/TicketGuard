CREATE KEYSPACE IF NOT EXISTS ticketguard WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1};

CREATE TABLE IF NOT EXISTS transactions_by_id ( transaction_id uuid, event_id uuid, ticket_id uuid, buyer_id uuid, seller_id uuid, ts timestamp, purchase_price decimal, resale_price decimal, transaction_type text, fraud_pattern text, day text, PRIMARY KEY (transaction_id));

CREATE TABLE IF NOT EXISTS transactions_by_buyer ( transaction_id uuid, event_id uuid, ticket_id uuid, buyer_id uuid, seller_id uuid, ts timestamp, purchase_price decimal, resale_price decimal, transaction_type text, fraud_pattern text, day text, PRIMARY KEY ((buyer_id), ts, transaction_id)) WITH CLUSTERING ORDER BY (ts DESC, transaction_id ASC);

CREATE TABLE IF NOT EXISTS transactions_by_ticket ( transaction_id uuid, event_id uuid, ticket_id uuid, buyer_id uuid, seller_id uuid, ts timestamp, purchase_price decimal, resale_price decimal, transaction_type text, fraud_pattern text, day text, PRIMARY KEY ((ticket_id), ts, transaction_id)) WITH CLUSTERING ORDER BY (ts DESC, transaction_id ASC);

CREATE TABLE IF NOT EXISTS transactions_by_day ( transaction_id uuid, event_id uuid, ticket_id uuid, buyer_id uuid, seller_id uuid, ts timestamp, purchase_price decimal, resale_price decimal, transaction_type text, fraud_pattern text, day text, PRIMARY KEY ((day), ts, transaction_id)) WITH CLUSTERING ORDER BY (ts ASC, transaction_id ASC);
