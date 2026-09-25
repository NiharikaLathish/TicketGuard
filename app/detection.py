"""Graph-based fraud detection over the Neo4j graph. Every finding carries a human-readable reason.

  cycles       Cypher path query: a ticket returning to an account that already sold it
  communities  Louvain (Neo4j GDS if installed, else NetworkX) on the TRANSFERRED_TO graph,
               flagging dense groups; enriched with rapid-purchase evidence
  hubs         centrality: distinct-counterparty degree (z-score) + PageRank
  pricing      resale price vs. original face price
"""
import statistics
from collections import defaultdict

import networkx as nx

from app import config
from app.db.neo4j_db import run


# ---------------------------------------------------------------- cycles
def detect_cycles(min_len: int = 2, max_len: int = 6) -> list[dict]:
    rows = run(f"""
        MATCH (a:Account)-[f:TRANSFERRED_TO]->()
        WITH a, f.ticket_id AS tid
        MATCH p = (a)-[rs:TRANSFERRED_TO*{min_len}..{max_len} {{ticket_id: tid}}]->(a)
        RETURN tid AS ticket_id, [n IN nodes(p) | n.account_id] AS accounts,
               [r IN rs | r.price] AS prices
    """)
    seen, out = set(), []
    for r in rows:
        ring = r["accounts"][:-1]
        key = (r["ticket_id"], frozenset(ring))
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "pattern": "circular_resale", "ticket_id": r["ticket_id"], "accounts": ring,
            "length": len(ring),
            "reason": f"Ticket {r['ticket_id'][:8]} was resold around a closed loop of {len(ring)} accounts "
                      f"and returned to its starting account."})
    return out


# ---------------------------------------------------------------- shared graph loading
def _transfer_graph() -> nx.Graph:
    g = nx.Graph()
    for r in run("""MATCH (a:Account)-[r:TRANSFERRED_TO]->(b:Account)
                    RETURN a.account_id AS s, b.account_id AS t, count(r) AS w"""):
        if g.has_edge(r["s"], r["t"]):
            g[r["s"]][r["t"]]["weight"] += r["w"]
        else:
            g.add_edge(r["s"], r["t"], weight=r["w"])
    return g


def _gds_available() -> bool:
    try:
        run("RETURN gds.version() AS v")
        return True
    except Exception:
        return False


def _louvain(g: nx.Graph) -> list[set]:
    """Louvain via GDS when the plugin is present, otherwise NetworkX."""
    if _gds_available():
        try:
            run("CALL gds.graph.drop('tg', false)")
            run("""MATCH (a:Account)-[r:TRANSFERRED_TO]->(b:Account)
                   WITH gds.graph.project('tg', a, b, {}, {undirectedRelationshipTypes: ['*']}) AS g
                   RETURN g.graphName""")
            rows = run("CALL gds.louvain.stream('tg') YIELD nodeId, communityId "
                       "RETURN gds.util.asNode(nodeId).account_id AS id, communityId AS c")
            run("CALL gds.graph.drop('tg', false)")
            comms = defaultdict(set)
            for r in rows:
                comms[r["c"]].add(r["id"])
            return list(comms.values())
        except Exception:
            pass
    return [set(c) for c in nx.community.louvain_communities(g, weight="weight", seed=7)]


# ---------------------------------------------------------------- communities
def detect_communities(min_size: int = 5, min_avg_degree: float = 1.8) -> list[dict]:
    g = _transfer_graph()
    if g.number_of_nodes() == 0:
        return []
    rapid = _rapid_buyers()
    out = []
    for members in _louvain(g):
        if len(members) < min_size:
            continue
        sub = g.subgraph(members)
        avg_deg = 2 * sub.number_of_edges() / len(members)
        rapid_n = len(members & rapid)
        if avg_deg >= min_avg_degree and (rapid_n >= 3 or avg_deg >= 3):
            out.append({
                "pattern": "bot_ring", "accounts": sorted(members), "size": len(members),
                "avg_internal_degree": round(avg_deg, 2), "rapid_buyers": rapid_n,
                "reason": f"Community of {len(members)} accounts trading densely among themselves "
                          f"(avg {avg_deg:.1f} internal links each); {rapid_n} of them bought many tickets "
                          f"for one event within minutes."})
    return sorted(out, key=lambda c: -c["size"])


def _rapid_buyers(min_tickets: int = 6, window_s: int = 300) -> set:
    rows = run("""
        MATCH (x:Transaction {transaction_type:'Purchase'})-[:MADE_BY]->(a:Account),
              (x)-[:INVOLVES]->(:Ticket)-[:BELONGS_TO]->(e:Event)
        WITH a, e, count(x) AS n, min(x.ts) AS t0, max(x.ts) AS t1
        WHERE n >= $n AND (t1 - t0) <= $w
        RETURN DISTINCT a.account_id AS id
    """, n=min_tickets, w=window_s * 1000)
    return {r["id"] for r in rows}


# ---------------------------------------------------------------- hubs
def detect_hubs(z_threshold: float = 4.0, min_degree: int = 20, top: int = 20) -> list[dict]:
    g = _transfer_graph()
    if g.number_of_nodes() == 0:
        return []
    deg = dict(g.degree())
    mean = statistics.mean(deg.values())
    sd = statistics.pstdev(deg.values()) or 1.0
    pr = nx.pagerank(g, weight="weight")
    out = []
    for acc, d in deg.items():
        z = (d - mean) / sd
        if d >= min_degree and z >= z_threshold:
            out.append({
                "pattern": "hub_account", "account_id": acc, "degree": d, "z_score": round(z, 1),
                "pagerank": round(pr[acc], 5),
                "reason": f"Account trades with {d} distinct counterparties (network mean {mean:.1f}, "
                          f"z-score {z:.1f}) - a hub connecting many otherwise unrelated accounts."})
    return sorted(out, key=lambda h: -h["degree"])[:top]


# ---------------------------------------------------------------- pricing
def detect_pricing(ratio: float = 2.0, limit: int = 500) -> list[dict]:
    rows = run("""
        MATCH (x:Transaction {transaction_type:'Resale'})-[:INVOLVES]->(t:Ticket)
        WHERE x.purchase_price > 0 AND x.resale_price >= $ratio * x.purchase_price
        MATCH (x)-[:MADE_BY]->(b:Account)
        RETURN x.transaction_id AS transaction_id, t.ticket_id AS ticket_id, b.account_id AS buyer_id,
               x.purchase_price AS face, x.resale_price AS resale, x.resale_price / x.purchase_price AS r
        ORDER BY r DESC LIMIT $limit
    """, ratio=ratio, limit=limit)
    return [{
        "pattern": "price_manipulation", "transaction_id": r["transaction_id"], "ticket_id": r["ticket_id"],
        "buyer_id": r["buyer_id"], "face_price": r["face"], "resale_price": r["resale"], "ratio": round(r["r"], 2),
        "reason": f"Ticket resold at {r['r']:.1f}x its face price ({r['face']:.2f} -> {r['resale']:.2f})."}
        for r in rows]


# ---------------------------------------------------------------- summary
def summary() -> dict:
    cyc, com, hub, pri = detect_cycles(), detect_communities(), detect_hubs(), detect_pricing()
    flagged = set()
    for c in cyc:
        flagged.update(c["accounts"])
    for c in com:
        flagged.update(c["accounts"])
    for h in hub:
        flagged.add(h["account_id"])
    return {"circular_resale": len(cyc), "bot_rings": len(com), "hub_accounts": len(hub),
            "price_anomalies": len(pri), "flagged_accounts": len(flagged)}


def flagged_account_ids() -> dict[str, set]:
    """account -> set of pattern names (used by evaluation and visualisation)."""
    m = defaultdict(set)
    for c in detect_cycles():
        for a in c["accounts"]:
            m[a].add("circular_resale")
    for c in detect_communities():
        for a in c["accounts"]:
            m[a].add("bot_ring")
    for h in detect_hubs():
        m[h["account_id"]].add("hub_account")
    return m


def visual_graph(pattern: str) -> dict:
    """Nodes/edges (vis-network format) for one detected pattern."""
    flagged = flagged_account_ids()
    if pattern == "all":
        ids = {a for a, p in flagged.items()}
    else:
        ids = {a for a, p in flagged.items() if pattern in p}
    ids = list(ids)[:400]
    if not ids:
        return {"nodes": [], "edges": []}
    edges = run("""MATCH (a:Account)-[r:TRANSFERRED_TO]->(b:Account)
                   WHERE a.account_id IN $ids AND b.account_id IN $ids
                   RETURN a.account_id AS s, b.account_id AS t, count(r) AS n""", ids=ids)
    colors = {"circular_resale": "#e4572e", "bot_ring": "#7b4bd6", "hub_account": "#f2a900"}
    nodes = [{"id": a, "label": a[:6], "title": f"{a}\n{', '.join(sorted(flagged[a]))}",
              "color": colors[sorted(flagged[a])[0]]} for a in ids]
    return {"nodes": nodes,
            "edges": [{"from": e["s"], "to": e["t"], "arrows": "to", "label": str(e["n"]) if e["n"] > 1 else ""}
                      for e in edges]}
