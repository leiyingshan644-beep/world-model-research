import argparse
import re
import time
import requests
from bs4 import BeautifulSoup
import arxiv as arxiv_pkg

from config import TARGET_VENUES, YEAR_RANGE, KEYWORDS
from utils.db import init_db, upsert_paper, update_paper

# ---------------------------------------------------------------------------
# OpenAlex
# ---------------------------------------------------------------------------
_OA_BASE    = "https://api.openalex.org"
_OA_HEADERS = {"User-Agent": "WorldModelResearch/1.0"}

# Map substrings of OpenAlex source display_name → our venue shortname
_VENUE_NORMALIZE = {
    "neural information processing": "neurips",
    "neurips": "neurips",
    "nips":    "neurips",
    "international conference on machine learning": "icml",
    "machine learning research": "icml",
    "icml":    "icml",
    "learning representations": "iclr",
    "iclr":    "iclr",
    "computer vision and pattern recognition": "cvpr",
    "cvpr":    "cvpr",
    "robot learning": "corl",
    "corl":    "corl",
}

FIBLABS_URL = (
    "https://raw.githubusercontent.com/tsinghua-fib-lab/world-model/main/README.md"
)


def _normalize_venue(name: str) -> str | None:
    low = (name or "").lower()
    for key, short in _VENUE_NORMALIZE.items():
        if key in low:
            return short
    return None


def _reconstruct_abstract(inv_index: dict | None) -> str:
    """Rebuild plain text from OpenAlex inverted-index abstract format."""
    if not inv_index:
        return ""
    pos_word: dict[int, str] = {}
    for word, positions in inv_index.items():
        for pos in positions:
            pos_word[pos] = word
    return " ".join(pos_word[i] for i in sorted(pos_word))


def _oa_work_to_paper(work: dict) -> dict | None:
    title    = work.get("title") or ""
    abstract = _reconstruct_abstract(work.get("abstract_inverted_index"))

    ids      = work.get("ids") or {}
    arxiv_raw = str(ids.get("arxiv") or "")
    arxiv_id  = None
    m = re.search(r"(\d{4}\.\d{4,5})", arxiv_raw)
    if m:
        arxiv_id = m.group(1)

    doi = str(ids.get("doi") or "").replace("https://doi.org/", "")

    loc    = (work.get("primary_location") or {})
    src    = (loc.get("source") or {})
    src_name = src.get("display_name") or ""
    venue  = _normalize_venue(src_name)

    authors = [
        a["author"].get("display_name", "")
        for a in (work.get("authorships") or [])
        if a.get("author")
    ]

    year     = work.get("publication_year")
    paper_id = arxiv_id or f"oa:{work['id'].split('/')[-1]}"
    pdf_url  = (f"https://arxiv.org/pdf/{arxiv_id}" if arxiv_id
                else loc.get("pdf_url"))

    return {
        "id": paper_id, "title": title, "authors": authors,
        "year": year, "venue": venue, "source": "openalex",
        "doi": doi, "abstract": abstract,
        "arxiv_id": arxiv_id, "pdf_url": pdf_url,
        "_src_name": src_name,   # kept for report; not stored in DB
    }


# ---------------------------------------------------------------------------
# Source 1: OpenAlex — conference proceedings keyword search
# ---------------------------------------------------------------------------
def fetch_from_openalex(target_venues: list, year_range: tuple) -> list:
    """
    Search OpenAlex for proceedings papers matching 'world model' in our
    year range, then filter locally to target venues.
    Also runs a second pass for 'dreamer' to catch technique-specific papers.
    """
    start, end = year_range
    results_all: dict[str, dict] = {}

    for kw in ("world model", "dreamer", "model-based reinforcement learning"):
        cursor = "*"
        while cursor:
            try:
                resp = requests.get(
                    f"{_OA_BASE}/works",
                    params={
                        "filter": (
                            f"type:proceedings-article,"
                            f"default.search:{kw},"
                            f"publication_year:{start}-{end}"
                        ),
                        "per_page": 200,
                        "cursor": cursor,
                        "select": (
                            "id,title,abstract_inverted_index,"
                            "publication_year,authorships,"
                            "primary_location,ids"
                        ),
                    },
                    headers=_OA_HEADERS,
                    timeout=30,
                )
            except requests.RequestException as e:
                print(f"    OA error ({kw!r}): {e}")
                break

            if not resp.ok:
                print(f"    OA {resp.status_code} ({kw!r})")
                break

            data   = resp.json()
            works  = data.get("results", [])
            total  = data.get("meta", {}).get("count", "?")
            print(f"    OA {kw!r}: {len(works)} / ~{total}")

            for work in works:
                paper = _oa_work_to_paper(work)
                if paper and paper["venue"] in target_venues:
                    results_all[paper["id"]] = paper

            cursor = data.get("meta", {}).get("next_cursor")
            if not works:
                break
            time.sleep(0.1)

    return list(results_all.values())


# ---------------------------------------------------------------------------
# Source 2: arXiv keyword search — CoRL + supplement
# ---------------------------------------------------------------------------
_VENUE_ALIASES = {
    "corl":    ["corl", "conference on robot learning"],
    "neurips": ["neurips", "neural information processing"],
    "icml":    ["icml", "international conference on machine learning"],
    "iclr":    ["iclr", "international conference on learning representations"],
    "cvpr":    ["cvpr", "computer vision and pattern recognition"],
}


def _detect_venue_from_text(comment: str, journal: str) -> str | None:
    text = (comment + " " + journal).lower()
    for venue, aliases in _VENUE_ALIASES.items():
        if any(a in text for a in aliases):
            return venue
    return None


def fetch_from_arxiv(keyword: str, year_range: tuple) -> list:
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
            venue    = _detect_venue_from_text(
                result.comment or "", result.journal_ref or ""
            )
            papers.append({
                "id": arxiv_id, "title": result.title,
                "authors": [a.name for a in result.authors],
                "year": year, "venue": venue,
                "source": "arxiv", "doi": "",
                "abstract": result.summary,
                "arxiv_id": arxiv_id,
                "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
            })
    except Exception as e:
        print(f"    arXiv error for {keyword!r}: {e}")
    return papers


# ---------------------------------------------------------------------------
# Source 3: CVF Open Access — CVPR supplement
# ---------------------------------------------------------------------------
def fetch_from_cvf(year: int) -> list:
    url = f"https://openaccess.thecvf.com/CVPR{year}?day=all"
    try:
        resp = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    except requests.RequestException as e:
        print(f"    CVF error (CVPR {year}): {e}")
        return []
    if not resp.ok:
        print(f"    CVF {resp.status_code} for CVPR {year}")
        return []

    soup    = BeautifulSoup(resp.text, "lxml")
    kw_low  = [k.lower() for k in KEYWORDS]
    papers  = []

    for dt in soup.find_all("dt", class_="ptitle"):
        a = dt.find("a")
        if not a:
            continue
        title = a.get_text(strip=True)
        if not any(kw in title.lower() for kw in kw_low):
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
                    h = pdf_a["href"]
                    pdf_url = (f"https://openaccess.thecvf.com{h}"
                               if h.startswith("/") else h)

        slug     = re.sub(r"[^a-z0-9]", "_", title.lower())[:40]
        paper_id = arxiv_id or f"cvf:{year}:{slug}"
        papers.append({
            "id": paper_id, "title": title, "authors": [],
            "year": year, "venue": "cvpr",
            "source": "cvf", "doi": "",
            "abstract": "", "arxiv_id": arxiv_id, "pdf_url": pdf_url,
        })
    return papers


# ---------------------------------------------------------------------------
# Source 4: FIB-Lab — curated arXiv list
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
    papers  = []
    for m in pattern.finditer(resp.text):
        title, arxiv_id = m.group(1), m.group(2)
        papers.append({
            "id": arxiv_id, "title": title, "authors": [],
            "year": None, "venue": None,
            "source": "fiblabs", "doi": "",
            "abstract": "", "arxiv_id": arxiv_id,
            "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
        })
    return papers


# ---------------------------------------------------------------------------
# Cross-reference: look up arXiv papers on OpenAlex to confirm publication
# ---------------------------------------------------------------------------
def crossref_via_openalex(papers_by_id: dict) -> int:
    """
    For papers without a known venue, batch-query OpenAlex by arXiv ID.
    Updates venue/doi/source in the DB for confirmed publications.
    Returns the number of papers whose venue was updated.
    """
    to_check = [
        p for p in papers_by_id.values()
        if p.get("arxiv_id") and not p.get("venue")
    ]
    if not to_check:
        return 0

    updated = 0
    batch_size = 50

    for i in range(0, len(to_check), batch_size):
        batch = to_check[i : i + batch_size]
        ids_str = "|".join(p["arxiv_id"] for p in batch)
        try:
            resp = requests.get(
                f"{_OA_BASE}/works",
                params={
                    "filter": f"ids.arxiv:{ids_str}",
                    "per_page": batch_size,
                    "select": "ids,primary_location,publication_year",
                },
                headers=_OA_HEADERS,
                timeout=30,
            )
        except requests.RequestException:
            continue

        if not resp.ok:
            continue

        for work in resp.json().get("results", []):
            arxiv_raw = str((work.get("ids") or {}).get("arxiv") or "")
            m = re.search(r"(\d{4}\.\d{4,5})", arxiv_raw)
            if not m:
                continue
            arxiv_id = m.group(1)

            src      = ((work.get("primary_location") or {}).get("source") or {})
            src_name = src.get("display_name") or ""
            venue    = _normalize_venue(src_name)
            doi_raw  = str((work.get("ids") or {}).get("doi") or "")
            doi      = doi_raw.replace("https://doi.org/", "")

            # Find the matching paper ID in our dict
            matching = [
                p for p in batch if p.get("arxiv_id") == arxiv_id
            ]
            for paper in matching:
                update_fields: dict = {"source": "openalex_crossref"}
                if venue:
                    update_fields["venue"] = venue
                if doi:
                    update_fields["doi"] = doi
                update_paper(paper["id"], **update_fields)
                # Also patch in-memory so report is accurate
                paper["venue"]  = venue or paper.get("venue")
                paper["doi"]    = doi
                paper["source"] = "openalex_crossref"
                if venue:
                    updated += 1

        time.sleep(0.1)

    return updated


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def _print_report(all_papers: dict, crossref_updated: int) -> None:
    papers = list(all_papers.values())
    total  = len(papers)

    from collections import Counter
    source_cnt = Counter(p.get("source") or "unknown" for p in papers)
    venue_cnt  = Counter(p.get("venue")  or "—"       for p in papers)
    year_cnt   = Counter(p.get("year")   or "—"       for p in papers)

    target = {"neurips", "icml", "iclr", "cvpr", "corl"}
    in_target   = sum(1 for p in papers if p.get("venue") in target)
    other_venue = sum(1 for p in papers if p.get("venue") and p.get("venue") not in target)
    no_venue    = sum(1 for p in papers if not p.get("venue"))
    has_doi     = sum(1 for p in papers if p.get("doi"))

    w = 52
    print("\n" + "━" * w)
    print(f"  Collection Report  —  {total} papers total")
    print("━" * w)

    print("\n  By channel (source):")
    labels = {
        "openalex":          "OpenAlex (proceedings search)",
        "arxiv":             "arXiv (keyword search)",
        "cvf":               "CVF Open Access (CVPR)",
        "fiblabs":           "FIB-Lab curated list",
        "openalex_crossref": "Venue confirmed via OpenAlex",
    }
    for src, cnt in sorted(source_cnt.items(), key=lambda x: -x[1]):
        label = labels.get(src, src)
        print(f"    {label:<36} {cnt:>4}")

    print(f"\n  Cross-reference:  {crossref_updated} arXiv papers got venue confirmed")

    print("\n  By conference/venue:")
    for v in ["neurips", "icml", "iclr", "cvpr", "corl"]:
        n = venue_cnt.get(v, 0)
        bar = "█" * (n // 5)
        print(f"    {v.upper():<8}  {n:>4}  {bar}")
    if other_venue:
        print(f"    Other journals    {other_venue:>4}")
    print(f"    No venue yet      {no_venue:>4}")

    print("\n  By year:")
    year_line = "    " + "   ".join(
        f"{y}: {year_cnt.get(y, 0)}"
        for y in [2021, 2022, 2023, 2024, 2025]
    )
    print(year_line)

    print(f"\n  With PDF link: {sum(1 for p in papers if p.get('pdf_url'))}")
    print(f"  With DOI:      {has_doi}")
    print("━" * w + "\n")


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
def collect(venues=None, year=None):
    init_db()
    target_venues = venues or TARGET_VENUES
    year_range    = (year, year) if year else YEAR_RANGE
    years         = range(year_range[0], year_range[1] + 1)

    all_papers: dict[str, dict] = {}

    # 1. OpenAlex — NeurIPS / ICML / ICLR / CVPR / CoRL (proceedings search)
    print("  OpenAlex: proceedings keyword search ...")
    oa_venues = [v for v in target_venues if v in {"neurips", "icml", "iclr", "cvpr", "corl"}]
    for p in fetch_from_openalex(oa_venues, year_range):
        all_papers[p["id"]] = p

    # 2. CVF Open Access — CVPR supplement (for papers OA might miss)
    if "cvpr" in target_venues:
        for y in years:
            print(f"  CVF: CVPR {y} ...")
            for p in fetch_from_cvf(y):
                if p["id"] not in all_papers:
                    all_papers[p["id"]] = p

    # 3. arXiv keyword search — CoRL + technique-specific supplement
    for kw in KEYWORDS:
        print(f"  arXiv: {kw!r} ...")
        for p in fetch_from_arxiv(kw, year_range):
            if p["id"] not in all_papers:
                all_papers[p["id"]] = p
        time.sleep(1)

    # 4. FIB-Lab curated list
    print("  FIB-Lab repo ...")
    for p in fetch_from_fiblabs():
        if p["id"] not in all_papers:
            all_papers[p["id"]] = p

    # 5. Write everything to DB first
    for p in all_papers.values():
        upsert_paper(p)

    # 6. Cross-reference arXiv/FIB-Lab papers to find their publication venue
    no_venue_count = sum(1 for p in all_papers.values() if not p.get("venue"))
    print(f"\n  Cross-referencing {no_venue_count} papers without venue via OpenAlex ...")
    crossref_updated = crossref_via_openalex(all_papers)

    _print_report(all_papers, crossref_updated)


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
