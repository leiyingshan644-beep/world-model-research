import sqlite3
import json

# This module-level variable is patched in tests via monkeypatch
from config import DB_PATH


def get_conn():
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS papers (
            id               TEXT PRIMARY KEY,
            title            TEXT NOT NULL,
            authors          TEXT,
            year             INTEGER,
            venue            TEXT,
            abstract         TEXT,
            arxiv_id         TEXT,
            pdf_url          TEXT,
            pdf_path         TEXT,
            relevance_score  REAL    DEFAULT 0.0,
            relevance_label  TEXT,
            status           TEXT    DEFAULT 'collected'
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS summaries (
            paper_id    TEXT PRIMARY KEY,
            problem     TEXT,
            innovation  TEXT,
            method      TEXT,
            results     TEXT,
            gaps        TEXT,
            my_thoughts TEXT DEFAULT '',
            model_used  TEXT,
            created_at  TEXT,
            FOREIGN KEY (paper_id) REFERENCES papers(id)
        )
    """)
    conn.commit()
    conn.close()


def upsert_paper(paper: dict):
    conn = get_conn()
    conn.execute(
        """INSERT OR IGNORE INTO papers
           (id, title, authors, year, venue, abstract, arxiv_id, pdf_url, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'collected')""",
        (
            paper["id"],
            paper["title"],
            json.dumps(paper.get("authors", [])),
            paper.get("year"),
            paper.get("venue"),
            paper.get("abstract", ""),
            paper.get("arxiv_id"),
            paper.get("pdf_url"),
        ),
    )
    conn.commit()
    conn.close()


def get_papers(venue=None, year=None, label=None, status=None):
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    query = "SELECT * FROM papers WHERE 1=1"
    params = []
    if venue:
        query += " AND venue = ?"
        params.append(venue)
    if year:
        query += " AND year = ?"
        params.append(year)
    if label:
        if isinstance(label, list):
            placeholders = ",".join("?" for _ in label)
            query += f" AND relevance_label IN ({placeholders})"
            params.extend(label)
        else:
            query += " AND relevance_label = ?"
            params.append(label)
    if status:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY relevance_score DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_paper(paper_id: str, **kwargs):
    if not kwargs:
        return
    conn = get_conn()
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [paper_id]
    conn.execute(f"UPDATE papers SET {sets} WHERE id = ?", vals)
    conn.commit()
    conn.close()


def upsert_summary(summary: dict):
    conn = get_conn()
    conn.execute(
        """INSERT OR REPLACE INTO summaries
           (paper_id, problem, innovation, method, results, gaps, model_used, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            summary["paper_id"],
            summary.get("problem", ""),
            summary.get("innovation", ""),
            summary.get("method", ""),
            summary.get("results", ""),
            summary.get("gaps", ""),
            summary.get("model_used", ""),
            summary.get("created_at", ""),
        ),
    )
    conn.commit()
    conn.close()


def get_summary(paper_id: str):
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM summaries WHERE paper_id = ?", (paper_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_my_thoughts(paper_id: str, thoughts: str):
    conn = get_conn()
    conn.execute(
        "UPDATE summaries SET my_thoughts = ? WHERE paper_id = ?",
        (thoughts, paper_id),
    )
    conn.commit()
    conn.close()


def search_papers(query: str):
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    like = f"%{query}%"
    rows = conn.execute(
        """SELECT * FROM papers
           WHERE title LIKE ? OR abstract LIKE ?
           ORDER BY relevance_score DESC""",
        (like, like),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
