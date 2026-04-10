"""
extract_gaps.py — Step 1 of idea generation pipeline.

Selects ~200 papers (top-100 by score + stratified sample of 100),
calls LLM to extract structured gaps from abstract + existing summary,
saves each result to gaps/{paper_id}.json.

Usage:
    python idea_gen/extract_gaps.py
    python idea_gen/extract_gaps.py --dry-run   # show selection stats only
"""

import argparse
import json
import os
import random
import sys

from openai import OpenAI

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import LLM_BASE_URL, LLM_API_KEY, LLM_MODEL
from utils.db import get_conn, get_papers

GAPS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gaps")

_PROMPT = """\
You are a research analyst specializing in world models and visual generation AI.

Given the following paper information, extract a structured gap analysis.
Return ONLY a valid JSON object with exactly these keys:

  "solved"      — list of 2-4 strings: concrete problems this paper solved
  "gaps"        — list of 3-5 strings: open problems, limitations, or unexplored directions left by this paper
  "key_methods" — list of 2-4 strings: core technical contributions/methods

Be specific and technical. Each string should be one clear sentence.
Return ONLY the JSON object, no markdown fences.

Paper title: {title}
Year: {year}
Venue: {venue}

Abstract:
{abstract}

Existing summary (may be empty):
{summary}
"""


def _get_summaries() -> dict[str, dict]:
    """Return dict of paper_id -> summary fields from DB."""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT paper_id, problem, innovation, method, results, gaps FROM summaries"
        ).fetchall()
        return {
            r[0]: {
                "problem": r[1], "innovation": r[2],
                "method": r[3], "results": r[4], "gaps": r[5],
            }
            for r in rows
        }
    finally:
        conn.close()


def select_papers() -> list[dict]:
    """Top-100 by score + stratified sample of 100 from the rest."""
    papers = [p for p in get_papers() if p.get("abstract", "").strip()]
    papers_sorted = sorted(papers, key=lambda p: p.get("relevance_score") or 0, reverse=True)

    top100 = papers_sorted[:100]
    rest   = papers_sorted[100:]

    # Stratified sample from rest: ~80 mid, ~20 low
    mid = [p for p in rest if p.get("relevance_label") == "mid"]
    low = [p for p in rest if p.get("relevance_label") == "low"]

    random.seed(42)
    sample_mid = random.sample(mid, min(80, len(mid)))
    sample_low = random.sample(low, min(20, len(low)))

    selected = top100 + sample_mid + sample_low
    # Deduplicate by id (top100 might overlap with mid)
    seen = set()
    unique = []
    for p in selected:
        if p["id"] not in seen:
            seen.add(p["id"])
            unique.append(p)
    return unique


def extract_gap(paper: dict, summaries: dict, client: OpenAI) -> dict | None:
    summary = summaries.get(paper["id"], {})
    summary_text = ""
    if summary:
        summary_text = (
            f"Problem: {summary.get('problem','')}\n"
            f"Innovation: {summary.get('innovation','')}\n"
            f"Gaps noted: {summary.get('gaps','')}"
        )

    prompt = _PROMPT.format(
        title    = paper.get("title", ""),
        year     = paper.get("year", ""),
        venue    = paper.get("venue", "") or "unknown",
        abstract = (paper.get("abstract", "") or "")[:3000],
        summary  = summary_text or "(none)",
    )

    resp = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    raw = resp.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    data = json.loads(raw)
    return {
        "paper_id":    paper["id"],
        "title":       paper.get("title", ""),
        "year":        paper.get("year"),
        "venue":       paper.get("venue", "") or "unknown",
        "arxiv_id":    paper.get("arxiv_id", "") or paper["id"],
        "score":       paper.get("relevance_score", 0),
        "label":       paper.get("relevance_label", ""),
        "solved":      data.get("solved", []),
        "gaps":        data.get("gaps", []),
        "key_methods": data.get("key_methods", []),
    }


def run_extract(dry_run: bool = False):
    os.makedirs(GAPS_DIR, exist_ok=True)
    papers   = select_papers()
    summaries = _get_summaries()

    already_done = {f.replace(".json", "") for f in os.listdir(GAPS_DIR)
                    if f.endswith(".json") and not f.startswith("._")}

    print(f"\n  Selected {len(papers)} papers for gap extraction")
    print(f"  Summaries available: {len(summaries)}")
    print(f"  Already extracted:   {len(already_done)}")
    print(f"  To process:          {len([p for p in papers if p['id'] not in already_done])}")

    if dry_run:
        label_counts = {}
        for p in papers:
            lbl = p.get("relevance_label", "none")
            label_counts[lbl] = label_counts.get(lbl, 0) + 1
        print(f"  Label breakdown: {label_counts}")
        return

    client = OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)
    todo = [p for p in papers if p["id"] not in already_done]
    ok = failed = 0

    for i, paper in enumerate(todo, 1):
        print(f"[{i}/{len(todo)}] {paper['title'][:65]}...", flush=True)
        try:
            gap = extract_gap(paper, summaries, client)
            out_path = os.path.join(GAPS_DIR, f"{paper['id']}.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(gap, f, ensure_ascii=False, indent=2)
            print(f"  ✓  gaps: {len(gap['gaps'])}", flush=True)
            ok += 1
        except Exception as e:
            print(f"  ✗  {e}", flush=True)
            failed += 1

    print(f"\nDone: {ok} extracted, {failed} failed.")
    print(f"Total gap files: {len(os.listdir(GAPS_DIR))}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract research gaps from selected papers")
    parser.add_argument("--dry-run", action="store_true", help="Show selection stats only, no API calls")
    args = parser.parse_args()
    run_extract(dry_run=args.dry_run)
