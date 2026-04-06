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
