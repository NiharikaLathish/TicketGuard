"""Synthetic ticket-transaction generator (normal traffic + injected fraud patterns).

Usage:
    python -m generator.generate --transactions 50000 --seed 42 --load --sync

Fraud patterns injected (ground truth is written to dumps/ground_truth.json and every
fraudulent transaction carries a `fraud_pattern` label):
    circular_resale     tickets passed A->B->C->...->A among a small ring of accounts
    bot_ring            10 bot accounts buying the same event within seconds, funnelling tickets to a collector
    hub_account         accounts trading with dozens of distinct counterparties
    price_manipulation  resales at 3-8x the original price
"""
import argparse
import csv
import json
import random
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import config

ROOT = Path(__file__).resolve().parent.parent


class Gen:
    def __init__(self, seed: int, n_tx: int):
        self.rng = random.Random(seed)
        self.n_tx = n_tx
        self.end = datetime.now(timezone.utc).replace(microsecond=0)
        self.start = self.end - timedelta(days=30)
        self.txs: list[dict] = []
        self.truth = {"circular_resale": [], "bot_ring": [], "hub_account": [], "price_manipulation": []}
        self.events = [{"id": self.uid(), "face": round(self.rng.uniform(30, 300), 2)} for _ in range(60)]
        self.normal_accounts = [self.uid() for _ in range(max(500, n_tx // 6))]

    def uid(self) -> str:
        return str(uuid.UUID(int=self.rng.getrandbits(128), version=4))

    def rand_ts(self) -> datetime:
        return self.start + timedelta(seconds=self.rng.uniform(0, (self.end - self.start).total_seconds() - 7200))

    def add(self, event, ticket, buyer, seller, ts, purchase, resale, kind, pattern="none"):
        self.txs.append({
            "transaction_id": self.uid(), "event_id": event["id"], "ticket_id": ticket, "buyer_id": buyer,
            "seller_id": seller, "ts": ts, "purchase_price": round(purchase, 2), "resale_price": round(resale, 2),
            "transaction_type": kind, "fraud_pattern": pattern})

    def primary(self, event, ticket, buyer, ts, pattern="none"):
        self.add(event, ticket, buyer, config.PLATFORM_ACCOUNT_ID, ts, event["face"], 0.0, "Purchase", pattern)

    # ------------------------------------------------------------ normal
    def normal_traffic(self, budget: int):
        while len(self.txs) < budget:
            ev, buyer, tk = self.rng.choice(self.events), self.rng.choice(self.normal_accounts), self.uid()
            ts = self.rand_ts()
            self.primary(ev, tk, buyer, ts)
            r = self.rng.random()
            if r < 0.04:  # honest resale near face value
                nb = self.rng.choice(self.normal_accounts)
                if nb != buyer:
                    self.add(ev, tk, nb, buyer, ts + timedelta(hours=self.rng.uniform(1, 72)), ev["face"],
                             ev["face"] * self.rng.uniform(0.85, 1.35), "Resale")
            elif r < 0.05:  # gift
                nb = self.rng.choice(self.normal_accounts)
                if nb != buyer:
                    self.add(ev, tk, nb, buyer, ts + timedelta(hours=self.rng.uniform(1, 48)), ev["face"], 0.0, "Transfer")

    # ------------------------------------------------------------ fraud
    def circular(self, n_rings=25):
        for _ in range(n_rings):
            ring = [self.uid() for _ in range(self.rng.randint(3, 5))]
            self.truth["circular_resale"].append(ring)
            for _ in range(self.rng.randint(2, 4)):
                ev, tk, ts = self.rng.choice(self.events), self.uid(), self.rand_ts()
                self.primary(ev, tk, ring[0], ts)
                for i in range(len(ring)):
                    ts += timedelta(minutes=self.rng.uniform(2, 30))
                    seller, buyer = ring[i], ring[(i + 1) % len(ring)]
                    self.add(ev, tk, buyer, seller, ts, ev["face"], ev["face"] * self.rng.uniform(1.0, 1.1),
                             "Resale", "circular_resale")

    def bot_rings(self, n_rings=6, size=10):
        for _ in range(n_rings):
            bots = [self.uid() for _ in range(size)]
            collector = self.uid()
            ev, t0 = self.rng.choice(self.events), self.rand_ts()
            self.truth["bot_ring"].append(bots + [collector])
            for bot in bots:
                for _ in range(self.rng.randint(6, 10)):
                    tk = self.uid()
                    ts = t0 + timedelta(seconds=self.rng.uniform(0, 120))
                    self.primary(ev, tk, bot, ts, "bot_ring")
                    hop1 = self.rng.choice([b for b in bots if b != bot])
                    ts += timedelta(minutes=self.rng.uniform(5, 60))
                    self.add(ev, tk, hop1, bot, ts, ev["face"], 0.0, "Transfer", "bot_ring")
                    ts += timedelta(minutes=self.rng.uniform(5, 60))
                    self.add(ev, tk, collector, hop1, ts, ev["face"], 0.0, "Transfer", "bot_ring")

    def hubs(self, n_hubs=5):
        for _ in range(n_hubs):
            hub = self.uid()
            self.truth["hub_account"].append(hub)
            for cp in self.rng.sample(self.normal_accounts, self.rng.randint(40, 80)):
                ev, tk, ts = self.rng.choice(self.events), self.uid(), self.rand_ts()
                self.primary(ev, tk, hub, ts, "hub_account")
                self.add(ev, tk, cp, hub, ts + timedelta(hours=self.rng.uniform(1, 24)), ev["face"],
                         ev["face"] * self.rng.uniform(1.0, 1.3), "Resale", "hub_account")

    def price_spikes(self, n=150):
        for _ in range(n):
            ev, tk, ts = self.rng.choice(self.events), self.uid(), self.rand_ts()
            a, b = self.rng.sample(self.normal_accounts, 2)
            self.primary(ev, tk, a, ts)
            self.add(ev, tk, b, a, ts + timedelta(hours=self.rng.uniform(1, 24)), ev["face"],
                     ev["face"] * self.rng.uniform(3, 8), "Resale", "price_manipulation")
            self.truth["price_manipulation"].append(tk)

    def build(self):
        self.circular()
        self.bot_rings()
        self.hubs()
        self.price_spikes()
        self.normal_traffic(self.n_tx)
        self.txs.sort(key=lambda t: t["ts"])
        return self.txs


def generate(n_tx: int = 50000, seed: int = 42):
    g = Gen(seed, n_tx)
    return g.build(), g.truth


def write_csv(txs, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(txs[0].keys()))
        w.writeheader()
        for t in txs:
            w.writerow({**t, "ts": t["ts"].isoformat()})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--transactions", type=int, default=50000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--csv", default=str(ROOT / "dumps" / "sample_dataset.csv"))
    ap.add_argument("--load", action="store_true", help="insert into Cassandra")
    ap.add_argument("--sync", action="store_true", help="sync Cassandra -> Neo4j after loading")
    ap.add_argument("--reset", action="store_true", help="wipe both databases first")
    a = ap.parse_args()

    txs, truth = generate(a.transactions, a.seed)
    write_csv(txs, Path(a.csv))
    (ROOT / "dumps").mkdir(exist_ok=True)
    (ROOT / "dumps" / "ground_truth.json").write_text(json.dumps(truth, indent=1), encoding="utf-8")
    fraud = sum(1 for t in txs if t["fraud_pattern"] != "none")
    print(f"generated {len(txs)} transactions ({fraud} fraudulent) -> {a.csv}")

    if a.load:
        from app.db import cassandra_db, neo4j_db
        cassandra_db.init_schema()
        neo4j_db.init_schema()
        if a.reset:
            cassandra_db.truncate_all()
            neo4j_db.clear_graph()
        import time
        t0 = time.time()
        cassandra_db.bulk_insert(txs)
        dt = time.time() - t0
        print(f"inserted into Cassandra in {dt:.1f}s ({len(txs)/dt:.0f} tx/s across 4 tables)")
        if a.sync:
            from app import sync
            print("sync:", sync.run_sync())


if __name__ == "__main__":
    main()
