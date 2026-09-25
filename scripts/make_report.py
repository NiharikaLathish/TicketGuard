"""Build docs/TicketGuard_Review2_Progress_Report.docx from the measured results.

    python -m scripts.make_report
"""
import json
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parent.parent
ev = json.loads((ROOT / "dumps" / "evaluation.json").read_text())

doc = Document()
sec = doc.sections[0]
sec.page_width, sec.page_height = Cm(21), Cm(29.7)
for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
    setattr(sec, side, Cm(2.2))

normal = doc.styles["Normal"]
normal.font.name = "Calibri"
normal.font.size = Pt(11)
for name, size in (("Heading 1", 16), ("Heading 2", 13)):
    st = doc.styles[name]
    st.font.name = "Calibri"
    st.font.size = Pt(size)
    st.font.color.rgb = RGBColor(0x1F, 0x3A, 0x6E)


def shade(cell, hex_fill):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    tcPr.append(shd)


def para(text, bold=False, italic=False, align=None, size=None, after=6):
    p = doc.add_paragraph()
    r = p.add_run(text)
    r.bold, r.italic = bold, italic
    if size:
        r.font.size = Pt(size)
    if align:
        p.alignment = align
    p.paragraph_format.space_after = Pt(after)
    return p


def bullets(items):
    for it in items:
        doc.add_paragraph(it, style="List Bullet").paragraph_format.space_after = Pt(2)


def table(header, rows, widths):
    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(header):
        c = t.rows[0].cells[i]
        c.text = ""
        run = c.paragraphs[0].add_run(h)
        run.bold = True
        run.font.size = Pt(10)
        shade(c, "DCE4F5")
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""
            cells[i].paragraphs[0].add_run(str(v)).font.size = Pt(10)
    for row in t.rows:
        for i, w in enumerate(widths):
            row.cells[i].width = Cm(w)
    doc.add_paragraph().paragraph_format.space_after = Pt(4)


# ------------------------------------------------------------------ title page
for _ in range(5):
    doc.add_paragraph()
para("TicketGuard", bold=True, size=30, align=WD_ALIGN_PARAGRAPH.CENTER, after=2)
para("Fraud Detection via Graph and Column-Store Databases", size=16, align=WD_ALIGN_PARAGRAPH.CENTER, after=24)
para("Review 2: Database Implementation & Prototype", bold=True, size=14, align=WD_ALIGN_PARAGRAPH.CENTER, after=24)
para("BCSE406L - NoSQL Databases", align=WD_ALIGN_PARAGRAPH.CENTER, after=2)
para("Fall Semester 2026-2027", align=WD_ALIGN_PARAGRAPH.CENTER, after=2)
para("Faculty: Lydia Jane G", align=WD_ALIGN_PARAGRAPH.CENTER, after=24)
para("Niharika Lathish (23BCE2162)", bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, after=2)
para("Sivaraj Swetha Srri (23BCE2180)", bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, after=24)
para("Source code: https://github.com/NiharikaLathish/TicketGuard", italic=True, align=WD_ALIGN_PARAGRAPH.CENTER)
doc.add_page_break()

# ------------------------------------------------------------------ 1
doc.add_heading("1. Summary of Progress", 1)
para("Review 1 finalised the problem, requirements, database choice, architecture and initial schema. Review 2 delivers the "
     "working prototype: both databases are implemented, populated with a 50,000-transaction synthetic dataset, "
     "synchronised, and exposed through a REST API. All four planned fraud detectors run on the Neo4j graph, and every "
     "finding carries a plain-language reason. The prototype is checked by 10 automated tests, all passing.")
table(["Plan phase (Review 1)", "Status", "Evidence"], [
    ["5. Synthetic data generation", "Done", "generator/generate.py; dumps/sample_dataset.csv"],
    ["6. Cassandra implementation + CRUD", "Done", "app/db/cassandra_db.py; 4 query tables"],
    ["7. Neo4j implementation + Cypher", "Done", "app/db/neo4j_db.py; constraints, indexes"],
    ["8. Database synchronisation", "Done", "app/sync.py; incremental, idempotent"],
    ["9. Fraud detection (cycle, community, centrality)", "Done", "app/detection.py; evaluation below"],
    ["10. Visualisation", "Done (prototype)", "static/index.html fraud console"],
    ["11. Testing & performance", "Started", "10 pytest tests; timings in section 7"],
    ["12. Final integration & demonstration", "Review 3", "-"],
], [6.5, 3.0, 6.9])

# ------------------------------------------------------------------ 2
doc.add_heading("2. Architecture as Implemented", 1)
para("Synthetic generator  ->  Cassandra  ->  Sync module  ->  Neo4j  ->  Graph algorithms  ->  Fraud findings  ->  "
     "Visualisation", bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
bullets([
    "Both databases run in Docker (Cassandra 4.1, Neo4j 5.26 Community with the Graph Data Science plugin).",
    "A FastAPI service (Python 3.11) is the single backend: transaction CRUD goes to Cassandra, account and ticket "
    "CRUD goes to Neo4j, and detection endpoints query Neo4j.",
    "Cassandra is the system of record for transactions. Neo4j is a derived, relationship-oriented view built by the "
    "sync module.",
])

# ------------------------------------------------------------------ 3
doc.add_heading("3. Data Modelling", 1)
doc.add_heading("3.1 Cassandra: one table per query", 2)
para("Review 1 proposed a single transactions table. Cassandra tables should be designed around the queries they serve, "
     "so this was refined into four tables with identical columns and different keys:")
table(["Table", "Primary key", "Query served"], [
    ["transactions_by_id", "(transaction_id)", "Point lookup, update, delete"],
    ["transactions_by_buyer", "((buyer_id), ts DESC, transaction_id)", "An account's purchase history, newest first"],
    ["transactions_by_ticket", "((ticket_id), ts DESC, transaction_id)", "A ticket's ownership chain"],
    ["transactions_by_day", "((day), ts, transaction_id)", "Time-window scans; used by the sync module"],
], [4.6, 6.0, 5.8])
bullets([
    "Partitioning: the day bucket keeps time-series partitions bounded, and buyer/ticket partitions are naturally small.",
    "Clustering by timestamp gives ordered, range-friendly reads without sorting at query time.",
    "Writes: single writes use a logged batch across the four tables for atomicity. The bulk loader uses concurrent "
    "asynchronous writes; each write is idempotent by primary key.",
])
doc.add_heading("3.2 Neo4j graph model", 2)
table(["Element", "Definition"], [
    ["Nodes", "Account, Ticket, Event, Transaction (SyncState holds the sync watermark)"],
    ["Relationships", "PURCHASED, SOLD, TRANSFERRED_TO {ticket_id, tx_id, ts, price}, INVOLVES, MADE_BY, BELONGS_TO"],
    ["Constraints", "Unique account_id, ticket_id, event_id, transaction_id"],
    ["Indexes", "Transaction.ts, Transaction.fraud_pattern, TRANSFERRED_TO.ticket_id"],
], [3.4, 13.0])
para("TRANSFERRED_TO carries the ticket id so that a ticket's movement between accounts can be followed directly, which is "
     "what makes the circular-resale query cheap.")

# ------------------------------------------------------------------ 4
doc.add_heading("4. Implementation", 1)
doc.add_heading("4.1 Synthetic dataset", 2)
para("The generator produces 50,000 transactions over 30 days: 47,538 normal (primary purchases, honest resales close to "
     "face value, gifts) and 2,462 fraudulent, labelled with a fraud_pattern column. A ground-truth file records the "
     "injected entities for evaluation.")
table(["Injected pattern", "Description", "Count"], [
    ["circular_resale", "Ticket passed around a ring of 3-5 accounts and back to the start", "25 rings"],
    ["bot_ring", "10 bot accounts buy one event within two minutes, funnel tickets to a collector", "6 rings"],
    ["hub_account", "Account trading with 40-80 distinct counterparties", "5 accounts"],
    ["price_manipulation", "Resale at 3-8x face price", "150 tickets"],
], [3.8, 9.8, 2.8])
doc.add_heading("4.2 CRUD operations", 2)
table(["Entity (store)", "Create", "Retrieve", "Update", "Delete"], [
    ["Transaction (Cassandra)", "POST /transactions", "GET /transactions/{id}; by buyer, ticket or day",
     "PUT /transactions/{id}", "DELETE /transactions/{id}"],
    ["Account (Neo4j)", "POST /accounts", "GET /accounts, /accounts/{id}", "PUT /accounts/{id}", "DELETE /accounts/{id}"],
    ["Ticket (Neo4j)", "via sync", "GET /tickets/{id}/history", "via sync", "via transaction delete"],
], [3.6, 2.8, 4.4, 2.8, 2.8])
para("Updating or deleting a transaction updates all four Cassandra tables and the graph, so the two databases stay "
     "consistent. Request bodies are validated (transaction type, non-negative prices).")
doc.add_heading("4.3 Synchronisation", 2)
para("The sync module reads Cassandra day partitions from the stored watermark onwards and upserts them into Neo4j with "
     "MERGE, in batches of 2,000. It is idempotent: a second run reports zero new records. A full re-sync is available "
     "with full=true.")
doc.add_heading("4.4 Fraud detection", 2)
table(["Pattern", "Method", "Explanation produced"], [
    ["Circular resale", "Cypher variable-length path over TRANSFERRED_TO restricted to one ticket, returning to the start",
     "Ticket looped through N accounts and returned to its origin"],
    ["Bot ring", "Louvain community detection (Neo4j GDS) + internal density + rapid-purchase evidence",
     "Group size, links per member, number of rapid buyers"],
    ["Hub account", "Distinct-counterparty degree z-score, plus PageRank", "Degree versus network mean and z-score"],
    ["Price manipulation", "Resale price >= 2x face price", "Ratio and prices"],
], [3.2, 7.2, 6.0])
doc.add_heading("4.5 Backend API and visualisation", 2)
para("The FastAPI service exposes 20 endpoints with automatic Swagger documentation at /docs (full list in the API "
     "documentation). A browser console at / shows summary counts, a colour-coded graph of detected rings, and a table of "
     "reasons.")
para("[Insert screenshot of the fraud console here]", italic=True, align=WD_ALIGN_PARAGRAPH.CENTER)

# ------------------------------------------------------------------ 5
doc.add_heading("5. Results", 1)
doc.add_heading("5.1 Data volumes", 2)
table(["Store", "Contents"], [
    ["Cassandra", "50,000 transactions in each of 4 tables (200,000 rows)"],
    ["Neo4j", "8,484 accounts, 46,132 tickets, 62 events, 50,000 transactions, 249,937 relationships "
              "(3,870 TRANSFERRED_TO)"],
], [3.4, 13.0])
doc.add_heading("5.2 Detection accuracy against ground truth", 2)
rows = []
labels = {"circular_resale": "Circular resale (accounts)", "bot_ring": "Bot ring (accounts)",
          "hub_account": "Hub account (accounts)", "price_manipulation": "Price manipulation (tickets)"}
for k, lab in labels.items():
    v = ev[k]
    rows.append([lab, v["expected"], v["found"], v["precision"], v["recall"], f'{v["seconds"]}s'])
table(["Pattern", "Injected", "Found", "Precision", "Recall", "Query time"], rows, [5.4, 2.0, 1.8, 2.3, 2.0, 2.9])
para("Note: the data is synthetic and the fraud patterns are cleanly separated from normal traffic, so perfect scores are "
     "expected and do not predict performance on real data. Their purpose is to show that each detector finds what was "
     "planted and does not flag normal accounts. Review 3 will add noisier scenarios (near-threshold prices, "
     "overlapping patterns) to test the thresholds.", italic=True)
doc.add_heading("5.3 Performance", 2)
table(["Operation", "Result"], [
    ["Bulk load into Cassandra (4 tables)", "50,000 transactions in about 97 s (about 200,000 row writes)"],
    ["Cassandra to Neo4j sync", "50,000 transactions in about 22 s"],
    ["Detection queries", "0.03 s to 1.5 s each on the full graph"],
], [6.4, 10.0])
para("Measured on a single laptop with one Cassandra node, so throughput figures illustrate correct operation, not "
     "Cassandra's cluster-scale capacity.", italic=True)

# ------------------------------------------------------------------ 6
doc.add_heading("6. Testing", 1)
para("Ten automated integration tests (pytest) run against the live databases and pass:")
bullets([
    "Health check of both databases.",
    "Transaction CRUD lifecycle, including that every query table returns the row and that update and delete propagate.",
    "Input validation and error codes (422, 400, 404).",
    "Account CRUD lifecycle in Neo4j.",
    "Sync: a new transaction reaches the graph, a second sync is a no-op, deleting the transaction removes it from the graph.",
    "Four detection tests asserting recall and precision thresholds against the ground truth, and that every "
    "finding has an explanation.",
])

# ------------------------------------------------------------------ 7
doc.add_heading("7. Issues Found and Resolved", 1)
table(["Issue", "Resolution"], [
    ["Single transactions table from Review 1 does not suit Cassandra's query-first modelling",
     "Replaced with four query-specific tables (section 3.1)."],
    ["Generator produced timestamps up to 3 days in the future (resale delays added to recent purchases), which broke "
     "the sync watermark and day queries; found by the automated tests",
     "Purchases are now generated at least 4 days before the end of the window."],
    ["cassandra-driver has no usable event loop on Python 3.12+ without extra C libraries",
     "Project runs on Python 3.11; documented in the README."],
], [8.4, 8.0])

# ------------------------------------------------------------------ 8
doc.add_heading("8. Version Control and Documentation", 1)
para("Source is hosted at https://github.com/NiharikaLathish/TicketGuard with incremental commits per component "
     "(setup, Cassandra layer, Neo4j layer, sync, generator, detection, API, tests, documentation, fixes). "
     "Deliverables in the repository:")
bullets([
    "Working prototype and source code: app/, generator/, static/, scripts/",
    "Database dump: dumps/ (Cassandra schema and transactions CSV; Neo4j schema, node and relationship CSVs; the "
    "sample dataset and ground truth)",
    "API documentation: docs/API.md and the live Swagger UI at /docs",
    "README with setup and run instructions",
])

# ------------------------------------------------------------------ 9
doc.add_heading("9. Known Limitations and Plan for Review 3", 1)
bullets([
    "Sync uses an event-time watermark, so a back-dated transaction inserted after newer ones is not picked up by an "
    "incremental sync; run a full sync in that case. Review 3: switch to an ingestion-time marker.",
    "Detection thresholds (2x price, z-score 4, density 1.8) are tuned on synthetic data only.",
    "Single-node databases; no replication or multi-node measurements yet.",
    "Review 3: performance evaluation at larger volumes (200k+ transactions), noisier fraud scenarios, "
    "polished visualisation, final documentation and presentation.",
])

out = ROOT / "docs" / "TicketGuard_Review2_Progress_Report.docx"
doc.save(out)
print("wrote", out)
