"""Export both databases to ./dumps (the 'database dump' deliverable).

    python -m scripts.dump

Cassandra -> dumps/cassandra_schema.cql + dumps/cassandra_transactions.csv
Neo4j     -> dumps/neo4j_nodes_<Label>.csv, dumps/neo4j_relationships.csv, dumps/neo4j_schema.cypher
"""
import csv
from pathlib import Path

from app.db import cassandra_db, neo4j_db

OUT = Path(__file__).resolve().parent.parent / "dumps"


def dump_cassandra():
    (OUT / "cassandra_schema.cql").write_text(
        ";\n\n".join([cassandra_db.KEYSPACE_DDL] + [" ".join(d.split()) for d in cassandra_db.TABLE_DDL]) + ";\n",
        encoding="utf-8")
    n = 0
    with open(OUT / "cassandra_transactions.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cassandra_db.COLUMNS)
        for day in cassandra_db.distinct_days():
            for t in cassandra_db.list_by_day(day):
                w.writerow([t["ts"].isoformat() if c == "ts" else t[c] for c in cassandra_db.COLUMNS])
                n += 1
    print(f"Cassandra: {n} transactions")


def dump_neo4j():
    (OUT / "neo4j_schema.cypher").write_text(";\n".join(neo4j_db.SCHEMA) + ";\n", encoding="utf-8")
    for label in ("Account", "Ticket", "Event", "Transaction"):
        rows = neo4j_db.run(f"MATCH (n:{label}) RETURN properties(n) AS p")
        cols = sorted({k for r in rows for k in r["p"]})
        with open(OUT / f"neo4j_nodes_{label}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(cols)
            for r in rows:
                w.writerow([r["p"].get(c, "") for c in cols])
        print(f"Neo4j: {len(rows)} {label} nodes")
    rels = neo4j_db.run("""MATCH (a)-[r]->(b)
        RETURN type(r) AS type, labels(a)[0] AS from_label, coalesce(a.account_id, a.ticket_id, a.transaction_id) AS from_id,
               labels(b)[0] AS to_label, coalesce(b.account_id, b.ticket_id, b.event_id) AS to_id,
               properties(r) AS props""")
    with open(OUT / "neo4j_relationships.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["type", "from_label", "from_id", "to_label", "to_id", "props"])
        for r in rels:
            w.writerow([r["type"], r["from_label"], r["from_id"], r["to_label"], r["to_id"], r["props"] or ""])
    print(f"Neo4j: {len(rels)} relationships")


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    dump_cassandra()
    dump_neo4j()
