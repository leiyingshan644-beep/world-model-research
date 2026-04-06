import argparse
import re
import time
import requests
from bs4 import BeautifulSoup
import arxiv as arxiv_pkg

from config import TARGET_VENUES, YEAR_RANGE, KEYWORDS
from utils.db import init_db, upsert_paper

# ---------------------------------------------------------------------------
# OpenReview venue IDs (NeurIPS / ICML / ICLR)
# ---------------------------------------------------------------------------
_OR_VENUE_IDS = {
    "neurips": {y: f"NeurIPS.cc/{y}/Conference" for y in range(2021, 2026)},
    "icml":    {y: f"ICML.cc/{y}/Conference"    for y in range(2021, 2026)},
    "iclr":    {y: f"ICLR.cc/{y}/Conference"    for y in range(2021, 2026)},
}

_OR_API   = "https://api2.openreview.net/notes"
_CVF_URL  = "https://openaccess.thecvf.com/CVPR{year}?day=all"
FIBLABS_URL = (
    "https://raw.githubusercontent.com/tsinghua-fib-lab/world-model/main/README.md"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _val(field):
    """OpenReview API v2 wraps content values in {"value": ...} dicts."""
    if isinstance(field, dict):
        return field.get("value", "")
    return field or ""


def _matches_keywords(title: str, abstract: str) -> bool:
    text = (title + " " + abstract).lower()
    return any(kw.lower() in text for kw in KEYWORDS)


def _arxiv_id_from_note(note: dict) -> str | None:
    """Try to pull an arXiv ID out of an OpenReview note's content fields."""
    c = note.get("content", {})
    for field in ("arxiv", "ARXIV", "arxiv_id", "ArXiv"):
        v = str(_val(c.get(field, "")))
        m = re.search(r"(\d{4}\.\d{4,5})", v)
        if m:
            return m.group(1)
    for field in ("pdf", "html", "code"):
        v = str(_val(c.get(field, "")))
        m = re.search(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", v)
        if m:
            return m.group(1)
    return None


# ---------------------------------------------------------------------------
# Source 1: OpenReview  →  NeurIPS / ICML / ICLR
# ---------------------------------------------------------------------------
def fetch_from_openreview(venue_key: str, year: int) -> list:
    """Return keyword-matching papers from one OpenReview venue/year."""
    venue_id = _OR_VENUE_IDS.get(venue_key, {}).get(year)
    if not venue_id:
        return []

    papers, offset, limit = [], 0, 1000
    while True:
        try:
            resp = requests.get(
                _OR_API,
                params={"content.venueid": venue_id, "limit": limit, "offset": offset},
                timeout=30,
            )
        except requests.RequestException as e:
            print(f"    OR error ({venue_key} {year}): {e}")
            break

        if not resp.ok:
            print(f"    OR {resp.status_code} for {venue_key} {year}")
            break

        notes = resp.json().get("notes", [])
        for note in notes:
            c = note.get("content", {})
            title    = str(_val(c.get("title",    "")))
            abstract = str(_val(c.get("abstract", "")))
            if not _matches_keywords(title, abstract):
                continue

            authors = _val(c.get("authors", []))
            if not isinstance(authors, list):
                authors = [authors] if authors else []

            arxiv_id = _arxiv_id_from_note(note)
            paper_id = arxiv_id or f"or:{note['id']}"

            pdf = str(_val(c.get("pdf", "")))
            if arxiv_id:
                pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"
            elif pdf:
                pdf_url = f"https://openreview.net{pdf}" if pdf.startswith("/") else pdf
            else:
                pdf_url = None

            papers.append({
                "id": paper_id, "title": title, "authors": authors,
                "year": year, "venue": venue_key, "abstract": abstract,
                "arxiv_id": arxiv_id, "pdf_url": pdf_url,
            })

        if len(notes) < limit:
            break
        offset += limit
        time.sleep(0.3)

    return papers


# ---------------------------------------------------------------------------
# Source 2: CVF Open Access  →  CVPR
# ---------------------------------------------------------------------------
def fetch_from_cvf(year: int) -> list:
    """Scrape CVPR papers from CVF Open Access and filter by keywords."""
    url = _CVF_URL.format(year=year)
    try:
        resp = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    except requests.RequestException as e:
        print(f"    CVF error (CVPR {year}): {e}")
        return []

    if not resp.ok:
        print(f"    CVF {resp.status_code} for CVPR {year}")
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    papers = []

    for dt in soup.find_all("dt", class_="ptitle"):
        a = dt.find("a")
        if not a:
            continue
        title = a.get_text(strip=True)
        if not _matches_keywords(title, ""):
            continue

        dd = dt.find_next_sibling("dd")
        arxiv_id, pdf_url = None, None

        if dd:
            for a_tag in dd.find_all("a"):
                href = a_tag.get("href", "")
                m = re.search(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", href)
                if m:
                    arxiv_id = m.group(1)
                    pdf_url  = f"https://arxiv.org/pdf/{arxiv_id}"
                    break
            if not pdf_url:
                pdf_a = dd.find("a", href=re.compile(r"\.pdf$", re.I))
                if pdf_a:
                    href = pdf_a["href"]
                    pdf_url = (
                        f"https://openaccess.thecvf.com{href}"
                        if href.startswith("/") else href
                    )

        slug = re.sub(r"[^a-z0-9]", "_", title.lower())[:40]
        paper_id = arxiv_id or f"cvf:{year}:{slug}"
        papers.append({
            "id": paper_id, "title": title, "authors": [],
            "year": year, "venue": "cvpr", "abstract": "",
            "arxiv_id": arxiv_id, "pdf_url": pdf_url,
        })

    return papers


# ---------------------------------------------------------------------------
# Source 3: arXiv keyword search  →  CoRL + supplement
# ---------------------------------------------------------------------------
_VENUE_ALIASES = {
    "corl":    ["corl", "conference on robot learning"],
    "neurips": ["neurips", "neural information processing"],
    "icml":    ["icml", "international conference on machine learning"],
    "iclr":    ["iclr", "international conference on learning representations"],
    "cvpr":    ["cvpr", "computer vision and pattern recognition"],
}


def _detect_venue(comment: str, journal: str) -> str | None:
    text = (comment + " " + journal).lower()
    for venue, aliases in _VENUE_ALIASES.items():
        if any(a in text for a in aliases):
            return venue
    return None


def fetch_from_arxiv(keyword: str, year_range: tuple) -> list:
    """Search arXiv for a keyword; return papers within year_range."""
    client = arxiv_pkg.Client(num_retries=3, delay_seconds=3)
    search = arxiv_pkg.Search(
        query=keyword,
        max_results=300,
        sort_by=arxiv_pkg.SortCriterion.Relevance,
    )
    start_year, end_year = year_range
    papers = []
    try:
        for result in client.results(search):
            year = result.published.year
            if not (start_year <= year <= end_year):
                continue
            arxiv_id = result.entry_id.split("/")[-1].split("v")[0]
            venue = _detect_venue(result.comment or "", result.journal_ref or "")
            papers.append({
                "id": arxiv_id, "title": result.title,
                "authors": [a.name for a in result.authors],
                "year": year, "venue": venue,
                "abstract": result.summary,
                "arxiv_id": arxiv_id,
                "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
            })
    except Exception as e:
        print(f"    arXiv error for '{keyword}': {e}")
    return papers


# ---------------------------------------------------------------------------
# Source 4: FIB-Lab GitHub  →  curated arXiv supplement
# ---------------------------------------------------------------------------
def fetch_from_fiblabs() -> list:
    try:
        resp = requests.get(FIBLABS_URL, timeout=15)
    except requests.RequestException as e:
        print(f"  Warning: FIB-Lab fetch failed: {e}")
        return []
    if not resp.ok:
        print(f"  Warning: FIB-Lab returned {resp.status_code}")
        return []
    pattern = re.compile(r"\[([^\]]+)\]\(https://arxiv\.org/abs/([0-9]+\.[0-9]+)")
    papers = []
    for m in pattern.finditer(resp.text):
        title, arxiv_id = m.group(1), m.group(2)
        papers.append({
            "id": arxiv_id, "title": title, "authors": [],
            "year": None, "venue": None, "abstract": "",
            "arxiv_id": arxiv_id,
            "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
        })
    return papers


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
def collect(venues=None, year=None):
    init_db()
    target_venues = venues or TARGET_VENUES
    year_range = (year, year) if year else YEAR_RANGE
    years = range(year_range[0], year_range[1] + 1)

    all_papers: dict = {}

    # 1. OpenReview → NeurIPS, ICML, ICLR
    for venue_key in [v for v in target_venues if v in _OR_VENUE_IDS]:
        for y in years:
            print(f"  OpenReview: {venue_key.upper()} {y} ...")
            for p in fetch_from_openreview(venue_key, y):
                all_papers[p["id"]] = p

    # 2. CVF Open Access → CVPR
    if "cvpr" in target_venues:
        for y in years:
            print(f"  CVF: CVPR {y} ...")
            for p in fetch_from_cvf(y):
                all_papers[p["id"]] = p

    # 3. arXiv keyword search → CoRL + supplement
    for kw in KEYWORDS:
        print(f"  arXiv: '{kw}' ...")
        for p in fetch_from_arxiv(kw, year_range):
            if p["id"] not in all_papers:
                all_papers[p["id"]] = p
        time.sleep(1)

    # 4. FIB-Lab supplement
    print("  FIB-Lab repo ...")
    for p in fetch_from_fiblabs():
        if p["id"] not in all_papers:
            all_papers[p["id"]] = p

    for p in all_papers.values():
        upsert_paper(p)

    print(f"Done. {len(all_papers)} papers written to DB.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collect world model paper metadata")
    parser.add_argument("--venue", help="Single venue, e.g. neurips")
    parser.add_argument("--year",  type=int, help="Single year, e.g. 2024")
    args = parser.parse_args()
    collect(
        venues=[args.venue] if args.venue else None,
        year=args.year,
    )
