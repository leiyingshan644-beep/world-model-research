# World Model Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a 5-stage CLI pipeline (collect → filter → download → summarize → browse) for researching world model papers from NeurIPS/ICML/ICLR/CVPR/CoRL (2021–2025).

**Architecture:** Five independent Python scripts share a SQLite database on a HIKSEMI U disk. Each script can be run standalone. A lightweight Flask app provides read/write browsing. All code and data live under `/Volumes/HIKSEMI/world-model-research/`.

**Tech Stack:** Python 3.9, sqlite3, semanticscholar, arxiv, requests, pdfplumber, openai (OpenAI-compatible client), Flask, pytest

---

## File Map

| File | Responsibility |
|---|---|
| `config.py` | All constants: paths, API keys, venues, keywords |
| `utils/__init__.py` | Empty package marker |
| `utils/db.py` | All SQLite reads/writes for `papers` and `summaries` tables |
| `utils/pdf_parser.py` | Extract plain text from a PDF file |
| `collect.py` | Fetch paper metadata from Semantic Scholar + FIB-Lab GitHub |
| `filter.py` | Keyword relevance scoring + interactive CLI labeling |
| `download.py` | Download PDFs from arXiv or fallback url, update DB |
| `summarize.py` | Call DeepSeek/Qwen API with PDF text, store structured summary |
| `browse.py` | Flask app: list/search/detail/edit-thoughts/open-PDF |
| `requirements.txt` | Pinned dependencies |
| `README.md` | Setup guide + one-command examples |
| `tests/test_db.py` | Unit tests for utils/db.py |
| `tests/test_filter.py` | Unit tests for score_paper() |
| `tests/test_download.py` | Unit tests for download_pdf() |
| `tests/test_summarize.py` | Unit tests for summarize_paper() |
| `tests/test_browse.py` | Flask test-client tests for browse.py |

---

## Task 1: Project Scaffold

**Files:**
- Create: `requirements.txt`
- Create: `config.py`
- Create: `utils/__init__.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: Create `requirements.txt`**

```
requests==2.32.5
semanticscholar==0.11.0
arxiv==2.4.0
pandas==2.3.3
pdfplumber==0.11.4
flask==3.1.0
openai==1.75.0
beautifulsoup4==4.14.3
lxml==6.0.2
pytest==8.3.5
```

- [ ] **Step 2: Install dependencies**

```bash
cd /Volumes/HIKSEMI/world-model-research
pip3 install -r requirements.txt
```

Expected: All packages install without error. `pdfplumber` and `openai` are new installs.

- [ ] **Step 3: Create `config.py`**

```python
import os

BASE_DIR = "/Volumes/HIKSEMI/world-model-research"
DB_PATH  = os.path.join(BASE_DIR, "papers.db")
PDF_DIR  = os.path.join(BASE_DIR, "pdfs")

# AI interface (OpenAI-compatible)
LLM_BASE_URL = "https://api.deepseek.com/v1"   # replace with Qwen URL if needed
LLM_API_KEY  = "your-api-key-here"              # fill in before using summarize.py
LLM_MODEL    = "deepseek-chat"

# Semantic Scholar (optional — higher rate limit with key)
S2_API_KEY = ""

TARGET_VENUES = ["neurips", "icml", "iclr", "cvpr", "corl"]
YEAR_RANGE    = (2021, 2025)

KEYWORDS = [
    "world model",
    "generative world model",
    "world foundation model",
    "dreamer",
    "PlaNet",
    "TD-MPC",
    "model-based RL",
    "video prediction world model",
    "embodied world model",
]
```

- [ ] **Step 4: Create package markers**

Create `utils/__init__.py` and `tests/__init__.py` as empty files.

- [ ] **Step 5: Initialize git repo and commit scaffold**

```bash
cd /Volumes/HIKSEMI/world-model-research
git init
git add requirements.txt config.py utils/__init__.py tests/__init__.py
git commit -m "chore: project scaffold"
```

Expected: `Initialized empty Git repository` then commit succeeds.

---

## Task 2: Database Layer

**Files:**
- Create: `utils/db.py`
- Create: `tests/test_db.py`

- [ ] **Step 1: Write `tests/test_db.py`**

```python
import os
import tempfile
import pytest

_TEMP_DB = tempfile.mktemp(suffix=".db")

@pytest.fixture(autouse=True)
def temp_db(monkeypatch):
    import utils.db as db_module
    monkeypatch.setattr(db_module, "DB_PATH", _TEMP_DB)
    db_module.init_db()
    yield
    if os.path.exists(_TEMP_DB):
        os.remove(_TEMP_DB)

def _paper(id="p1", venue="neurips", year=2023, label=None):
    return {
        "id": id, "title": f"Title {id}", "authors": ["Alice"],
        "year": year, "venue": venue,
        "abstract": "A world model paper.", "arxiv_id": id, "pdf_url": None,
    }

def test_upsert_and_get():
    from utils.db import upsert_paper, get_papers
    upsert_paper(_paper())
    papers = get_papers()
    assert len(papers) == 1
    assert papers[0]["title"] == "Title p1"

def test_upsert_is_idempotent():
    from utils.db import upsert_paper, get_papers
    upsert_paper(_paper())
    upsert_paper(_paper())
    assert len(get_papers()) == 1

def test_filter_by_venue():
    from utils.db import upsert_paper, get_papers
    upsert_paper(_paper("a", venue="neurips"))
    upsert_paper(_paper("b", venue="icml"))
    assert len(get_papers(venue="neurips")) == 1

def test_filter_by_label():
    from utils.db import upsert_paper, update_paper, get_papers
    upsert_paper(_paper("a"))
    update_paper("a", relevance_label="high")
    assert len(get_papers(label="high")) == 1
    assert len(get_papers(label="mid")) == 0

def test_update_paper():
    from utils.db import upsert_paper, update_paper, get_papers
    upsert_paper(_paper())
    update_paper("p1", relevance_score=0.9, status="downloaded")
    p = get_papers()[0]
    assert p["relevance_score"] == 0.9
    assert p["status"] == "downloaded"

def test_summary_roundtrip():
    from utils.db import upsert_paper, upsert_summary, get_summary
    upsert_paper(_paper())
    upsert_summary({
        "paper_id": "p1", "problem": "P", "innovation": "I",
        "method": "M", "results": "R", "gaps": "G",
        "model_used": "deepseek-chat", "created_at": "2026-01-01T00:00:00",
    })
    s = get_summary("p1")
    assert s["problem"] == "P"
    assert s["my_thoughts"] == ""

def test_update_my_thoughts():
    from utils.db import upsert_paper, upsert_summary, update_my_thoughts, get_summary
    upsert_paper(_paper())
    upsert_summary({"paper_id": "p1", "problem": "", "innovation": "",
                    "method": "", "results": "", "gaps": "",
                    "model_used": "m", "created_at": "2026-01-01T00:00:00"})
    update_my_thoughts("p1", "very interesting!")
    assert get_summary("p1")["my_thoughts"] == "very interesting!"

def test_search_papers():
    from utils.db import upsert_paper, search_papers
    upsert_paper({"id": "z", "title": "DreamerV3 World Model", "authors": [],
                  "year": 2024, "venue": "iclr",
                  "abstract": "latent world model for RL", "arxiv_id": "z", "pdf_url": None})
    assert len(search_papers("dreamer")) == 1
    assert len(search_papers("transformer")) == 0
```

- [ ] **Step 2: Run tests to confirm they all fail**

```bash
cd /Volumes/HIKSEMI/world-model-research
python3 -m pytest tests/test_db.py -v
```

Expected: `ModuleNotFoundError: No module named 'utils.db'` (all fail).

- [ ] **Step 3: Create `utils/db.py`**

```python
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
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
python3 -m pytest tests/test_db.py -v
```

Expected: 8 tests pass, 0 fail.

- [ ] **Step 5: Commit**

```bash
git add utils/db.py tests/test_db.py
git commit -m "feat: SQLite database layer with full CRUD"
```

---

## Task 3: PDF Parser

**Files:**
- Create: `utils/pdf_parser.py`
- Create: `tests/test_pdf_parser.py`

- [ ] **Step 1: Write `tests/test_pdf_parser.py`**

```python
import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock


def test_extract_returns_string():
    from utils.pdf_parser import extract_text
    mock_page = MagicMock()
    mock_page.extract_text.return_value = "Hello world model paper."
    mock_pdf = MagicMock()
    mock_pdf.__enter__ = lambda s: s
    mock_pdf.__exit__ = MagicMock(return_value=False)
    mock_pdf.pages = [mock_page]
    with patch("pdfplumber.open", return_value=mock_pdf):
        result = extract_text("/fake/path.pdf")
    assert "Hello world model paper." in result


def test_extract_respects_max_chars():
    from utils.pdf_parser import extract_text
    long_text = "A" * 20000
    mock_page = MagicMock()
    mock_page.extract_text.return_value = long_text
    mock_pdf = MagicMock()
    mock_pdf.__enter__ = lambda s: s
    mock_pdf.__exit__ = MagicMock(return_value=False)
    mock_pdf.pages = [mock_page]
    with patch("pdfplumber.open", return_value=mock_pdf):
        result = extract_text("/fake/path.pdf", max_chars=100)
    assert len(result) == 100


def test_extract_handles_none_page_text():
    from utils.pdf_parser import extract_text
    mock_page = MagicMock()
    mock_page.extract_text.return_value = None
    mock_pdf = MagicMock()
    mock_pdf.__enter__ = lambda s: s
    mock_pdf.__exit__ = MagicMock(return_value=False)
    mock_pdf.pages = [mock_page]
    with patch("pdfplumber.open", return_value=mock_pdf):
        result = extract_text("/fake/path.pdf")
    assert result == ""
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python3 -m pytest tests/test_pdf_parser.py -v
```

Expected: `ModuleNotFoundError: No module named 'utils.pdf_parser'`

- [ ] **Step 3: Create `utils/pdf_parser.py`**

```python
import pdfplumber

MAX_CHARS = 12000  # ~4k tokens; enough context for most LLMs


def extract_text(pdf_path: str, max_chars: int = MAX_CHARS) -> str:
    parts = []
    total = 0
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
            remaining = max_chars - total
            parts.append(text[:remaining])
            total += len(text)
            if total >= max_chars:
                break
    return "\n".join(parts)[:max_chars]
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
python3 -m pytest tests/test_pdf_parser.py -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add utils/pdf_parser.py tests/test_pdf_parser.py
git commit -m "feat: PDF text extractor with char limit"
```

---

## Task 4: Collect Module

**Files:**
- Create: `collect.py`
- Create: `tests/test_collect.py`

- [ ] **Step 1: Write `tests/test_collect.py`**

```python
from unittest.mock import patch, MagicMock


def test_fiblabs_parses_arxiv_links():
    from collect import fetch_from_fiblabs
    fake_readme = """
## Papers
| [DreamerV3](https://arxiv.org/abs/2301.04589) | NeurIPS 2023 |
| [TD-MPC2](https://arxiv.org/abs/2310.16828) | ICLR 2024 |
"""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.text = fake_readme
    with patch("requests.get", return_value=mock_resp):
        papers = fetch_from_fiblabs()
    assert len(papers) == 2
    ids = {p["arxiv_id"] for p in papers}
    assert "2301.04589" in ids
    assert "2310.16828" in ids


def test_fiblabs_handles_network_error():
    from collect import fetch_from_fiblabs
    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.status_code = 404
    with patch("requests.get", return_value=mock_resp):
        papers = fetch_from_fiblabs()
    assert papers == []


def test_collect_deduplicates_by_id(tmp_path, monkeypatch):
    import utils.db as db_module
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    db_module.init_db()

    fake_paper = {
        "id": "2301.04589", "title": "DreamerV3", "authors": [],
        "year": 2023, "venue": "neurips", "abstract": "world model",
        "arxiv_id": "2301.04589", "pdf_url": None,
    }

    with patch("collect.fetch_from_fiblabs", return_value=[fake_paper, fake_paper]):
        with patch("collect.fetch_from_s2", return_value=[]):
            from collect import collect
            collect()

    papers = db_module.get_papers()
    assert len(papers) == 1
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python3 -m pytest tests/test_collect.py -v
```

Expected: `ModuleNotFoundError: No module named 'collect'`

- [ ] **Step 3: Create `collect.py`**

```python
import argparse
import re
import requests
from semanticscholar import SemanticScholar
from config import TARGET_VENUES, YEAR_RANGE, KEYWORDS, S2_API_KEY
from utils.db import init_db, upsert_paper

VENUE_MAP = {
    "neurips": ["NeurIPS", "Neural Information Processing Systems", "neurips"],
    "icml":    ["ICML", "International Conference on Machine Learning", "icml"],
    "iclr":    ["ICLR", "International Conference on Learning Representations", "iclr"],
    "cvpr":    ["CVPR", "Computer Vision and Pattern Recognition", "cvpr"],
    "corl":    ["CoRL", "Conference on Robot Learning", "corl"],
}

FIBLABS_URL = (
    "https://raw.githubusercontent.com/tsinghua-fib-lab/world-model/main/README.md"
)


def _match_venue(venue_str: str):
    vl = (venue_str or "").lower()
    for key, aliases in VENUE_MAP.items():
        if any(a.lower() in vl for a in aliases):
            return key
    return None


def fetch_from_s2(keyword: str, venues: list, year_range: tuple) -> list:
    sch = SemanticScholar(api_key=S2_API_KEY or None)
    papers = []
    try:
        results = sch.search_paper(
            keyword,
            year=f"{year_range[0]}-{year_range[1]}",
            fields=["title", "authors", "year", "venue", "abstract",
                    "externalIds", "openAccessPdf"],
            limit=100,
        )
    except Exception as e:
        print(f"  S2 error for '{keyword}': {e}")
        return []

    for p in results:
        matched = _match_venue(p.venue)
        if matched not in venues:
            continue
        arxiv_id = (p.externalIds or {}).get("ArXiv")
        pdf_url = None
        if p.openAccessPdf:
            pdf_url = p.openAccessPdf.get("url")
        if not pdf_url and arxiv_id:
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"
        paper_id = arxiv_id or f"s2:{p.paperId}"
        papers.append({
            "id":       paper_id,
            "title":    p.title or "",
            "authors":  [a.name for a in (p.authors or [])],
            "year":     p.year,
            "venue":    matched,
            "abstract": p.abstract or "",
            "arxiv_id": arxiv_id,
            "pdf_url":  pdf_url,
        })
    return papers


def fetch_from_fiblabs() -> list:
    try:
        resp = requests.get(FIBLABS_URL, timeout=15)
    except requests.RequestException as e:
        print(f"Warning: FIB-Lab fetch failed: {e}")
        return []
    if not resp.ok:
        print(f"Warning: FIB-Lab returned {resp.status_code}")
        return []
    pattern = re.compile(
        r"\[([^\]]+)\]\(https://arxiv\.org/abs/([0-9]+\.[0-9]+)"
    )
    papers = []
    for m in pattern.finditer(resp.text):
        title, arxiv_id = m.group(1), m.group(2)
        papers.append({
            "id":       arxiv_id,
            "title":    title,
            "authors":  [],
            "year":     None,
            "venue":    None,
            "abstract": "",
            "arxiv_id": arxiv_id,
            "pdf_url":  f"https://arxiv.org/pdf/{arxiv_id}",
        })
    return papers


def collect(venues=None, year=None):
    init_db()
    target_venues = venues or TARGET_VENUES
    year_range = (year, year) if year else YEAR_RANGE

    all_papers: dict = {}

    for kw in KEYWORDS:
        print(f"  S2: '{kw}' ...")
        for p in fetch_from_s2(kw, target_venues, year_range):
            all_papers[p["id"]] = p

    print("  FIB-Lab repo ...")
    for p in fetch_from_fiblabs():
        if p["id"] not in all_papers:
            all_papers[p["id"]] = p

    for p in all_papers.values():
        upsert_paper(p)

    print(f"Done. {len(all_papers)} papers written to DB.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collect world model paper metadata")
    parser.add_argument("--venue", help="Single venue, e.g. neurips")
    parser.add_argument("--year", type=int, help="Single year, e.g. 2024")
    args = parser.parse_args()
    collect(
        venues=[args.venue] if args.venue else None,
        year=args.year,
    )
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
python3 -m pytest tests/test_collect.py -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add collect.py tests/test_collect.py
git commit -m "feat: collect module (Semantic Scholar + FIB-Lab)"
```

---

## Task 5: Filter Module

**Files:**
- Create: `filter.py`
- Create: `tests/test_filter.py`

- [ ] **Step 1: Write `tests/test_filter.py`**

```python
def test_score_high_relevance():
    from filter import score_paper
    paper = {
        "title": "DreamerV3: A Generative World Model for RL",
        "abstract": "We propose a world foundation model for model-based RL exploration.",
    }
    assert score_paper(paper) > 0.5


def test_score_zero_for_unrelated():
    from filter import score_paper
    paper = {
        "title": "Attention is All You Need",
        "abstract": "A transformer architecture for natural language translation tasks.",
    }
    assert score_paper(paper) == 0.0


def test_score_is_capped_at_one():
    from filter import score_paper
    paper = {
        "title": "world model world model dreamer planet td-mpc",
        "abstract": "world model generative world model world foundation model dreamer",
    }
    assert score_paper(paper) <= 1.0
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python3 -m pytest tests/test_filter.py -v
```

Expected: `ModuleNotFoundError: No module named 'filter'`

- [ ] **Step 3: Create `filter.py`**

```python
import argparse
from utils.db import get_papers, update_paper

# Keyword weights — higher = more central to "world model" research
_WEIGHTS = {
    "world model":           3.0,
    "generative world model": 4.0,
    "world foundation model": 4.0,
    "model-based rl":        2.0,
    "dreamer":               2.5,
    "planet":                1.5,
    "td-mpc":                2.0,
    "video prediction":      1.5,
    "embodied world model":  3.0,
}
_MAX_RAW = sum(_WEIGHTS.values())  # normalisation denominator


def score_paper(paper: dict) -> float:
    text = f"{paper.get('title', '')} {paper.get('abstract', '')}".lower()
    raw = sum(w for kw, w in _WEIGHTS.items() if kw in text)
    return min(raw / _MAX_RAW, 1.0)


def run_filter(auto: bool = False, review: bool = False):
    papers = get_papers()
    if review:
        papers = [p for p in papers if p["relevance_label"] is None]

    # Score all
    for p in papers:
        s = score_paper(p)
        update_paper(p["id"], relevance_score=s)
        p["relevance_score"] = s

    if auto:
        print(f"Scored {len(papers)} papers.")
        return

    unlabeled = sorted(
        [p for p in papers if p["relevance_label"] is None],
        key=lambda x: x["relevance_score"],
        reverse=True,
    )
    print(f"\n{len(unlabeled)} papers to label.")
    print("Keys: [h]igh  [m]id  [l]ow  [s]kip  [q]uit\n")

    label_map = {"h": "high", "m": "mid", "l": "low", "s": "skip"}

    for p in unlabeled:
        venue = (p.get("venue") or "?").upper()
        year  = p.get("year") or "?"
        score = p.get("relevance_score", 0.0)
        abstract_preview = (p.get("abstract") or "")[:200]
        print(f"[{venue} {year}] score={score:.2f}")
        print(f"  {p['title']}")
        if abstract_preview:
            print(f"  {abstract_preview}...")
        choice = input("  Label: ").strip().lower()
        if choice == "q":
            break
        label = label_map.get(choice)
        if label:
            update_paper(p["id"], relevance_label=label)
        else:
            print("  (invalid — skipped)")

    print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Score and label paper relevance")
    parser.add_argument("--auto",   action="store_true", help="Score only, no interactive prompt")
    parser.add_argument("--review", action="store_true", help="Only show unlabeled papers")
    args = parser.parse_args()
    run_filter(auto=args.auto, review=args.review)
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
python3 -m pytest tests/test_filter.py -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add filter.py tests/test_filter.py
git commit -m "feat: filter module with keyword scoring and interactive labeling"
```

---

## Task 6: Download Module

**Files:**
- Create: `download.py`
- Create: `tests/test_download.py`

- [ ] **Step 1: Write `tests/test_download.py`**

```python
import os
import tempfile
from unittest.mock import patch, MagicMock


def test_skips_existing_file():
    from download import download_pdf
    with tempfile.TemporaryDirectory() as tmpdir:
        dest = os.path.join(tmpdir, "neurips", "2023", "test123.pdf")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        open(dest, "wb").close()
        paper = {"id": "test123", "arxiv_id": "test123",
                 "pdf_url": None, "venue": "neurips", "year": 2023}
        _, status = download_pdf(paper, tmpdir)
        assert status == "exists"


def test_returns_no_url_when_no_links():
    from download import download_pdf
    with tempfile.TemporaryDirectory() as tmpdir:
        paper = {"id": "s2:abc", "arxiv_id": None,
                 "pdf_url": None, "venue": "icml", "year": 2023}
        _, status = download_pdf(paper, tmpdir)
        assert status == "no_url"


def test_downloads_successfully():
    from download import download_pdf
    with tempfile.TemporaryDirectory() as tmpdir:
        paper = {"id": "2301.00001", "arxiv_id": "2301.00001",
                 "pdf_url": None, "venue": "neurips", "year": 2023}
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.headers = {"content-type": "application/pdf"}
        mock_resp.iter_content = lambda chunk_size: [b"%PDF-1.4 fake"]
        with patch("requests.get", return_value=mock_resp):
            path, status = download_pdf(paper, tmpdir)
        assert status == "downloaded"
        assert os.path.exists(path)


def test_falls_back_to_pdf_url():
    from download import download_pdf
    with tempfile.TemporaryDirectory() as tmpdir:
        paper = {"id": "s2:xyz", "arxiv_id": None,
                 "pdf_url": "https://example.com/paper.pdf",
                 "venue": "cvpr", "year": 2022}
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.headers = {"content-type": "application/pdf"}
        mock_resp.iter_content = lambda chunk_size: [b"%PDF-1.4 fake"]
        with patch("requests.get", return_value=mock_resp):
            path, status = download_pdf(paper, tmpdir)
        assert status == "downloaded"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python3 -m pytest tests/test_download.py -v
```

Expected: `ModuleNotFoundError: No module named 'download'`

- [ ] **Step 3: Create `download.py`**

```python
import argparse
import os
import time
import requests
from config import PDF_DIR
from utils.db import get_papers, update_paper


def download_pdf(paper: dict, pdf_dir: str) -> tuple:
    """Return (local_path_or_None, status_string)."""
    venue = (paper.get("venue") or "unknown").lower()
    year  = str(paper.get("year") or "unknown")
    dest_dir = os.path.join(pdf_dir, venue, year)
    os.makedirs(dest_dir, exist_ok=True)

    file_id = paper.get("arxiv_id") or paper["id"].replace("s2:", "s2_")
    dest_path = os.path.join(dest_dir, f"{file_id}.pdf")

    if os.path.exists(dest_path):
        return dest_path, "exists"

    urls = []
    if paper.get("arxiv_id"):
        urls.append(f"https://arxiv.org/pdf/{paper['arxiv_id']}")
    if paper.get("pdf_url") and paper["pdf_url"] not in urls:
        urls.append(paper["pdf_url"])
    if not urls:
        return None, "no_url"

    for url in urls:
        try:
            resp = requests.get(url, timeout=30, stream=True)
            content_type = resp.headers.get("content-type", "")
            if resp.ok and "pdf" in content_type.lower():
                with open(dest_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)
                return dest_path, "downloaded"
        except requests.RequestException:
            continue

    return None, "failed"


def run_download(high_only: bool = False, limit: int = None):
    if high_only:
        papers = get_papers(label="high")
    else:
        all_papers = get_papers()
        papers = [p for p in all_papers if p.get("relevance_label") != "skip"]

    if limit:
        papers = papers[:limit]

    print(f"Downloading {len(papers)} papers...")
    downloaded = skipped = failed = 0

    for i, p in enumerate(papers, 1):
        path, status = download_pdf(p, PDF_DIR)
        prefix = f"[{i}/{len(papers)}]"
        if status == "downloaded":
            update_paper(p["id"], pdf_path=path, status="downloaded")
            print(f"{prefix} ✓ {p['title'][:60]}")
            downloaded += 1
            time.sleep(1)  # polite delay for arXiv
        elif status == "exists":
            if not p.get("pdf_path"):
                update_paper(p["id"], pdf_path=path, status="downloaded")
            print(f"{prefix} = {p['title'][:60]} (already exists)")
            skipped += 1
        else:
            print(f"{prefix} ✗ {p['title'][:60]} ({status})")
            failed += 1

    print(f"\nDone: {downloaded} downloaded, {skipped} skipped, {failed} failed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download paper PDFs")
    parser.add_argument("--high",  action="store_true", help="Only download high-relevance papers")
    parser.add_argument("--limit", type=int, help="Max papers to download this run")
    args = parser.parse_args()
    run_download(high_only=args.high, limit=args.limit)
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
python3 -m pytest tests/test_download.py -v
```

Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add download.py tests/test_download.py
git commit -m "feat: download module with arXiv priority and fallback"
```

---

## Task 7: Summarize Module

**Files:**
- Create: `summarize.py`
- Create: `tests/test_summarize.py`

- [ ] **Step 1: Write `tests/test_summarize.py`**

```python
import json
import os
import tempfile
from unittest.mock import patch, MagicMock


def test_returns_no_pdf_when_path_missing():
    from summarize import summarize_paper
    paper = {"id": "x", "pdf_path": "/nonexistent/path.pdf"}
    summary, status = summarize_paper(paper)
    assert status == "no_pdf"
    assert summary is None


def test_returns_no_pdf_when_path_is_none():
    from summarize import summarize_paper
    paper = {"id": "x", "pdf_path": None}
    summary, status = summarize_paper(paper)
    assert status == "no_pdf"
    assert summary is None


def test_returns_structured_summary():
    from summarize import summarize_paper
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(b"fake pdf content")
        pdf_path = f.name
    try:
        paper = {"id": "2301.04589", "pdf_path": pdf_path}
        fake_json = json.dumps({
            "problem":    "World models lack long-horizon consistency.",
            "innovation": "New latent recurrent architecture.",
            "method":     "RSSM with discrete latents.",
            "results":    "SOTA on Atari and DM Control.",
            "gaps":       "Slow training; limited 3D understanding.",
        })
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value \
            .choices[0].message.content = fake_json
        with patch("utils.pdf_parser.extract_text", return_value="some paper text"):
            with patch("summarize.OpenAI", return_value=mock_client):
                summary, status = summarize_paper(paper)
        assert status == "ok"
        assert summary["paper_id"] == "2301.04589"
        assert summary["problem"] == "World models lack long-horizon consistency."
        assert "model_used" in summary
        assert "created_at" in summary
    finally:
        os.unlink(pdf_path)


def test_strips_markdown_fences_from_llm_output():
    from summarize import summarize_paper
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(b"fake")
        pdf_path = f.name
    try:
        paper = {"id": "abc", "pdf_path": pdf_path}
        fake_json = json.dumps({"problem":"P","innovation":"I","method":"M","results":"R","gaps":"G"})
        wrapped = f"```json\n{fake_json}\n```"
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value \
            .choices[0].message.content = wrapped
        with patch("utils.pdf_parser.extract_text", return_value="text"):
            with patch("summarize.OpenAI", return_value=mock_client):
                summary, status = summarize_paper(paper)
        assert status == "ok"
        assert summary["problem"] == "P"
    finally:
        os.unlink(pdf_path)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python3 -m pytest tests/test_summarize.py -v
```

Expected: `ModuleNotFoundError: No module named 'summarize'`

- [ ] **Step 3: Create `summarize.py`**

```python
import argparse
import json
import os
from datetime import datetime, timezone

from openai import OpenAI

from config import LLM_BASE_URL, LLM_API_KEY, LLM_MODEL
from utils.db import get_papers, upsert_summary, update_paper
from utils.pdf_parser import extract_text

_PROMPT = """\
You are a research paper analyst. Read the paper text below and return ONLY a \
valid JSON object with exactly these five string keys:

  problem     — The core problem addressed (2-3 sentences)
  innovation  — Key innovation vs. prior work (2-3 sentences)
  method      — Main technical approach (3-5 sentences)
  results     — Key experimental results (2-3 sentences)
  gaps        — Limitations and open problems (2-3 sentences)

Return ONLY the JSON object. No markdown fences, no explanation.

Paper text:
{text}
"""


def summarize_paper(paper: dict) -> tuple:
    """Return (summary_dict, status_str). Status is 'ok', 'no_pdf', or 'empty_pdf'."""
    pdf_path = paper.get("pdf_path")
    if not pdf_path or not os.path.exists(pdf_path):
        return None, "no_pdf"

    text = extract_text(pdf_path)
    if not text.strip():
        return None, "empty_pdf"

    client = OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)
    resp = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": _PROMPT.format(text=text)}],
        temperature=0.1,
    )
    raw = resp.choices[0].message.content.strip()

    # Strip markdown code fences if model wrapped output
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    data = json.loads(raw)
    summary = {
        "paper_id":   paper["id"],
        "problem":    data.get("problem", ""),
        "innovation": data.get("innovation", ""),
        "method":     data.get("method", ""),
        "results":    data.get("results", ""),
        "gaps":       data.get("gaps", ""),
        "model_used": LLM_MODEL,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return summary, "ok"


def run_summarize(labels: str = None, paper_id: str = None):
    if paper_id:
        clean_id = paper_id.replace("arxiv:", "")
        papers = [p for p in get_papers() if p["id"] == clean_id]
    elif labels:
        label_list = [l.strip() for l in labels.split(",")]
        papers = []
        for label in label_list:
            papers.extend(get_papers(label=label))
    else:
        papers = get_papers(status="downloaded")

    papers = [p for p in papers if p.get("pdf_path")]
    print(f"Summarizing {len(papers)} papers...")

    ok = failed = 0
    for i, p in enumerate(papers, 1):
        print(f"[{i}/{len(papers)}] {p['title'][:60]}...")
        summary, status = summarize_paper(p)
        if status == "ok":
            upsert_summary(summary)
            update_paper(p["id"], status="summarized")
            print("  ✓")
            ok += 1
        else:
            print(f"  ✗ {status}")
            failed += 1

    print(f"\nDone: {ok} summarized, {failed} failed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI summarization of downloaded papers")
    parser.add_argument("--label",    help="Comma-separated labels, e.g. high or high,mid")
    parser.add_argument("--id",  dest="paper_id", help="Summarize a single paper, e.g. arxiv:2301.04589")
    args = parser.parse_args()
    run_summarize(labels=args.label, paper_id=args.paper_id)
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
python3 -m pytest tests/test_summarize.py -v
```

Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add summarize.py tests/test_summarize.py
git commit -m "feat: summarize module with DeepSeek/Qwen OpenAI-compatible API"
```

---

## Task 8: Browse Flask App

**Files:**
- Create: `browse.py`
- Create: `tests/test_browse.py`

- [ ] **Step 1: Write `tests/test_browse.py`**

```python
import pytest
from unittest.mock import patch


@pytest.fixture
def client():
    from browse import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _paper(**kwargs):
    base = {
        "id": "2301.04589", "title": "DreamerV3", "venue": "neurips",
        "year": 2023, "relevance_label": "high", "status": "summarized",
        "relevance_score": 0.85, "abstract": "A world model paper.",
        "pdf_path": "/tmp/fake.pdf",
    }
    base.update(kwargs)
    return base


def test_index_returns_200(client):
    with patch("browse.get_papers", return_value=[]):
        resp = client.get("/")
    assert resp.status_code == 200


def test_index_shows_paper_title(client):
    with patch("browse.get_papers", return_value=[_paper()]):
        resp = client.get("/")
    assert b"DreamerV3" in resp.data


def test_index_search_calls_search_papers(client):
    with patch("browse.search_papers", return_value=[]) as mock_search:
        client.get("/?q=dreamer")
    mock_search.assert_called_once_with("dreamer")


def test_paper_detail_200(client):
    paper = _paper()
    summary = {
        "paper_id": "2301.04589", "problem": "P", "innovation": "I",
        "method": "M", "results": "R", "gaps": "G", "my_thoughts": "",
    }
    with patch("browse.get_papers", return_value=[paper]):
        with patch("browse.get_summary", return_value=summary):
            resp = client.get("/paper/2301.04589")
    assert resp.status_code == 200
    assert b"DreamerV3" in resp.data
    assert b"Innovation" in resp.data


def test_paper_detail_404_for_unknown(client):
    with patch("browse.get_papers", return_value=[]):
        resp = client.get("/paper/nonexistent-id")
    assert resp.status_code == 404


def test_save_thoughts_updates_db(client):
    with patch("browse.update_my_thoughts") as mock_update:
        resp = client.post(
            "/save_thoughts/2301.04589",
            json={"thoughts": "very promising direction"},
            content_type="application/json",
        )
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    mock_update.assert_called_once_with("2301.04589", "very promising direction")
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
python3 -m pytest tests/test_browse.py -v
```

Expected: `ModuleNotFoundError: No module named 'browse'`

- [ ] **Step 3: Create `browse.py`**

```python
import os
import subprocess

from flask import Flask, render_template_string, request, jsonify

from utils.db import get_papers, get_summary, search_papers, update_my_thoughts

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Templates (inline — no separate template files needed)
# ---------------------------------------------------------------------------

_LIST_HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>World Model Papers</title>
<style>
  body{font-family:sans-serif;max-width:1200px;margin:0 auto;padding:20px}
  .filters{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap;align-items:center}
  .filters select,.filters input{padding:6px 10px;border:1px solid #ccc;border-radius:4px}
  .filters input{flex:1;min-width:200px}
  button{padding:6px 14px;background:#007bff;color:#fff;border:none;border-radius:4px;cursor:pointer}
  button:hover{background:#0056b3}
  table{width:100%;border-collapse:collapse}
  th,td{text-align:left;padding:8px;border-bottom:1px solid #eee}
  th{background:#f5f5f5;font-weight:600}
  .badge{padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600}
  .badge-high{background:#d4edda;color:#155724}
  .badge-mid{background:#fff3cd;color:#856404}
  .badge-low{background:#f8d7da;color:#721c24}
  .badge-skip{background:#e9ecef;color:#6c757d}
  .badge-summarized{background:#cce5ff;color:#004085}
  .badge-downloaded{background:#e2e3e5;color:#383d41}
  .badge-collected{background:#f8f9fa;color:#6c757d}
  a{color:#007bff;text-decoration:none}
  a:hover{text-decoration:underline}
  .count{color:#666;margin-bottom:8px;font-size:14px}
</style>
</head>
<body>
<h1>World Model Papers</h1>
<form method="get" action="/">
  <div class="filters">
    <input name="q" value="{{ q }}" placeholder="搜索标题/摘要...">
    <select name="venue">
      <option value="">所有会议</option>
      {% for v in ['neurips','icml','iclr','cvpr','corl'] %}
      <option value="{{ v }}" {{ 'selected' if venue==v }}>{{ v.upper() }}</option>
      {% endfor %}
    </select>
    <select name="year">
      <option value="">所有年份</option>
      {% for y in range(2025,2020,-1) %}
      <option value="{{ y }}" {{ 'selected' if year==y|string }}>{{ y }}</option>
      {% endfor %}
    </select>
    <select name="label">
      <option value="">所有标记</option>
      {% for l in ['high','mid','low','skip'] %}
      <option value="{{ l }}" {{ 'selected' if label==l }}>{{ l }}</option>
      {% endfor %}
    </select>
    <select name="status">
      <option value="">所有状态</option>
      {% for s in ['collected','downloaded','summarized'] %}
      <option value="{{ s }}" {{ 'selected' if status==s }}>{{ s }}</option>
      {% endfor %}
    </select>
    <button type="submit">筛选</button>
  </div>
</form>
<p class="count">共 {{ papers|length }} 篇</p>
<table>
  <tr><th>标题</th><th>会议</th><th>年份</th><th>标记</th><th>状态</th><th>得分</th></tr>
  {% for p in papers %}
  <tr>
    <td><a href="{{ url_for('paper_detail', paper_id=p.id) }}">{{ p.title[:80] }}</a></td>
    <td>{{ (p.venue or '')|upper }}</td>
    <td>{{ p.year or '' }}</td>
    <td><span class="badge badge-{{ p.relevance_label or '' }}">{{ p.relevance_label or '-' }}</span></td>
    <td><span class="badge badge-{{ p.status }}">{{ p.status }}</span></td>
    <td>{{ '%.2f'|format(p.relevance_score or 0) }}</td>
  </tr>
  {% endfor %}
</table>
</body>
</html>"""

_DETAIL_HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>{{ paper.title }}</title>
<style>
  body{font-family:sans-serif;max-width:900px;margin:0 auto;padding:20px}
  .meta{color:#555;margin-bottom:20px;font-size:14px}
  .section{margin-bottom:20px}
  .section h3{margin-bottom:6px;color:#222;border-bottom:1px solid #eee;padding-bottom:4px}
  .section p{margin:0;line-height:1.7}
  textarea{width:100%;min-height:100px;padding:8px;border:1px solid #ccc;
           border-radius:4px;font-family:inherit;font-size:14px;box-sizing:border-box}
  .btn{padding:8px 16px;border:none;border-radius:4px;cursor:pointer;color:#fff}
  .btn-save{background:#007bff}.btn-save:hover{background:#0056b3}
  .btn-pdf{background:#28a745;margin-left:10px}.btn-pdf:hover{background:#1e7e34}
  .no-summary{color:#999;font-style:italic}
  a{color:#007bff;text-decoration:none}
  code{background:#f5f5f5;padding:2px 6px;border-radius:3px;font-size:13px}
</style>
</head>
<body>
<p><a href="/">← 返回列表</a></p>
<h1>{{ paper.title }}</h1>
<div class="meta">
  {{ (paper.venue or '')|upper }} {{ paper.year or '' }} &nbsp;|&nbsp;
  标记: <strong>{{ paper.relevance_label or '-' }}</strong> &nbsp;|&nbsp;
  状态: <strong>{{ paper.status }}</strong> &nbsp;|&nbsp;
  得分: {{ '%.2f'|format(paper.relevance_score or 0) }}
  {% if paper.pdf_path %}
  <button class="btn btn-pdf" onclick="openPdf()">打开 PDF</button>
  {% endif %}
</div>
<div class="section"><h3>摘要</h3><p>{{ paper.abstract or '(无)' }}</p></div>

{% if summary %}
<div class="section"><h3>核心问题</h3><p>{{ summary.problem }}</p></div>
<div class="section"><h3>核心创新</h3><p>{{ summary.innovation }}</p></div>
<div class="section"><h3>方法</h3><p>{{ summary.method }}</p></div>
<div class="section"><h3>实验结果</h3><p>{{ summary.results }}</p></div>
<div class="section"><h3>不足与空白</h3><p>{{ summary.gaps }}</p></div>
<div class="section">
  <h3>我的思考</h3>
  <textarea id="thoughts">{{ summary.my_thoughts or '' }}</textarea><br><br>
  <button class="btn btn-save" onclick="saveThoughts()">保存</button>
</div>
{% else %}
<p class="no-summary">
  尚无 AI 总结。运行：<code>python summarize.py --id {{ paper.id }}</code>
</p>
{% endif %}

<script>
function openPdf() {
  fetch('/open_pdf/{{ paper.id }}', {method:'POST'});
}
function saveThoughts() {
  fetch('/save_thoughts/{{ paper.id }}', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({thoughts: document.getElementById('thoughts').value})
  }).then(r=>r.json()).then(d=>{ if(d.ok) alert('已保存'); else alert('保存失败'); });
}
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    q      = request.args.get("q", "")
    venue  = request.args.get("venue", "")
    year   = request.args.get("year", "")
    label  = request.args.get("label", "")
    status = request.args.get("status", "")

    if q:
        papers = search_papers(q)
    else:
        papers = get_papers(
            venue=venue or None,
            year=int(year) if year else None,
            label=label or None,
            status=status or None,
        )
    return render_template_string(
        _LIST_HTML, papers=papers,
        q=q, venue=venue, year=year, label=label, status=status,
    )


@app.route("/paper/<path:paper_id>")
def paper_detail(paper_id):
    all_papers = get_papers()
    paper = next((p for p in all_papers if p["id"] == paper_id), None)
    if not paper:
        return "Paper not found", 404
    summary = get_summary(paper_id)
    return render_template_string(_DETAIL_HTML, paper=paper, summary=summary)


@app.route("/open_pdf/<path:paper_id>", methods=["POST"])
def open_pdf(paper_id):
    all_papers = get_papers()
    paper = next((p for p in all_papers if p["id"] == paper_id), None)
    if paper and paper.get("pdf_path") and os.path.exists(paper["pdf_path"]):
        subprocess.Popen(["open", paper["pdf_path"]])
    return jsonify({"ok": True})


@app.route("/save_thoughts/<path:paper_id>", methods=["POST"])
def save_thoughts(paper_id):
    data = request.get_json()
    update_my_thoughts(paper_id, data.get("thoughts", ""))
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
python3 -m pytest tests/test_browse.py -v
```

Expected: 6 tests pass.

- [ ] **Step 5: Run full test suite**

```bash
python3 -m pytest tests/ -v
```

Expected: All tests pass (26 total across 5 test files).

- [ ] **Step 6: Commit**

```bash
git add browse.py tests/test_browse.py
git commit -m "feat: Flask browse app with search, filter, detail, and PDF open"
```

---

## Task 9: README

**Files:**
- Create: `README.md`

- [ ] **Step 1: Create `README.md`**

```markdown
# 世界模型论文调研流水线

从顶会检索 → 相关性筛选 → 批量下载 → AI 总结 → 本地浏览，五步全自动完成世界模型方向的论文调研。

**覆盖会议：** NeurIPS、ICML、ICLR、CVPR、CoRL（2021—2025）

---

## 项目结构

\```
world-model-research/
├── config.py          # 所有配置：API Key、路径、关键词
├── collect.py         # 阶段1：检索论文元数据
├── filter.py          # 阶段2：关键词打分 + 手动标记相关度
├── download.py        # 阶段3：批量下载 PDF
├── summarize.py       # 阶段4：AI 生成结构化总结
├── browse.py          # 阶段5：本地 Web 浏览界面
├── requirements.txt
├── utils/
│   ├── db.py          # SQLite 读写封装
│   └── pdf_parser.py  # PDF 文字提取
├── papers.db          # 数据库（论文元数据 + AI 总结）
└── pdfs/              # PDF 文件（按会议/年份存放）
    ├── neurips/2023/
    ├── icml/2024/
    └── ...
\```

---

## 快速开始

### 1. 配置

打开 `config.py`，填写你的 DeepSeek 或 Qwen API Key：

\```python
LLM_API_KEY  = "sk-xxxxxx"          # 你的 API Key
LLM_BASE_URL = "https://api.deepseek.com/v1"  # 或 Qwen 地址
LLM_MODEL    = "deepseek-chat"
\```

### 2. 安装依赖

\```bash
pip3 install -r requirements.txt
\```

### 3. 完整调研流程

\```bash
# 检索全部会议元数据（约 5-15 分钟）
python collect.py

# 自动打分 + 手动标记相关度（交互式，按 h/m/l/s + 回车）
python filter.py

# 下载高相关论文 PDF
python download.py --high

# AI 生成总结（需要 API Key）
python summarize.py --label high

# 启动浏览界面
python browse.py
# 打开浏览器访问 http://localhost:5000
\```

---

## 各模块使用说明

### collect.py — 检索元数据

\```bash
python collect.py                    # 检索所有会议（2021-2025）
python collect.py --venue neurips    # 只检索 NeurIPS
python collect.py --year 2024        # 只检索 2024 年
\```

数据来源：
- **Semantic Scholar API**（主要来源，支持按会议/年份过滤）
- **清华 FIB-Lab 汇总库**（`tsinghua-fib-lab/world-model`，补充 arXiv 论文）

### filter.py — 相关性打分与标记

\```bash
python filter.py             # 自动打分 + 逐篇交互标记
python filter.py --auto      # 只自动打分，不弹出交互
python filter.py --review    # 只对未标记论文进行标记
\```

交互标记按键：`h` = high | `m` = mid | `l` = low | `s` = skip | `q` = 退出

### download.py — 下载 PDF

\```bash
python download.py              # 下载所有非 skip 论文
python download.py --high       # 只下载 high 相关度论文
python download.py --limit 20   # 本次最多下载 20 篇
\```

PDF 存放路径：`pdfs/{venue}/{year}/{arxiv_id}.pdf`
已存在的文件自动跳过，支持断点续传。

### summarize.py — AI 生成总结

\```bash
python summarize.py --label high              # 总结 high 论文
python summarize.py --label high,mid          # 总结 high 和 mid 论文
python summarize.py --id arxiv:2301.04589     # 总结单篇
\```

输出字段：核心问题 / 核心创新 / 方法 / 实验结果 / 不足与空白

### browse.py — 本地浏览界面

\```bash
python browse.py
\```

访问 `http://localhost:5000`，支持：
- 按会议、年份、标记、状态筛选
- 标题/摘要关键词搜索
- 查看 AI 总结详情
- 编辑"我的思考"并保存
- 点击"打开 PDF"直接在系统 PDF 阅读器中查看

---

## 典型使用示例

### 示例 A：快速完成一轮高相关论文调研

\```bash
python collect.py                        # 检索元数据（首次约 10 分钟）
python filter.py --auto                  # 快速自动打分
python download.py --high                # 下载得分最高的论文
python summarize.py --label high         # AI 批量总结
python browse.py                         # 浏览总结，开始阅读
\```

### 示例 B：只看 NeurIPS 2024 的论文

\```bash
python collect.py --venue neurips --year 2024
python filter.py
python download.py
python browse.py
\```

### 示例 C：对单篇论文生成总结

\```bash
# 先确保 PDF 已下载
python download.py --id arxiv:2301.04589
# 生成总结
python summarize.py --id arxiv:2301.04589
\```

---

## 测试

\```bash
python3 -m pytest tests/ -v
\```

---

## 注意事项

- arXiv 下载有频率限制，`download.py` 已内置每次 1 秒延迟，请勿并发多次运行
- API Key 请勿提交到 git，建议将 `config.py` 加入 `.gitignore`
- AI 总结可能存在幻觉，关键信息请回到论文原文核对
```

- [ ] **Step 2: Create `.gitignore`**

```
config.py
papers.db
pdfs/
__pycache__/
*.pyc
.pytest_cache/
```

- [ ] **Step 3: Commit**

```bash
git add README.md .gitignore
git commit -m "docs: README with full usage guide and examples"
```

---

## Final Verification

- [ ] **Run full test suite one last time**

```bash
cd /Volumes/HIKSEMI/world-model-research
python3 -m pytest tests/ -v --tb=short
```

Expected output:
```
tests/test_browse.py ......      [ 6 passed ]
tests/test_collect.py ...        [ 3 passed ]
tests/test_db.py ........        [ 8 passed ]
tests/test_download.py ....      [ 4 passed ]
tests/test_filter.py ...         [ 3 passed ]
tests/test_pdf_parser.py ...     [ 3 passed ]
tests/test_summarize.py ....     [ 4 passed ]
======================== 31 passed ========================
```

- [ ] **Verify project structure is complete**

```bash
ls /Volumes/HIKSEMI/world-model-research/
```

Expected: `browse.py  collect.py  config.py  download.py  filter.py  README.md  requirements.txt  summarize.py  utils/  tests/  papers.db  pdfs/  docs/`
