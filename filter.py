import argparse
from utils.db import get_papers, update_paper, batch_update_papers

# Keyword weights — higher = more central to "world model" research
_WEIGHTS = {
    # Core world model terms
    "world model":              3.0,
    "generative world model":   4.0,
    "world foundation model":   4.0,
    "visual world model":       3.5,
    "driving world model":      3.0,
    "embodied world model":     3.0,
    # Visual generation — our group's focus
    "cosmos":                   2.5,
    "hunyuan":                  2.0,
    "video diffusion":          1.5,
    "text-to-video":            1.5,
    "4d generation":            2.0,
    "scene generation":         1.5,
    # RL-based world models — lower priority
    "model-based rl":           1.5,
    "video prediction":         1.0,
    "dreamer":                  0.8,
    "td-mpc":                   0.8,
    "planet":                   0.5,
}
_MAX_RAW = sum(_WEIGHTS.values())  # normalisation denominator

# Auto-label thresholds (fraction of _MAX_RAW)
_THRESH_HIGH = 0.20   # score ≥ 0.20 → high
_THRESH_MID  = 0.08   # score ≥ 0.08 → mid   (else → low)


def score_paper(paper: dict) -> float:
    text = f"{paper.get('title', '')} {paper.get('abstract', '')}".lower()
    raw = sum(w for kw, w in _WEIGHTS.items() if kw in text)
    return min(raw / _MAX_RAW, 1.0)


def _print_filter_report(papers: list, label_counts: dict) -> None:
    scored = sorted(papers, key=lambda p: p["relevance_score"], reverse=True)
    buckets = {
        "≥ 0.50": sum(1 for p in papers if p["relevance_score"] >= 0.50),
        "≥ 0.30": sum(1 for p in papers if 0.30 <= p["relevance_score"] < 0.50),
        "≥ 0.20": sum(1 for p in papers if 0.20 <= p["relevance_score"] < 0.30),
        "≥ 0.08": sum(1 for p in papers if 0.08 <= p["relevance_score"] < 0.20),
        "< 0.08": sum(1 for p in papers if p["relevance_score"] < 0.08),
    }

    w = 52
    print("\n" + "━" * w)
    print(f"  Filter Report  —  {len(papers)} papers scored")
    print("━" * w)

    print("\n  Score distribution:")
    bar_scale = max(buckets.values()) or 1
    for label_str, cnt in buckets.items():
        bar = "█" * int(cnt / bar_scale * 20)
        print(f"    {label_str}   {cnt:>4}  {bar}")

    print(f"\n  Auto-labels assigned (high ≥ {_THRESH_HIGH:.2f} / mid ≥ {_THRESH_MID:.2f}):")
    for lbl in ("high", "mid", "low"):
        n   = label_counts[lbl]
        bar = "█" * (n // max(1, len(papers) // 40))
        print(f"    {lbl:<5}  {n:>4}  {bar}")

    print(f"\n  Top 10 highest-scored papers:")
    for p in scored[:10]:
        venue = (p.get("venue") or "?").upper()
        year  = p.get("year") or "?"
        title = p.get("title", "")[:55]
        print(f"    {p['relevance_score']:.2f}  [{venue} {year}]  {title}")

    print("━" * w + "\n")


def run_filter(auto: bool = False, review: bool = False):
    papers = get_papers()
    if review:
        papers = [p for p in papers if p["relevance_label"] is None]

    # Score all in memory first, then write in one transaction
    label_counts = {"high": 0, "mid": 0, "low": 0}
    updates = []
    for p in papers:
        s = score_paper(p)
        p["relevance_score"] = s
        if auto:
            if s >= _THRESH_HIGH:
                label = "high"
            elif s >= _THRESH_MID:
                label = "mid"
            else:
                label = "low"
            label_counts[label] += 1
        else:
            label = p.get("relevance_label")  # preserve existing
        updates.append((p["id"], s, label))

    print(f"  Writing {len(updates)} scores to DB...", flush=True)
    batch_update_papers(updates)

    if auto:
        _print_filter_report(papers, label_counts)
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
