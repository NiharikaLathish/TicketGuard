"""Build docs/TicketGuard_Review2_Report.docx from the measured results and the real Git history.

    python -m scripts.make_figures           (diagrams, needs matplotlib)
    python -m scripts.make_review2_report

Yellow boxes in the document mark where a screenshot must be pasted; the last page is a checklist of all of them.
"""
import json
import subprocess
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from app.db import neo4j_db

ROOT = Path(__file__).resolve().parent.parent
FIG = ROOT / "docs" / "figures"
ev = json.loads((ROOT / "dumps" / "evaluation.json").read_text())

NAVY = RGBColor(0x1F, 0x3A, 0x6E)
GREY = RGBColor(0x55, 0x55, 0x55)

doc = Document()
sec = doc.sections[0]
sec.page_width, sec.page_height = Cm(21), Cm(29.7)
sec.left_margin = sec.right_margin = Cm(2.3)
sec.top_margin = Cm(2.2)
sec.bottom_margin = Cm(2.2)

st = doc.styles
st["Normal"].font.name = "Calibri"
st["Normal"].font.size = Pt(11)
st["Normal"].paragraph_format.space_after = Pt(6)
st["Normal"].paragraph_format.line_spacing = 1.15
for name, size in (("Heading 1", 17), ("Heading 2", 13.5), ("Heading 3", 12)):
    h = st[name]
    h.font.name = "Calibri"
    h.font.size = Pt(size)
    h.font.bold = True
    h.font.color.rgb = NAVY
    h.paragraph_format.space_before = Pt(16 if name == "Heading 1" else 10)
    h.paragraph_format.space_after = Pt(6)
    h.paragraph_format.keep_with_next = True

IMAGES: list[tuple[str, str, str]] = []  # (figure id, title, how) for the checklist


# ------------------------------------------------------------------ helpers
def shade(pr, fill):
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    pr.append(shd)


def set_borders(cell, color="C9A227", sz="12", val="dashed"):
    tcPr = cell._tc.get_or_add_tcPr()
    b = OxmlElement("w:tcBorders")
    for edge in ("top", "left", "bottom", "right"):
        e = OxmlElement(f"w:{edge}")
        e.set(qn("w:val"), val)
        e.set(qn("w:sz"), sz)
        e.set(qn("w:color"), color)
        b.append(e)
    tcPr.append(b)


def para(text="", bold=False, italic=False, align=None, size=None, color=None, after=None):
    p = doc.add_paragraph()
    if text:
        r = p.add_run(text)
        r.bold, r.italic = bold, italic
        if size:
            r.font.size = Pt(size)
        if color:
            r.font.color.rgb = color
    if align is not None:
        p.alignment = align
    if after is not None:
        p.paragraph_format.space_after = Pt(after)
    return p


def bullets(items):
    for it in items:
        p = doc.add_paragraph(style="List Bullet")
        p.paragraph_format.space_after = Pt(2)
        if isinstance(it, tuple):
            r = p.add_run(it[0])
            r.bold = True
            p.add_run(it[1])
        else:
            p.add_run(it)


def numbered(items):
    for it in items:
        p = doc.add_paragraph(style="List Number")
        p.paragraph_format.space_after = Pt(2)
        p.add_run(it)


def code(text):
    for line in text.strip("\n").split("\n"):
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.left_indent = Cm(0.3)
        shade(p._p.get_or_add_pPr(), "F1F1EE")
        r = p.add_run(line if line else " ")
        r.font.name = "Consolas"
        r._element.rPr.rFonts.set(qn("w:eastAsia"), "Consolas")
        r.font.size = Pt(8.5)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def table(header, rows, widths, size=9.5, header_fill="DCE4F5"):
    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(header):
        c = t.rows[0].cells[i]
        c.text = ""
        r = c.paragraphs[0].add_run(h)
        r.bold = True
        r.font.size = Pt(size)
        shade(c._tc.get_or_add_tcPr(), header_fill)
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""
            cells[i].paragraphs[0].add_run(str(v)).font.size = Pt(size)
    for row in t.rows:
        for i, w in enumerate(widths):
            row.cells[i].width = Cm(w)
        for c in row.cells:
            for p in c.paragraphs:
                p.paragraph_format.space_after = Pt(1)
    trPr = t.rows[0]._tr.get_or_add_trPr()
    th = OxmlElement("w:tblHeader")
    th.set(qn("w:val"), "true")
    trPr.append(th)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t


def caption(text):
    return para(text, italic=True, align=WD_ALIGN_PARAGRAPH.CENTER, size=9.5, color=GREY, after=10)


def figure(filename, cap, width=16.0):
    doc.add_picture(str(FIG / filename), width=Cm(width))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    caption(cap)


def image_box(fig_id, title, capture, how, size="Full width (about 16 cm)"):
    """A yellow dashed box telling the reader exactly which screenshot to paste here."""
    IMAGES.append((fig_id, title, how))
    t = doc.add_table(rows=1, cols=1)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    c = t.rows[0].cells[0]
    c.width = Cm(16.2)
    shade(c._tc.get_or_add_tcPr(), "FFF6CC")
    set_borders(c)
    c.text = ""
    r = c.paragraphs[0].add_run(f"INSERT IMAGE HERE  |  Figure {fig_id}")
    r.bold = True
    r.font.size = Pt(11)
    r.font.color.rgb = RGBColor(0x8A, 0x5A, 0x00)
    for label, text in (("Image of: ", title), ("What it must show: ", capture), ("How to take it: ", how), ("Size: ", size)):
        q = c.add_paragraph()
        q.paragraph_format.space_after = Pt(1)
        a = q.add_run(label)
        a.bold = True
        a.font.size = Pt(9.5)
        q.add_run(text).font.size = Pt(9.5)
    c.add_paragraph().add_run("\n\n(delete this box after pasting the image)").font.size = Pt(8)
    caption(f"Figure {fig_id}: {title}")


def fill_note(text):
    r = doc.add_paragraph().add_run(text)
    r.font.highlight_color = 7  # yellow
    r.italic = True


def field(paragraph, instr, placeholder="1"):
    """Insert a Word field (each part in its own run, as Word expects)."""
    def run_with(el):
        r = paragraph.add_run()
        r._r.append(el)

    b = OxmlElement("w:fldChar")
    b.set(qn("w:fldCharType"), "begin")
    run_with(b)
    it = OxmlElement("w:instrText")
    it.set(qn("xml:space"), "preserve")
    it.text = f" {instr} "
    run_with(it)
    sep = OxmlElement("w:fldChar")
    sep.set(qn("w:fldCharType"), "separate")
    run_with(sep)
    t = OxmlElement("w:t")
    t.text = placeholder
    run_with(t)
    e = OxmlElement("w:fldChar")
    e.set(qn("w:fldCharType"), "end")
    run_with(e)


def page_break():
    doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


# ------------------------------------------------------------------ footer with page numbers
fp = sec.footer.paragraphs[0]
fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
fr = fp.add_run("TicketGuard  |  Review 2: Database Implementation & Prototype  |  Page ")
fr.font.size = Pt(9)
fr.font.color.rgb = GREY
field(fp, "PAGE")

# ------------------------------------------------------------------ cover
for _ in range(4):
    doc.add_paragraph()
para("TicketGuard: Fraud Detection via", bold=True, size=24, align=WD_ALIGN_PARAGRAPH.CENTER, color=NAVY, after=0)
para("Graph and Column-Store Databases", bold=True, size=24, align=WD_ALIGN_PARAGRAPH.CENTER, color=NAVY, after=26)
para("Review 2: Database Implementation & Prototype", bold=True, size=16, align=WD_ALIGN_PARAGRAPH.CENTER, after=30)
para("BCSE406L - NoSQL Databases", size=13, align=WD_ALIGN_PARAGRAPH.CENTER, after=2)
para("Fall Semester 2026-2027", size=13, align=WD_ALIGN_PARAGRAPH.CENTER, after=2)
para("Faculty: Lydia Jane G", size=13, align=WD_ALIGN_PARAGRAPH.CENTER, after=28)
para("Team Members", bold=True, size=13, align=WD_ALIGN_PARAGRAPH.CENTER, after=2)
para("Niharika Lathish (23BCE2162)", size=13, align=WD_ALIGN_PARAGRAPH.CENTER, after=2)
para("Sivaraj Swetha Srri (23BCE2180)", size=13, align=WD_ALIGN_PARAGRAPH.CENTER, after=30)
para("Source code: https://github.com/NiharikaLathish/TicketGuard", italic=True, size=10.5,
     align=WD_ALIGN_PARAGRAPH.CENTER, color=GREY)
page_break()

# ------------------------------------------------------------------ contents
para("Contents", bold=True, size=17, color=NAVY, after=8)
field(doc.add_paragraph(), 'TOC \\o "1-2" \\h \\z \\u',
      "Table of contents: choose Yes when Word asks to update fields, or right-click here and choose Update Field.")
para("If the list above is empty, click inside it and press F9 (or right-click, Update Field, Update entire table).",
     italic=True, size=9, color=GREY)
page_break()

# ================================================================== 1
doc.add_heading("1. Introduction and Scope of Review 2", 1)
doc.add_heading("1.1 Project recap", 2)
para("TicketGuard is a prototype that detects fraud on ticket resale platforms: circular resale between a few accounts, "
     "coordinated bot groups that grab tickets for an event, accounts that trade with an unusually large number of "
     "others, and resale at abnormal prices. Fraud of this kind involves several accounts and many transactions, so it "
     "is hard to see by looking at one transaction at a time. It is easy to see when the accounts and tickets are "
     "drawn as a network.")
para("The design uses two NoSQL databases, each for what it does best. Apache Cassandra (wide-column) stores the "
     "high-volume transaction events. Neo4j (graph) stores the relationships between accounts, tickets and "
     "transactions, and the fraud detection runs on that graph. The detection is rule and graph based, with no "
     "machine-learning model to train.")
doc.add_heading("1.2 What Review 1 delivered", 2)
para("Review 1 covered the problem statement, literature survey, research gaps, requirements, the justification for using "
     "Cassandra and Neo4j, the system architecture, the initial database schema and the project plan.")
doc.add_heading("1.3 What this report covers", 2)
para("Review 2 is the implementation review. This report documents the working prototype and maps it to the "
     "Review 2 deliverables and marking criteria.")
table(["Review 2 criterion", "Where it is covered in this report"], [
    ["Database implementation: collections, nodes and tables created correctly", "Section 4 (Cassandra tables, Neo4j nodes, constraints and indexes)"],
    ["CRUD operations: insert, update, delete, retrieve", "Section 6, with API screenshots"],
    ["Data modelling quality: embedding/referencing, indexing, partitioning", "Section 4.3 (design decisions and reasons)"],
    ["Functional prototype: core features working", "Sections 7 to 10 (sync, detection, API, web console) and Section 11 (test results)"],
    ["Progress and documentation: code quality, Git usage, technical documentation", "Sections 12 and 13, plus the README and API documentation in the repository"],
], [8.0, 8.4])
table(["Review 2 deliverable", "Status", "Location"], [
    ["Working prototype", "Done", "Sections 7 to 10; run with the steps in Appendix A"],
    ["Source code", "Done", "github.com/NiharikaLathish/TicketGuard"],
    ["Database dump", "Done", "dumps/ in the repository (Cassandra schema and CSV; Neo4j schema, node and relationship CSVs)"],
    ["API documentation", "Done", "docs/API.md, and live Swagger UI at /docs (Section 9)"],
    ["Progress report", "Done", "This document"],
    ["Sample dataset", "Done", "dumps/sample_dataset.csv (50,000 transactions)"],
    ["Intermediate demonstration", "Ready", "Live demo using the web console (Section 10)"],
], [4.4, 2.2, 9.8])

# ================================================================== 2
doc.add_heading("2. Progress Against the Project Plan", 1)
para("The plan in Review 1 had twelve phases. The table shows where each stands at Review 2.")
table(["Phase (Review 1 plan)", "Status", "Evidence"], [
    ["1-3. Problem, literature survey, requirements, database design", "Done in Review 1", "Review 1 report"],
    ["4. Architecture design", "Done", "Section 3"],
    ["5. Synthetic data generation", "Done", "Section 5; generator/generate.py"],
    ["6. Cassandra implementation and CRUD", "Done", "Sections 4.1 and 6"],
    ["7. Neo4j implementation and Cypher queries", "Done", "Sections 4.2 and 8"],
    ["8. Database synchronisation", "Done", "Section 7; automatic every 60 seconds"],
    ["9. Fraud detection implementation", "Done", "Section 8; all four detectors working"],
    ["10. Visualisation", "Done (prototype)", "Section 10"],
    ["11. Testing and performance evaluation", "Started", "Section 11; larger-scale performance testing planned for Review 3"],
    ["12. Final integration and demonstration", "Review 3", "Section 14"],
], [7.2, 3.0, 6.2])
para("Milestones M1 to M8 from the plan are complete (problem, requirements, database design, dataset, Cassandra, Neo4j, "
     "synchronisation, detection). M9 (visualisation and testing) is partly complete, and M10 (final integrated "
     "prototype) is the Review 3 target.")

# ================================================================== 3
doc.add_heading("3. System Architecture", 1)
para("The implemented architecture follows the workflow proposed in Review 1, with one addition: a FastAPI backend sits "
     "in front of both databases and serves the web console.")
figure("fig_architecture.png", "Figure 3.1: Implemented architecture of TicketGuard")
doc.add_heading("3.1 Components", 2)
table(["Component", "Technology", "Role"], [
    ["Data generator", "Python", "Creates normal and fraudulent transactions with ground-truth labels"],
    ["Transaction store", "Apache Cassandra 4.1", "High-volume writes; reads by buyer, ticket, day or id"],
    ["Graph store", "Neo4j 5.26 Community with Graph Data Science plugin", "Accounts, tickets, events and transactions as a connected graph"],
    ["Synchronisation", "Python (app/sync.py, app/sync_worker.py)", "Copies new transactions from Cassandra to Neo4j"],
    ["Detection", "Cypher, Louvain (Neo4j GDS), NetworkX for PageRank and degree statistics", "Finds loops, bot rings, hubs and price anomalies"],
    ["Backend API", "FastAPI (Python 3.11)", "20 REST endpoints with automatic Swagger documentation"],
    ["Web console", "HTML, JavaScript, vis-network", "Shows results, the relationship map and the transaction form"],
    ["Environment", "Docker Compose", "Runs both databases with one command"],
], [3.4, 5.6, 7.4])
doc.add_heading("3.2 Running environment", 2)
para("Both databases run as Docker containers defined in docker-compose.yml. The application runs on Python 3.11. "
     "(Python 3.12 and newer are not supported by the Cassandra driver's default event loop, which is documented in the README.)")
image_box("3.2", "Both database containers running",
          "The terminal output of docker ps showing ticketguard-cassandra with status (healthy) and ticketguard-neo4j with status Up.",
          "Open a terminal, run:  docker ps   then take a screenshot of the terminal window.")

# ================================================================== 4
doc.add_heading("4. Database Implementation", 1)
doc.add_heading("4.1 Cassandra (wide-column store)", 2)
para("The keyspace ticketguard uses SimpleStrategy with replication factor 1, which is appropriate for a single-node "
     "prototype. Cassandra can only filter efficiently on the partition key, so the tables are designed around the "
     "questions the application asks, not around the entities. Review 1 proposed a single transactions table; the "
     "implementation refines it into four tables with identical columns and different keys.")
figure("fig_cassandra_tables.png", "Figure 4.1: The four Cassandra tables, with partition and clustering keys")
para("Example definition (the other three differ only in the key):")
code("""CREATE TABLE transactions_by_buyer (
    transaction_id uuid, event_id uuid, ticket_id uuid, buyer_id uuid, seller_id uuid,
    ts timestamp, purchase_price decimal, resale_price decimal,
    transaction_type text, fraud_pattern text, day text,
    PRIMARY KEY ((buyer_id), ts, transaction_id)
) WITH CLUSTERING ORDER BY (ts DESC, transaction_id ASC);""")
table(["Table", "Partition key", "Clustering", "Used for"], [
    ["transactions_by_id", "transaction_id", "-", "Get, update, delete one transaction"],
    ["transactions_by_buyer", "buyer_id", "ts DESC, transaction_id", "An account's history, newest first"],
    ["transactions_by_ticket", "ticket_id", "ts DESC, transaction_id", "The ownership chain of a ticket"],
    ["transactions_by_day", "day (text, YYYY-MM-DD)", "ts ASC, transaction_id", "Time-window scans; the sync job reads this"],
], [4.0, 3.6, 4.2, 4.6])
image_box("4.2", "The Cassandra keyspace and tables created",
          "The output of DESCRIBE TABLES inside the ticketguard keyspace, listing all four transactions_by_* tables.",
          "Open a terminal and run:  docker exec -it ticketguard-cassandra cqlsh   then type:  USE ticketguard;  then:  DESCRIBE TABLES;   Screenshot the result.")
image_box("4.3", "Data stored in Cassandra, read through a partition key",
          "A CQL query on transactions_by_buyer (or by_ticket) and the rows it returns, newest first.",
          "In the same cqlsh window run a query from docs/queries.md, for example:  SELECT ts, ticket_id, transaction_type, resale_price FROM transactions_by_buyer WHERE buyer_id = <an id from the CSV> LIMIT 5;   Screenshot the query and the result.")

doc.add_heading("4.2 Neo4j (graph store)", 2)
para("The graph has four node labels and six relationship types. A ticket changing hands is stored twice on purpose: "
     "as a Transaction node that records the details, and as a TRANSFERRED_TO relationship between the two accounts "
     "that carries the ticket id, price and time. The relationship is what makes loop detection cheap, because a "
     "traversal can follow one ticket by filtering on that property.")
figure("fig_neo4j_model.png", "Figure 4.4: Neo4j graph model", width=13.5)
table(["Element", "Definition"], [
    ["Nodes", "Account {account_id, is_platform}, Ticket {ticket_id}, Event {event_id}, Transaction {transaction_id, ts, purchase_price, resale_price, transaction_type, fraud_pattern}"],
    ["Relationships", "PURCHASED and SOLD (Account to Ticket), TRANSFERRED_TO (Account to Account, with ticket_id, tx_id, ts, price), INVOLVES (Transaction to Ticket), MADE_BY (Transaction to Account), BELONGS_TO (Ticket to Event)"],
    ["Special node", "One platform account (id 000...001) is the seller on primary-market purchases"],
], [3.0, 13.4])
para("Constraints and indexes created at start-up:")
code("\n".join(neo4j_db.SCHEMA))
image_box("4.5", "Neo4j graph schema as seen in Neo4j Browser",
          "The schema diagram Neo4j draws: Account, Ticket, Event and Transaction nodes with the relationship types between them.",
          "Open http://localhost:7474, log in (user neo4j, password ticketguard123), run:  CALL db.schema.visualization()   then screenshot the graph that appears.")
image_box("4.6", "Data loaded in Neo4j",
          "Node counts by label (Transaction 50000, Ticket 46130, Account 8480, Event 60).",
          "In Neo4j Browser run:  MATCH (n) WHERE n:Account OR n:Ticket OR n:Event OR n:Transaction RETURN labels(n)[0] AS label, count(*) AS nodes ORDER BY nodes DESC   then switch to the Table view and screenshot it.")

doc.add_heading("4.3 Data modelling decisions", 2)
table(["Decision", "Reason"], [
    ["One Cassandra table per query (denormalised, same columns in each)",
     "Cassandra reads are fast only along the partition key. Storing the data four times replaces joins and secondary indexes with single-partition reads. The cost is extra storage and four writes per transaction."],
    ["Day bucket as the partition key of transactions_by_day",
     "A single global time-ordered partition would grow without limit and become a hot spot. One partition per day stays bounded (about 2,000 rows per day in the sample data) and still allows time-range reads."],
    ["Clustering by ts (newest first for buyer and ticket)",
     "History queries return in the order users want with no sorting at read time."],
    ["Referencing, not embedding",
     "Transactions hold the buyer, seller, ticket and event as ids. The details of those entities live in Neo4j as nodes. Nothing is nested inside a transaction row, so a change to an account never requires rewriting transactions."],
    ["Neo4j uniqueness constraints on every id",
     "MERGE is safe to repeat and never creates duplicate nodes, which is what makes the sync idempotent. A constraint also creates an index for lookups."],
    ["Index on Transaction.ts and fraud_pattern, and on the TRANSFERRED_TO ticket_id property",
     "Speeds up time filtering, ground-truth checks and the per-ticket loop search."],
    ["Cassandra keeps the full history, Neo4j keeps only what analysis needs",
     "Cassandra is the system of record; the graph is a derived view that can be rebuilt with a full sync."],
], [5.6, 10.8])

# ================================================================== 5
doc.add_heading("5. Sample Dataset", 1)
para("No real customer data is used. The generator (generator/generate.py) creates 50,000 synthetic transactions over a 30-day "
     "window using a fixed random seed, so the same data can be reproduced. Every transaction carries a fraud_pattern label "
     "for evaluation only; the detectors never read that column.")
table(["Part of the dataset", "Content", "Volume"], [
    ["Normal traffic", "Primary purchases from the platform; honest resales at 0.85 to 1.35 times face value; occasional gifts (transfers)", "47,538 transactions"],
    ["Circular resale", "A ticket passed around a ring of 3 to 5 accounts and back to the first one", "25 rings, 98 accounts"],
    ["Bot rings", "10 bot accounts each buying 6 to 10 tickets for one event within two minutes, forwarding them to a collector account", "6 rings, 66 accounts"],
    ["Hub accounts", "One account trading with 40 to 80 different counterparties", "5 accounts"],
    ["Price manipulation", "Resales at 3 to 8 times the original price", "150 tickets"],
], [3.4, 9.4, 3.6])
para("Loaded into the databases, the dataset gives:")
bullets([
    "Cassandra: 50,000 transactions, stored in each of 4 tables (200,000 rows), across 29 daily partitions.",
    "Neo4j: 8,480 accounts (including one platform account), 46,130 tickets, 60 events, 50,000 transactions and 249,931 relationships (3,870 of them TRANSFERRED_TO).",
])
image_box("5.1", "Sample dataset file",
          "The first 8 to 10 rows of dumps/sample_dataset.csv with the column headers visible (transaction_id, event_id, ticket_id, buyer_id, seller_id, ts, purchase_price, resale_price, transaction_type, fraud_pattern).",
          "Open dumps/sample_dataset.csv in Excel (or VS Code) and screenshot the top of the sheet.")
image_box("5.2", "Loading the dataset",
          "The terminal output of the generator: 'generated 50000 transactions', 'inserted into Cassandra in ...s' and the sync line.",
          "In the project folder run:  python -m generator.generate --transactions 50000 --load --sync --reset   and screenshot the final lines of output.")

# ================================================================== 6
doc.add_heading("6. CRUD Operations", 1)
para("Transactions are managed in Cassandra; accounts and tickets are managed in Neo4j. All operations are exposed through the API.")
table(["Entity (store)", "Create", "Retrieve", "Update", "Delete"], [
    ["Transaction (Cassandra)", "POST /transactions", "GET /transactions/{id}; GET /transactions?buyer_id= or ticket_id= or day=", "PUT /transactions/{id}", "DELETE /transactions/{id}"],
    ["Account (Neo4j)", "POST /accounts", "GET /accounts; GET /accounts/{id}", "PUT /accounts/{id}", "DELETE /accounts/{id}"],
    ["Ticket (Neo4j)", "created by sync", "GET /tickets/{id}/history", "changed by sync", "removed with its last transaction"],
], [3.3, 2.7, 5.1, 2.7, 2.6], size=9)
doc.add_heading("6.1 How writes work", 2)
bullets([
    ("Create: ", "one transaction is written to all four Cassandra tables in a single logged batch, so the tables cannot disagree. Bulk loading uses concurrent asynchronous writes, which are safe to repeat because they are keyed by primary key."),
    ("Update: ", "only price, type and label can change. The key columns (ids and timestamp) are immutable, because changing a partition or clustering key in Cassandra means writing a new row. The update is applied to all four tables and then to the graph."),
    ("Delete: ", "removes the row from all four tables and the transaction from Neo4j. It also removes the ticket, event and accounts that existed only because of that transaction, so no orphan nodes remain."),
    ("Validation: ", "prices must not be negative, the type must be Purchase, Resale or Transfer, and ids must be valid UUIDs. Invalid input returns HTTP 422; unknown ids return 404."),
])
doc.add_heading("6.2 Evidence", 2)
para("The following screenshots show one full lifecycle of a transaction using the Swagger page at http://localhost:8000/docs "
     "(open the endpoint, choose Try it out, paste the body, choose Execute). Use the same transaction for all four so the story is consistent. "
     "Example body for the create step:")
code("""{
  "event_id":  "11111111-1111-1111-1111-111111111111",
  "ticket_id": "22222222-2222-2222-2222-222222222222",
  "buyer_id":  "33333333-3333-3333-3333-333333333333",
  "seller_id": "44444444-4444-4444-4444-444444444444",
  "purchase_price": 100, "resale_price": 140, "transaction_type": "Resale"
}""")
image_box("6.1", "CREATE: POST /transactions",
          "The request body and the response with HTTP status 201 and the new transaction_id.",
          "Swagger page, POST /transactions, Try it out, paste the body above, Execute. Screenshot the request and the response section together. Copy the transaction_id for the next steps.")
image_box("6.2", "RETRIEVE: GET /transactions/{transaction_id}",
          "Status 200 and the same transaction returned, with resale_price 140.",
          "Swagger page, GET /transactions/{transaction_id}, paste the id, Execute, screenshot.")
image_box("6.3", "UPDATE: PUT /transactions/{transaction_id}",
          "The request body {\"resale_price\": 999} and the response showing resale_price 999.",
          "Swagger page, PUT /transactions/{transaction_id}, body  {\"resale_price\": 999}, Execute, screenshot.")
image_box("6.4", "DELETE: DELETE /transactions/{transaction_id}, then GET returns 404",
          "Two things in one image: DELETE returning 204, and a following GET of the same id returning 404 Not Found.",
          "Run DELETE, then GET the same id again. Combine the two screenshots into one image (paste one above the other in Paint or PowerPoint), or insert them as two images.")
image_box("6.5", "Account CRUD in Neo4j",
          "POST /accounts returning 201 with the account, and GET /accounts/{id} returning the same account.",
          "Swagger page, POST /accounts with body {\"name\": \"Test User\"}, then GET /accounts/{account_id}. Screenshot both responses.")

# ================================================================== 7
doc.add_heading("7. Synchronisation from Cassandra to Neo4j", 1)
para("The sync module (app/sync.py) keeps the graph up to date with the transaction store. It works in four steps:")
numbered([
    "Read the watermark (the timestamp of the newest transaction already copied) from a SyncState node in Neo4j.",
    "Read the Cassandra day partitions from the watermark's day up to the latest day, keeping only rows newer than the watermark.",
    "Write them to Neo4j in batches of 2,000 with MERGE statements, which create each node and relationship only if it does not already exist.",
    "Store the new watermark.",
])
para("Because everything is written with MERGE, running a sync twice changes nothing, which the tests confirm. A background worker "
     "(app/sync_worker.py) repeats the sync every 60 seconds; the interval is set with SYNC_INTERVAL_SECONDS and 0 turns it off. "
     "POST /sync triggers an immediate sync, and POST /sync?full=true re-copies everything.")
table(["Measurement", "Result"], [
    ["Initial sync of 50,000 transactions", "about 22 seconds"],
    ["Repeat sync with no new data", "0 records synced"],
    ["A new transaction added through the API", "appears in Neo4j within one sync interval"],
], [8.0, 8.4])
image_box("7.1", "Synchronisation working",
          "POST /sync returning the number of records synced, and (below it) GET /stats showing the same 50,000 transactions in Cassandra and Neo4j.",
          "Swagger page: run POST /sync, screenshot the response; then run GET /stats and screenshot that too (or stack them into one image).")

# ================================================================== 8
doc.add_heading("8. Fraud Detection", 1)
para("All four detectors read the Neo4j graph, and every finding comes with a plain-language reason (the explainability "
     "requirement from Review 1).")
doc.add_heading("8.1 Circular resale", 2)
para("A ticket that leaves an account and returns to it through 2 to 6 transfers is suspicious. The search is restricted to "
     "one ticket at a time by matching on the ticket_id property, so it stays fast on the full graph.")
code("""MATCH (a:Account)-[f:TRANSFERRED_TO]->()
WITH a, f.ticket_id AS tid
MATCH p = (a)-[rs:TRANSFERRED_TO*2..6 {ticket_id: tid}]->(a)
RETURN tid AS ticket, [n IN nodes(p) | n.account_id] AS accounts""")
doc.add_heading("8.2 Coordinated bot rings", 2)
para("Louvain community detection (Neo4j Graph Data Science) groups accounts that trade mostly among themselves. A community is "
     "flagged when it has at least 5 members, an average of at least 1.8 internal links per member, and either 3 or more "
     "members who bought many tickets for one event within minutes, or a very high link density. The rapid-purchase "
     "evidence comes from a Cypher query on transaction timestamps.")
doc.add_heading("8.3 Hub accounts", 2)
para("For each account the number of distinct trading partners is compared with the network average. An account is flagged "
     "when it has at least 20 partners and a z-score of at least 4. PageRank is reported alongside as a second measure of "
     "importance.")
doc.add_heading("8.4 Price manipulation", 2)
para("A resale is flagged when the resale price is at least twice the original price. The threshold is a parameter of the endpoint.")
doc.add_heading("8.5 Results against ground truth", 2)
rows = []
labels = {"circular_resale": "Circular resale (accounts)", "bot_ring": "Bot ring (accounts)",
          "hub_account": "Hub account (accounts)", "price_manipulation": "Price manipulation (tickets)"}
for k, lab in labels.items():
    v = ev[k]
    rows.append([lab, v["expected"], v["found"], v["precision"], v["recall"], f'{v["seconds"]} s'])
table(["Pattern", "Injected", "Found", "Precision", "Recall", "Query time"], rows, [5.4, 2.0, 1.8, 2.3, 2.0, 2.9])
para("The data is synthetic and the fraud patterns are clearly separated from normal traffic, so perfect scores are expected. They "
     "show that each detector finds what was planted and does not flag normal accounts; they do not predict accuracy on real "
     "data. Review 3 will test noisier cases (prices near the threshold, overlapping patterns).", italic=True)
image_box("8.1", "A detected circular-resale ring drawn in Neo4j Browser",
          "A small closed loop of 3 to 5 account nodes joined by TRANSFERRED_TO arrows, with the loop clearly visible.",
          "In Neo4j Browser run:  MATCH p = (a:Account)-[:TRANSFERRED_TO*3..5 {ticket_id: '480a202f-1cde-4b69-b8fb-04f3cbbc04a3'}]->(a) RETURN p LIMIT 1   (if that ticket id does not exist in your data, take any ticket_id from the first row of GET /fraud/cycles). Screenshot the graph view.")
image_box("8.2", "A detected bot ring drawn in Neo4j Browser",
          "A dense cluster of about 11 accounts with many links between them.",
          "Easiest way: use the Bot rings tab of the web console and take the screenshot there (this is the same picture as Figure 10.3, so you may insert that one here instead). In Neo4j Browser you can instead copy the account ids of one item from GET /fraud/communities and run:  MATCH (a:Account)-[r:TRANSFERRED_TO]->(b:Account) WHERE a.account_id IN [ ...ids... ] AND b.account_id IN [ ...ids... ] RETURN a, r, b")
image_box("8.3", "Detection accuracy against ground truth",
          "The terminal table printed by the evaluation script (pattern, expected, found, precision, recall, seconds).",
          "In the project folder run:  python -m scripts.evaluate   and screenshot the output table.")
image_box("8.4", "Detection results returned by the API",
          "The JSON of GET /fraud/summary (counts per pattern) and, below it, one item of GET /fraud/cycles showing the 'reason' text.",
          "Swagger page: run GET /fraud/summary and GET /fraud/cycles; screenshot both responses (stack them into one image).")

# ================================================================== 9
doc.add_heading("9. Backend API", 1)
para("The backend is a FastAPI application (app/main.py) with 20 endpoints. Swagger documentation is generated automatically at "
     "/docs and the full reference is in docs/API.md.")
table(["Group", "Endpoints"], [
    ["System", "GET /health, GET /stats"],
    ["Transactions (Cassandra)", "POST /transactions, GET /transactions/{id}, GET /transactions (by buyer_id, ticket_id or day), PUT /transactions/{id}, DELETE /transactions/{id}"],
    ["Accounts and tickets (Neo4j)", "POST /accounts, GET /accounts, GET /accounts/{id}, PUT /accounts/{id}, DELETE /accounts/{id}, GET /tickets/{id}/history"],
    ["Synchronisation", "POST /sync"],
    ["Fraud detection", "GET /fraud/summary, /fraud/cycles, /fraud/communities, /fraud/hubs, /fraud/pricing, /fraud/graph"],
    ["Web console", "GET /"],
], [4.6, 11.8])
image_box("9.1", "The Swagger documentation page",
          "The full list of endpoints grouped under system, transactions (Cassandra), graph (Neo4j), sync and fraud detection.",
          "Open http://localhost:8000/docs in a browser, zoom the browser out (Ctrl and minus) until all groups are visible, and screenshot the page.")

# ================================================================== 10
doc.add_heading("10. Web Console", 1)
para("The console at http://localhost:8000/ is the visual part of the prototype. It shows the live state of both databases, the "
     "number of findings per fraud type, a relationship map, and a case list where every case has its reason. Selecting a "
     "case highlights that ring on the map. The map can be filtered by pattern. A pop-up form lets a user add a "
     "transaction, which is saved to Cassandra, synced to Neo4j and analysed immediately; two one-click demos (a price "
     "spike and a full circular-resale ring) make the pipeline easy to show.")
image_box("10.1", "The console home page",
          "The whole page: header with Cassandra and Neo4j status and counts, the big flagged-accounts number, the four summary cards, the relationship map and the case list.",
          "Start the app (uvicorn app.main:app), open http://localhost:8000/ and wait 5 seconds for the map to load. Screenshot the full window. If the page is taller than the screen, take it in two parts or zoom the browser out.")
image_box("10.2", "Adding a transaction from the console",
          "The Log transaction pop-up after a successful save, with the confirmation line ('Saved ... to Cassandra and synced ... to Neo4j').",
          "Click Log transaction, choose 'Example: 5x price spike', then Save and analyse. Screenshot the pop-up including the confirmation message. To keep the dataset clean afterwards, press 'Undo added' in the same pop-up.")
image_box("10.3", "Filtering and highlighting a bot ring",
          "The map filtered to Bot rings, with one ring zoomed in and highlighted, and the matching case selected in the list.",
          "Click the Bot rings tab above the map, then click any case in the list on the right. Screenshot the map and the list together.")

# ================================================================== 11
doc.add_heading("11. Testing and Results", 1)
doc.add_heading("11.1 Automated tests", 2)
para("Nineteen automated integration tests (pytest) run against the live databases and all pass. They cover:")
bullets([
    "The health check of both databases.",
    "Full create, retrieve, update and delete lifecycles for transactions (checking every Cassandra table) and accounts.",
    "Input validation and error codes (422, 400, 404), including malformed ids and negative prices.",
    "Result ordering (a buyer's history is newest first).",
    "Sync behaviour: a new transaction reaches the graph, a repeat sync does nothing, and deleting a transaction leaves no orphan nodes.",
    "The background sync: a transaction added through the API reaches Neo4j without anyone calling /sync.",
    "Detection recall and precision against the ground truth, and that every finding has a reason.",
])
image_box("11.1", "Automated test results",
          "The pytest summary line showing 19 passed.",
          "In the project folder run:  pytest -q   and screenshot the terminal when it finishes (about 20 seconds). The 19 count includes Swetha's extra tests (tests/test_extra.py). If only 10 tests exist so far, take this screenshot after her files are merged.")
doc.add_heading("11.2 Manual test cases", 2)
para("A further 17 manual cases (insert, retrieve through each table, update, sync, delete, validation, account CRUD and each detector) "
     "were executed against the running system, with the expected and observed results recorded in docs/test_plan.md. All 17 passed.")
doc.add_heading("11.3 Performance on the prototype dataset", 2)
table(["Operation", "Result"], [
    ["Bulk load into Cassandra (4 tables)", "50,000 transactions in about 97 seconds (about 200,000 row writes)"],
    ["Cassandra to Neo4j sync", "50,000 transactions in about 22 seconds"],
    ["Circular-resale detection", "0.1 seconds"],
    ["Bot-ring detection (Louvain plus rapid-purchase query)", "about 2 seconds"],
    ["Hub detection", "0.3 seconds"],
    ["Price-anomaly query", "0.03 seconds"],
], [7.6, 8.8])
para("These figures were measured on a single laptop with one Cassandra node. They show the prototype works at 50,000 transactions; "
     "they say little about cluster-scale throughput, which is outside the scope of the prototype.", italic=True)

# ================================================================== 12
doc.add_heading("12. Version Control and Code Quality", 1)
para("The source is in a Git repository at https://github.com/NiharikaLathish/TicketGuard. Work was committed in small steps "
     "with descriptive messages, one component at a time.")
log = subprocess.run(["git", "log", "--reverse", "--format=%h|%ad|%s", "--date=short"], cwd=ROOT,
                     capture_output=True, text=True).stdout.strip().split("\n")
table(["Commit", "Date", "Message"], [line.split("|", 2) for line in log if line], [2.0, 2.6, 11.8], size=8.5)
table(["Path", "Contents"], [
    ["app/db/cassandra_db.py, app/db/neo4j_db.py", "Database layers: schema and CRUD for each store"],
    ["app/sync.py, app/sync_worker.py", "Incremental sync and the background worker"],
    ["app/detection.py", "The four fraud detectors"],
    ["app/main.py", "FastAPI endpoints"],
    ["generator/generate.py", "Synthetic data with labelled fraud"],
    ["static/index.html", "Web console"],
    ["scripts/", "Database dump, evaluation and report scripts"],
    ["tests/", "Automated tests"],
    ["docs/", "API reference, query showcase, test plan, this report"],
    ["dumps/", "Sample dataset, ground truth, database exports"],
], [6.0, 10.4], size=9)
para("Code-quality practices: configuration and credentials are kept in a git-ignored .env file (an example file is committed); "
     "database access is separated from the API and detection logic; every detector returns a reason; and inputs are validated.")
doc.add_heading("12.1 Team contribution", 2)
fill_note("[Fill in before submitting: who worked on what. The rows below are suggestions; replace them with the real split.]")
table(["Team member", "Contribution"], [
    ["Niharika Lathish (23BCE2162)", "[e.g. Cassandra and Neo4j schemas, generator, sync, detection, API, web console, Git repository]"],
    ["Sivaraj Swetha Srri (23BCE2180)", "[e.g. query showcase (docs/queries.md), test plan (docs/test_plan.md), extra automated tests]"],
], [5.4, 11.0])
image_box("12.1", "Commit history on GitHub",
          "The list of commits on the main branch of the repository, showing the commit messages and dates.",
          "Open https://github.com/NiharikaLathish/TicketGuard, click 'Commits' (next to the branch name) and screenshot the first page.")
image_box("12.2", "Both team members as contributors",
          "The repository Contributors view (or the commit list) showing commits from Swetha as well as Niharika.",
          "On GitHub open Insights, then Contributors, and screenshot it. Do this only after Swetha has pushed her commits.")

# ================================================================== 13
doc.add_heading("13. Problems Found and How They Were Resolved", 1)
table(["Problem", "Resolution"], [
    ["The single transactions table proposed in Review 1 does not suit Cassandra's query-first modelling.",
     "Replaced by four query-specific tables (Section 4.1)."],
    ["The generator created timestamps up to three days in the future (resale delays added to recent purchases). This broke the sync watermark and the day queries. The automated tests caught it.",
     "Purchases are now generated at least four days before the end of the window."],
    ["Deleting a transaction left the ticket, event and account nodes it had created in Neo4j.",
     "Delete now removes nodes and relationships that only that transaction justified. A test checks it."],
    ["The Cassandra driver has no usable event loop on Python 3.12 and newer.",
     "The project runs on Python 3.11 (documented in the README)."],
    ["Review 1 described the sync as periodic, but the first version only ran when called.",
     "Added a background worker that syncs every 60 seconds, with a test."],
], [8.4, 8.0])

# ================================================================== 14
doc.add_heading("14. Limitations and Plan for Review 3", 1)
doc.add_heading("14.1 Known limitations", 2)
bullets([
    "The incremental sync uses an event-time watermark, so a transaction back-dated to before the newest synced one is not picked up until a full sync (POST /sync?full=true). A marker based on ingestion time would remove this.",
    "The detection thresholds (price ratio 2, hub z-score 4, community density 1.8) are tuned on synthetic data only.",
    "Both databases run as single nodes, so replication and multi-node behaviour are not demonstrated.",
    "Results are perfect on clean synthetic data and should not be read as accuracy on real platforms.",
])
doc.add_heading("14.2 Review 3 plan", 2)
bullets([
    "Performance evaluation at larger volumes (200,000 or more transactions), with insert and query timings.",
    "Noisier fraud scenarios: prices close to the threshold, overlapping patterns, and legitimate high-volume resellers.",
    "Improved visualisation and any changes from Review 2 feedback.",
    "Final documentation, presentation and demonstration.",
])

# ================================================================== 15
doc.add_heading("15. Conclusion", 1)
para("The prototype now does what the Review 1 design set out to do. Cassandra stores 50,000 transactions in tables designed around "
     "the way they are read; Neo4j holds the same activity as a graph; a synchronisation job keeps the two consistent; and four "
     "graph-based detectors find every planted fraud pattern and explain each finding. The API supports full create, read, "
     "update and delete on both databases, and a web console shows the results. The remaining work for Review 3 is evaluation "
     "at larger scale and with harder data, not new core features.")

doc.add_heading("References", 1)
for ref in [
    "[1] L. Akoglu, H. Tong, D. Koutra, \"Graph based anomaly detection and description: a survey\", Data Mining and Knowledge Discovery, 2015 (as cited in Review 1).",
    "[2] Apache Cassandra documentation, Data Modeling. https://cassandra.apache.org/doc/latest/",
    "[3] Neo4j Cypher Manual and Graph Data Science Library (Louvain). https://neo4j.com/docs/",
    "[4] FastAPI documentation. https://fastapi.tiangolo.com/",
    "[5] Review 1 report: TicketGuard, BCSE406L, Fall 2026-2027.",
]:
    para(ref, size=10, after=3)

# ------------------------------------------------------------------ appendix A
page_break()
doc.add_heading("Appendix A: How to run the prototype", 1)
code("""docker compose up -d                       # starts Cassandra and Neo4j (first run downloads about 1 GB)
py -3.11 -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
copy .env.example .env

python -m generator.generate --transactions 50000 --load --sync --reset
uvicorn app.main:app                       # console: http://localhost:8000/   API docs: http://localhost:8000/docs

pytest -q                                  # 19 tests
python -m scripts.evaluate                 # precision / recall against ground truth
python -m scripts.dump                     # exports both databases to dumps/""")

# ------------------------------------------------------------------ appendix B: image checklist
page_break()
doc.add_heading("Appendix B: Image checklist (delete this page before submitting)", 1)
para(f"There are {len(IMAGES)} screenshots to paste. Each yellow box in the report describes its image in detail; this is the summary. "
     "The architecture diagram, the Cassandra table diagram and the Neo4j model diagram are already drawn and inserted.")
table(["Figure", "Screenshot of", "Take it from"],
      [[a, b, c if len(c) < 150 else c[:147] + "..."] for a, b, c in IMAGES], [1.5, 6.0, 8.9], size=8.5)

# ask Word to refresh fields (table of contents, page numbers) when the file is opened
upd = OxmlElement("w:updateFields")
upd.set(qn("w:val"), "true")
doc.settings.element.append(upd)

OUT = ROOT / "docs" / "TicketGuard_Review2_Report.docx"
doc.save(OUT)
print("wrote", OUT, "|", len(IMAGES), "image placeholders")
