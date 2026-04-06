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
