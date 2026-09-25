"""Draw the three diagrams used in the report into docs/figures/ (needs matplotlib).

    python -m scripts.make_figures
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Circle

OUT = Path(__file__).resolve().parent.parent / "docs" / "figures"
INK, MUTED = "#1c2420", "#6b6f66"
GREEN, GREEN_L = "#14342b", "#e3ede8"
BLUE, BLUE_L = "#2d4a80", "#e4eaf5"
RED, RED_L = "#d2452b", "#fbe6e1"
GOLD, GOLD_L = "#c28a0e", "#f7edd2"
GREY_L = "#eeece6"


def box(ax, x, y, w, h, title, sub="", face=GREY_L, edge=INK, tsize=11, ssize=8.5, bold=True):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.12", fc=face, ec=edge, lw=1.4))
    ax.text(x + w / 2, y + h / 2 + (0.14 if sub else 0), title, ha="center", va="center", fontsize=tsize,
            fontweight="bold" if bold else "normal", color=INK)
    if sub:
        ax.text(x + w / 2, y + h / 2 - 0.2, sub, ha="center", va="center", fontsize=ssize, color=MUTED)


def arrow(ax, p, q, text="", rad=0.0, color=INK, lw=1.5, ls="-", ts=8, off=(0, 0.16)):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle="-|>", mutation_scale=14, lw=lw, color=color, ls=ls,
                                 connectionstyle=f"arc3,rad={rad}"))
    if text:
        ax.text((p[0] + q[0]) / 2 + off[0], (p[1] + q[1]) / 2 + off[1], text, ha="center", va="center", fontsize=ts,
                color=color, bbox=dict(fc="white", ec="none", pad=1.2))


def fig_architecture():
    fig, ax = plt.subplots(figsize=(11, 4.6))
    ax.set_xlim(0, 11)
    ax.set_ylim(0, 4.6)
    ax.axis("off")
    y = 1.5
    box(ax, 0.1, y, 1.7, 1.2, "Synthetic\ngenerator", "Python", GREY_L)
    box(ax, 2.4, y, 1.9, 1.2, "Cassandra", "transaction store", GREEN_L, GREEN)
    box(ax, 4.9, y, 1.5, 1.2, "Sync", "incremental", GREY_L)
    box(ax, 7.0, y, 1.9, 1.2, "Neo4j", "relationship graph", BLUE_L, BLUE)
    box(ax, 9.3, y, 1.6, 1.2, "Detection", "Cypher / Louvain", RED_L, RED)
    for a, b in [(1.8, 2.4), (4.3, 4.9), (6.4, 7.0), (8.9, 9.3)]:
        arrow(ax, (a, y + 0.6), (b, y + 0.6))
    box(ax, 2.4, 3.55, 6.5, 0.8, "FastAPI backend  (20 REST endpoints, Swagger docs)", "", GOLD_L, GOLD, tsize=10.5)
    arrow(ax, (3.35, 3.55), (3.35, 2.7), "CRUD", off=(0.32, 0))
    arrow(ax, (7.95, 3.55), (7.95, 2.7), "graph CRUD + detection", off=(0.95, 0))
    arrow(ax, (5.65, 3.55), (5.65, 2.7), "/sync", off=(0.3, 0), ls="--")
    box(ax, 9.3, 3.55, 1.6, 0.8, "Web console", "", GREY_L, tsize=10)
    arrow(ax, (8.9, 3.95), (9.3, 3.95), "")
    arrow(ax, (10.1, 2.7), (10.1, 3.55), "findings", off=(0.42, 0), ls="--", color=MUTED)
    ax.text(0.95, 1.05, "50,000 normal +\nfraud transactions", ha="center", fontsize=8, color=MUTED)
    ax.text(3.35, 1.05, "4 query tables", ha="center", fontsize=8, color=MUTED)
    ax.text(5.65, 1.05, "background worker\nevery 60 s", ha="center", fontsize=8, color=MUTED)
    ax.text(7.95, 1.05, "8,480 accounts\n46,130 tickets", ha="center", fontsize=8, color=MUTED)
    ax.text(10.1, 1.05, "cycles, bot rings,\nhubs, pricing", ha="center", fontsize=8, color=MUTED)
    fig.savefig(OUT / "fig_architecture.png", dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def fig_cassandra():
    fig, ax = plt.subplots(figsize=(11, 4.9))
    ax.set_xlim(0, 11)
    ax.set_ylim(0, 4.9)
    ax.axis("off")
    tables = [
        ("transactions_by_id", "transaction_id", "-", "Fetch, update or delete\none transaction"),
        ("transactions_by_buyer", "buyer_id", "ts DESC, transaction_id", "An account's purchase\nhistory, newest first"),
        ("transactions_by_ticket", "ticket_id", "ts DESC, transaction_id", "A ticket's ownership\nchain across resales"),
        ("transactions_by_day", "day  (YYYY-MM-DD)", "ts ASC, transaction_id", "Time-window scans;\nused by the sync job"),
    ]
    w, gap = 2.5, 0.28
    for i, (name, pk, ck, use) in enumerate(tables):
        x = 0.1 + i * (w + gap)
        ax.add_patch(FancyBboxPatch((x, 0.5), w, 3.9, boxstyle="round,pad=0.02,rounding_size=0.12", fc="white", ec=GREEN, lw=1.5))
        ax.add_patch(FancyBboxPatch((x, 3.6), w, 0.8, boxstyle="round,pad=0.02,rounding_size=0.12", fc=GREEN, ec=GREEN))
        ax.text(x + w / 2, 4.0, name, ha="center", va="center", color="white", fontsize=9.5, fontweight="bold")
        ax.text(x + 0.15, 3.2, "PARTITION KEY", fontsize=7.5, color=MUTED)
        ax.text(x + 0.15, 2.85, pk, fontsize=10, fontweight="bold", color=RED)
        ax.text(x + 0.15, 2.3, "CLUSTERING", fontsize=7.5, color=MUTED)
        ax.text(x + 0.15, 1.95, ck, fontsize=9, fontweight="bold", color=BLUE)
        ax.text(x + 0.15, 1.35, "ANSWERS", fontsize=7.5, color=MUTED)
        ax.text(x + 0.15, 0.85, use, fontsize=8.5, color=INK, va="center")
    ax.text(5.5, 0.15, "All four tables hold the same columns: transaction_id, event_id, ticket_id, buyer_id, seller_id, ts, "
            "purchase_price, resale_price, transaction_type, fraud_pattern, day",
            ha="center", fontsize=8, color=MUTED)
    fig.savefig(OUT / "fig_cassandra_tables.png", dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def fig_graph_model():
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.set_xlim(0, 10)
    ax.set_ylim(-0.9, 6)
    ax.set_aspect("equal")
    ax.axis("off")
    pos = {"Account": (2.2, 3.4, RED, RED_L), "Ticket": (5.6, 3.4, BLUE, BLUE_L), "Event": (8.6, 3.4, GOLD, GOLD_L),
           "Transaction": (3.9, 0.9, GREEN, GREEN_L)}
    for name, (x, y, ec, fc) in pos.items():
        ax.add_patch(Circle((x, y), 0.78, fc=fc, ec=ec, lw=2))
        ax.text(x, y, name, ha="center", va="center", fontsize=9.5, fontweight="bold", color=INK)
    A, T, E, X = [(pos[k][0], pos[k][1]) for k in ("Account", "Ticket", "Event", "Transaction")]
    arrow(ax, (A[0] + 0.8, A[1] + 0.25), (T[0] - 0.8, T[1] + 0.25), "PURCHASED", rad=-0.18, off=(0, 0.42), ts=9)
    arrow(ax, (A[0] + 0.8, A[1] - 0.25), (T[0] - 0.8, T[1] - 0.25), "SOLD", rad=0.18, off=(0, -0.42), ts=9)
    arrow(ax, (T[0] + 0.8, T[1]), (E[0] - 0.8, E[1]), "BELONGS_TO", ts=9)
    arrow(ax, (X[0] - 0.55, X[1] + 0.55), (A[0] + 0.35, A[1] - 0.72), "MADE_BY", rad=0.0, off=(-0.55, 0.05), ts=9)
    arrow(ax, (X[0] + 0.55, X[1] + 0.55), (T[0] - 0.35, T[1] - 0.72), "INVOLVES", rad=0.0, off=(0.6, 0.05), ts=9)
    # self loop TRANSFERRED_TO on Account
    ax.add_patch(FancyArrowPatch((A[0] - 0.35, A[1] + 0.72), (A[0] + 0.35, A[1] + 0.72), arrowstyle="-|>", mutation_scale=14,
                                 lw=1.6, color=RED, connectionstyle="arc3,rad=-1.9"))
    ax.text(A[0], A[1] + 1.95, "TRANSFERRED_TO", ha="center", fontsize=9, color=RED, fontweight="bold")
    ax.text(A[0], A[1] + 1.68, "{ticket_id, tx_id, ts, price}", ha="center", fontsize=8, color=MUTED)
    ax.text(0.2, -0.75, "Uniqueness constraints: account_id, ticket_id, event_id, transaction_id\n"
            "Indexes: Transaction.ts, Transaction.fraud_pattern, TRANSFERRED_TO.ticket_id", fontsize=8.5, color=MUTED)
    fig.savefig(OUT / "fig_neo4j_model.png", dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    fig_architecture()
    fig_cassandra()
    fig_graph_model()
    print("figures written to", OUT)
