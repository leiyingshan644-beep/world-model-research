import argparse
from utils.db import get_papers, update_paper

# Keyword weights — higher = more central to "world model" research
_WEIGHTS = {
    "world model":            3.0,
    "generative world model": 4.0,
    "world foundation model": 4.0,
    "model-based rl":         2.0,
    "dreamer":                2.5,
    "planet":                 1.5,
    "td-mpc":                 2.0,
    "video prediction":       1.5,
    "embodied world model":   3.0,
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
