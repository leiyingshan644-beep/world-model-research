import sqlite3
import json

# This module-level variable is patched in tests via monkeypatch
from config import DB_PATH


def get_conn():
    return sqlite3.connect(DB_PATH, timeout=30)


def init_db():
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS papers (
                id               TEXT PRIMARY KEY,
                title            TEXT NOT NULL,
                authors          TEXT,
                year             INTEGER,
                venue            TEXT,
                source           TEXT    DEFAULT '',
                doi              TEXT    DEFAULT '',
                abstract         TEXT,
                arxiv_id         TEXT,
                pdf_url          TEXT,
                pdf_path         TEXT,
                relevance_score  REAL    DEFAULT 0.0,
                relevance_label  TEXT,
                status           TEXT    DEFAULT 'collected'
            )
        """)
        # Migrate existing databases that predate source/doi columns
        for col, defn in [("source", "TEXT DEFAULT ''"), ("doi", "TEXT DEFAULT ''")]:
            try:
                c.execute(f"ALTER TABLE papers ADD COLUMN {col} {defn}")
            except Exception:
                pass
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
        # Tags
        c.execute("""
            CREATE TABLE IF NOT EXISTS tags (
                name TEXT PRIMARY KEY
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS paper_tags (
                paper_id TEXT NOT NULL,
                tag_name TEXT NOT NULL,
                PRIMARY KEY (paper_id, tag_name),
                FOREIGN KEY (paper_id) REFERENCES papers(id),
                FOREIGN KEY (tag_name) REFERENCES tags(name)
            )
        """)
        # Manual boost column migration
        try:
            c.execute("ALTER TABLE papers ADD COLUMN manual_boost REAL DEFAULT 0.0")
        except Exception:
            pass
        # Viewed column migration
        try:
            c.execute("ALTER TABLE papers ADD COLUMN viewed INTEGER DEFAULT 0")
        except Exception:
            pass
        conn.commit()
    finally:
        conn.close()


def upsert_paper(paper: dict):
    conn = get_conn()
    try:
        conn.execute(
            """INSERT OR IGNORE INTO papers
               (id, title, authors, year, venue, source, doi,
                abstract, arxiv_id, pdf_url, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'collected')""",
            (
                paper["id"],
                paper["title"],
                json.dumps(paper.get("authors", [])),
                paper.get("year"),
                paper.get("venue"),
                paper.get("source", ""),
                paper.get("doi", ""),
                paper.get("abstract", ""),
                paper.get("arxiv_id"),
                paper.get("pdf_url"),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_papers(venue=None, year=None, label=None, status=None):
    conn = get_conn()
    try:
        conn.row_factory = sqlite3.Row
        query = "SELECT * FROM papers WHERE 1=1"
        params = []
        if venue is not None:
            query += " AND venue = ?"
            params.append(venue)
        if year is not None:
            query += " AND year = ?"
            params.append(year)
        if label is not None:
            if isinstance(label, list):
                if label:  # non-empty list
                    placeholders = ",".join("?" for _ in label)
                    query += f" AND relevance_label IN ({placeholders})"
                    params.extend(label)
            else:
                query += " AND relevance_label = ?"
                params.append(label)
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY (relevance_score + COALESCE(manual_boost, 0)) DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def batch_update_papers(updates: list[tuple]):
    """updates: list of (paper_id, score, label) — single transaction for speed."""
    conn = get_conn()
    try:
        conn.executemany(
            "UPDATE papers SET relevance_score = ?, relevance_label = ? WHERE id = ?",
            [(score, label, pid) for pid, score, label in updates],
        )
        conn.commit()
    finally:
        conn.close()


def update_paper(paper_id: str, **kwargs):
    if not kwargs:
        return
    conn = get_conn()
    try:
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        vals = list(kwargs.values()) + [paper_id]
        conn.execute(f"UPDATE papers SET {sets} WHERE id = ?", vals)
        conn.commit()
    finally:
        conn.close()


def upsert_summary(summary: dict):
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO summaries
               (paper_id, problem, innovation, method, results, gaps, model_used, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(paper_id) DO UPDATE SET
                   problem=excluded.problem,
                   innovation=excluded.innovation,
                   method=excluded.method,
                   results=excluded.results,
                   gaps=excluded.gaps,
                   model_used=excluded.model_used,
                   created_at=excluded.created_at""",
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
    finally:
        conn.close()


def get_summary(paper_id: str):
    conn = get_conn()
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM summaries WHERE paper_id = ?", (paper_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_my_thoughts(paper_id: str, thoughts: str):
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE summaries SET my_thoughts = ? WHERE paper_id = ?",
            (thoughts, paper_id),
        )
        conn.commit()
    finally:
        conn.close()


def add_tag_to_paper(paper_id: str, tag_name: str):
    conn = get_conn()
    try:
        conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag_name,))
        conn.execute(
            "INSERT OR IGNORE INTO paper_tags (paper_id, tag_name) VALUES (?, ?)",
            (paper_id, tag_name),
        )
        conn.commit()
    finally:
        conn.close()


def remove_tag_from_paper(paper_id: str, tag_name: str):
    conn = get_conn()
    try:
        conn.execute(
            "DELETE FROM paper_tags WHERE paper_id = ? AND tag_name = ?",
            (paper_id, tag_name),
        )
        conn.commit()
    finally:
        conn.close()


def get_tags_for_paper(paper_id: str) -> list:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT tag_name FROM paper_tags WHERE paper_id = ? ORDER BY tag_name",
            (paper_id,),
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


def get_all_tags() -> list:
    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT t.name, COUNT(pt.paper_id) as count
            FROM tags t
            LEFT JOIN paper_tags pt ON t.name = pt.tag_name
            GROUP BY t.name
            ORDER BY count DESC, t.name
        """).fetchall()
        return [{"name": r[0], "count": r[1]} for r in rows]
    finally:
        conn.close()


def delete_tag_globally(tag_name: str) -> list[str]:
    """Delete a tag and all its paper associations. Returns list of affected paper_ids."""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT paper_id FROM paper_tags WHERE tag_name = ?", (tag_name,)
        ).fetchall()
        affected = [r[0] for r in rows]
        conn.execute("DELETE FROM paper_tags WHERE tag_name = ?", (tag_name,))
        conn.execute("DELETE FROM tags WHERE name = ?", (tag_name,))
        conn.commit()
        return affected
    finally:
        conn.close()


def restore_tag(tag_name: str, paper_ids: list[str]):
    """Restore a deleted tag to a list of papers (undo support)."""
    conn = get_conn()
    try:
        conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag_name,))
        conn.executemany(
            "INSERT OR IGNORE INTO paper_tags (paper_id, tag_name) VALUES (?, ?)",
            [(pid, tag_name) for pid in paper_ids],
        )
        conn.commit()
    finally:
        conn.close()


def get_papers_by_tag(tag_name: str) -> list:
    conn = get_conn()
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT p.* FROM papers p
            JOIN paper_tags pt ON p.id = pt.paper_id
            WHERE pt.tag_name = ?
            ORDER BY (p.relevance_score + COALESCE(p.manual_boost, 0)) DESC
        """, (tag_name,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def search_papers(query: str):
    conn = get_conn()
    try:
        conn.row_factory = sqlite3.Row
        like = f"%{query}%"
        rows = conn.execute(
            """SELECT * FROM papers
               WHERE title LIKE ? OR abstract LIKE ?
               ORDER BY relevance_score DESC""",
            (like, like),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
