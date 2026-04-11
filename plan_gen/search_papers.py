"""
search_papers.py — Dual-track paper retrieval for plan generation.

Retrieves real, verifiable papers from:
  1. Local papers.db (already curated)
  2. arXiv API (free, no key required)
  3. Semantic Scholar API (free, rate-limited: 100 req/5min)

Usage:
    from plan_gen.search_papers import search_all
    papers = search_all(keywords, n=30)
"""

import json
import os
import sqlite3
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Optional

# ── Config ─────────────────────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH  = os.path.join(BASE_DIR, "papers.db")

ARXIV_API    = "https://export.arxiv.org/api/query"
S2_API       = "https://api.semanticscholar.org/graph/v1/paper/search"
S2_FIELDS    = "title,year,venue,externalIds,abstract,citationCount,authors"

_ARXIV_NS = "http://www.w3.org/2005/Atom"


# ── Local DB ───────────────────────────────────────────────────────────────

def _search_local(keywords: list[str], n: int = 20) -> list[dict]:
    """FTS search across title + abstract in local papers.db."""
    if not os.path.exists(DB_PATH):
        return []
    query = " OR ".join(f'"{kw}"' for kw in keywords)
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        # Simple LIKE search (no FTS table needed)
        conditions = " OR ".join(
            ["(LOWER(title) LIKE ? OR LOWER(abstract) LIKE ?)"] * len(keywords)
        )
        params = []
        for kw in keywords:
            like = f"%{kw.lower()}%"
            params += [like, like]
        rows = conn.execute(
            f"""SELECT id, title, year, venue, abstract, arxiv_id
                FROM papers
                WHERE {conditions}
                ORDER BY (relevance_score + COALESCE(manual_boost,0)) DESC
                LIMIT ?""",
            params + [n],
        ).fetchall()
        conn.close()
        results = []
        for r in rows:
            results.append({
                "source":    "local",
                "paper_id":  r["id"],
                "arxiv_id":  r["arxiv_id"] or "",
                "title":     r["title"],
                "year":      r["year"] or "",
                "venue":     (r["venue"] or "arXiv").upper(),
                "abstract":  (r["abstract"] or "")[:300],
                "citation_count": 0,
            })
        return results
    except Exception as e:
        print(f"  [local search error] {e}")
        return []


# ── arXiv ──────────────────────────────────────────────────────────────────

def _search_arxiv(keywords: list[str], n: int = 15) -> list[dict]:
    """Query arXiv API. Returns up to n results."""
    query = "+AND+".join(
        f"all:{urllib.parse.quote(kw)}" for kw in keywords[:3]
    )
    url = (
        f"{ARXIV_API}?search_query={query}"
        f"&start=0&max_results={n}&sortBy=relevance&sortOrder=descending"
    )
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            xml_data = resp.read()
        root = ET.fromstring(xml_data)
        ns   = {"a": _ARXIV_NS}
        results = []
        for entry in root.findall("a:entry", ns):
            arxiv_id = entry.find("a:id", ns).text.split("/abs/")[-1].strip()
            title    = entry.find("a:title", ns).text.strip().replace("\n", " ")
            abstract = (entry.find("a:summary", ns).text or "").strip()[:300]
            published = entry.find("a:published", ns).text[:4]  # year
            # venue from category
            cats = [c.get("term","") for c in entry.findall("a:category", ns)]
            venue = "arXiv"
            results.append({
                "source":   "arxiv",
                "paper_id": f"arxiv:{arxiv_id}",
                "arxiv_id": arxiv_id,
                "title":    title,
                "year":     published,
                "venue":    venue,
                "abstract": abstract,
                "citation_count": 0,
            })
        return results
    except Exception as e:
        print(f"  [arXiv search error] {e}")
        return []


# ── Semantic Scholar ────────────────────────────────────────────────────────

def _search_s2(keywords: list[str], n: int = 15) -> list[dict]:
    """Query Semantic Scholar API. Rate limit: 100 req/5min (no key)."""
    query = urllib.parse.quote(" ".join(keywords[:4]))
    url   = f"{S2_API}?query={query}&limit={n}&fields={S2_FIELDS}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "research-plan-gen/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        results = []
        for p in data.get("data", []):
            ext   = p.get("externalIds") or {}
            arxiv = ext.get("ArXiv", "")
            venue = p.get("venue") or "arXiv"
            results.append({
                "source":         "s2",
                "paper_id":       f"s2:{p['paperId']}",
                "arxiv_id":       arxiv,
                "title":          p.get("title", ""),
                "year":           str(p.get("year") or ""),
                "venue":          venue.upper() if venue else "arXiv",
                "abstract":       (p.get("abstract") or "")[:300],
                "citation_count": p.get("citationCount") or 0,
            })
        time.sleep(0.4)  # gentle rate limiting
        return results
    except Exception as e:
        print(f"  [S2 search error] {e}")
        return []


# ── Merge & Deduplicate ─────────────────────────────────────────────────────

def _deduplicate(papers: list[dict]) -> list[dict]:
    """Remove duplicates by arxiv_id and title similarity."""
    seen_arxiv = set()
    seen_title = set()
    out = []
    for p in papers:
        aid = p.get("arxiv_id", "").strip()
        title_key = p["title"].lower()[:60]
        if aid and aid in seen_arxiv:
            continue
        if title_key in seen_title:
            continue
        if aid:
            seen_arxiv.add(aid)
        seen_title.add(title_key)
        out.append(p)
    return out


def search_all(keywords: list[str], n: int = 30, verbose: bool = True) -> list[dict]:
    """
    Retrieve up to n real papers from local DB + arXiv + Semantic Scholar.
    Returns deduplicated list sorted by citation count (desc).
    """
    if verbose:
        print(f"  Searching: {keywords}")

    local  = _search_local(keywords, n=20)
    if verbose:
        print(f"    local DB: {len(local)} papers")

    arxiv  = _search_arxiv(keywords, n=15)
    if verbose:
        print(f"    arXiv:    {len(arxiv)} papers")

    s2     = _search_s2(keywords, n=15)
    if verbose:
        print(f"    S2:       {len(s2)} papers")

    # Local results first (highest trust), then S2 (has citation count), then arXiv
    merged = _deduplicate(local + s2 + arxiv)

    # Sort: local high-score papers first, then by citation count
    merged.sort(key=lambda p: (
        0 if p["source"] == "local" else 1,
        -p.get("citation_count", 0),
    ))

    result = merged[:n]
    if verbose:
        print(f"    → {len(result)} unique papers after dedup")
    return result


if __name__ == "__main__":
    import sys
    kws = sys.argv[1:] or ["world model", "video prediction", "temporal consistency"]
    papers = search_all(kws, n=20)
    for i, p in enumerate(papers, 1):
        print(f"[{i:2d}] [{p['source']:5s}] {p['year']} {p['venue']:10s} {p['title'][:70]}")
