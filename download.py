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
            if not resp.ok:
                continue
            content_type = resp.headers.get("content-type", "")
            # Accept application/pdf, octet-stream, or unknown content-type;
            # reject obvious HTML responses (arXiv abstract pages, captchas)
            if "html" in content_type.lower():
                continue
            with open(dest_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            # Verify it's actually a PDF (magic bytes)
            with open(dest_path, "rb") as f:
                if f.read(4) != b"%PDF":
                    os.remove(dest_path)
                    continue
            return dest_path, "downloaded"
        except requests.RequestException:
            continue

    return None, "failed"


def run_download(high_only: bool = False, limit: int = None, paper_id: str = None):
    if paper_id:
        clean_id = paper_id.replace("arxiv:", "")
        papers = [p for p in get_papers() if p["id"] == clean_id]
        if not papers:
            print(f"Paper not found in DB: {clean_id}")
            return
    elif high_only:
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
    parser.add_argument("--id",    dest="paper_id", help="Download a single paper, e.g. arxiv:2301.04589")
    args = parser.parse_args()
    run_download(high_only=args.high, limit=args.limit, paper_id=args.paper_id)
