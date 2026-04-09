"""
generate_ideas.py — Steps 2a / 2b / 2c of idea generation pipeline.

2a. Batch synthesis : group gap JSONs into batches of 20, extract common themes/gaps
2b. Full generation : synthesize all batch summaries → 20+ draft ideas (Markdown)
2c. Idea refinement : cluster draft ideas → merge similar, split broad → final ideas

Usage:
    python idea_gen/generate_ideas.py --step all     # run all three steps
    python idea_gen/generate_ideas.py --step 2a
    python idea_gen/generate_ideas.py --step 2b
    python idea_gen/generate_ideas.py --step 2c
"""

import argparse
import json
import os
import re
import sys

from openai import OpenAI

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import LLM_BASE_URL, LLM_API_KEY, LLM_MODEL

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
GAPS_DIR    = os.path.join(BASE_DIR, "gaps")
DRAFT_DIR   = os.path.join(BASE_DIR, "ideas_draft")
FINAL_DIR   = os.path.join(BASE_DIR, "ideas_final")
BATCH_FILE  = os.path.join(BASE_DIR, "batch_themes.json")

BROWSE_URL  = "http://localhost:5000/paper"

# ── Prompts ────────────────────────────────────────────────────────────────

_BATCH_PROMPT = """\
You are a research strategist in world models and visual AI generation.

Below are gap analyses from {n} recent papers. Each entry contains:
- title, solved problems, open gaps, key methods.

Your task: identify 3-6 common research themes or recurring open problems
across these papers.

For each theme output a JSON object with:
  "theme"       — short name (5-10 words)
  "description" — 2-3 sentences describing the shared gap/opportunity
  "paper_ids"   — list of paper_ids that contributed to this theme

Return a JSON array of theme objects. No markdown fences.

Papers:
{papers_json}
"""

_IDEA_PROMPT = """\
You are a senior AI researcher specializing in world models and visual generation.
Your research group uses video diffusion models (Wan, Cosmos, HunyuanVideo) as base models.

Below are clustered research themes distilled from {n_papers} recent papers.

Generate {n_ideas} distinct, concrete research ideas. Each idea should be novel,
feasible within 6-12 months, and grounded in the literature provided.

For each idea, output a JSON object with these exact keys:

  English fields:
  "id"           — integer starting from 1
  "title"        — concise idea title in English (10-15 words)
  "problem"      — the specific current problem (3-5 sentences, English)
  "innovation"   — what is novel vs. existing work (3-5 sentences, English)
  "method"       — concrete technical approach (5-8 sentences, English)

  Chinese fields (NOT a literal translation — use natural Chinese research writing):
  "title_zh"     — Chinese title (key technical terms followed by English in parentheses)
  "problem_zh"   — Chinese problem description (key terms like 世界模型(World Model) with English in parentheses)
  "innovation_zh"— Chinese innovation description (same parenthetical convention)
  "method_zh"    — Chinese method description (same parenthetical convention)

  "source_ids"   — list of paper_ids (use the exact paper_id strings from the gap data) that inspired this idea

Return a JSON array. No markdown fences.

Research themes:
{themes_json}

All gap data (for reference, paper_ids are the exact strings to use in source_ids):
{all_gaps_summary}
"""

_REFINE_PROMPT = """\
You are a research director reviewing a set of AI research ideas.

Below are {n} draft research ideas. Your task:
1. Identify ideas that are TOO SIMILAR (>70% overlap) — merge them into one stronger idea
2. Identify ideas that are TOO BROAD (covering 3+ distinct sub-problems) — split them
3. Keep well-scoped ideas as-is

For each output idea, provide a JSON object with:
  "id"           — integer starting from 1
  "title"        — concise English title
  "title_zh"     — Chinese title with key terms parenthetically annotated in English
  "problem"      — current problem (3-5 sentences, English)
  "problem_zh"   — current problem in Chinese (key technical terms with English in parentheses)
  "innovation"   — novelty vs. existing work (3-5 sentences, English)
  "innovation_zh"— innovation in Chinese (same parenthetical convention)
  "method"       — technical approach (5-8 sentences, English)
  "method_zh"    — method in Chinese (same parenthetical convention)
  "source_ids"   — paper_ids (union of merged ideas if applicable)
  "provenance"   — one of "original", "merged", "split"
  "merged_from"  — list of original idea ids if merged (else empty list)
  "split_from"   — original idea id if split (else null)

Return a JSON array. No markdown fences.

Draft ideas:
{ideas_json}
"""


# ── Helpers ────────────────────────────────────────────────────────────────

def _load_gaps() -> list[dict]:
    gaps = []
    for fname in sorted(os.listdir(GAPS_DIR)):
        if fname.endswith(".json") and not fname.startswith("._"):
            with open(os.path.join(GAPS_DIR, fname), encoding="utf-8") as f:
                gaps.append(json.load(f))
    return gaps


def _llm(client: OpenAI, prompt: str, temperature: float = 0.5) -> str:
    resp = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    raw = resp.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return raw


def _idea_to_markdown(idea: dict, paper_meta: dict, final: bool = False) -> str:
    """Render one idea dict to bilingual Markdown."""
    source_links = []
    for pid in idea.get("source_ids", []):
        meta = paper_meta.get(pid)
        if meta:
            title = meta.get("title", pid)
            year  = meta.get("year", "")
            venue = (meta.get("venue") or "").upper() or "arXiv"
        else:
            title, year, venue = pid, "", "arXiv"
        link = f"{BROWSE_URL}/paper/{pid}"
        source_links.append(f"- [{title}]({link}) [{venue} {year}]")

    provenance_en = ""
    provenance_zh = ""
    if final:
        prov = idea.get("provenance", "original")
        if prov == "merged":
            provenance_en = f"\n> **Merged from ideas:** {idea.get('merged_from', [])}\n"
            provenance_zh = f"\n> **合并自 idea：** {idea.get('merged_from', [])}\n"
        elif prov == "split":
            provenance_en = f"\n> **Split from idea:** {idea.get('split_from')}\n"
            provenance_zh = f"\n> **拆分自 idea：** {idea.get('split_from')}\n"

    sources_md = "\n".join(source_links) if source_links else "_No specific papers cited._"

    return f"""# Idea {idea['id']}: {idea['title']}
{provenance_en}
## Current Problem

{idea.get('problem', '')}

## Innovation

{idea.get('innovation', '')}

## Proposed Method

{idea.get('method', '')}

## Source Papers

{sources_md}

---

# Idea {idea['id']}（中文版）：{idea.get('title_zh', idea['title'])}
{provenance_zh}
## 当前问题

{idea.get('problem_zh', '')}

## 创新点

{idea.get('innovation_zh', '')}

## 方法

{idea.get('method_zh', '')}

## 参考文献

{sources_md}
"""


# ── Step 2a ────────────────────────────────────────────────────────────────

def step_2a(client: OpenAI):
    gaps = _load_gaps()
    if not gaps:
        print("  No gap files found. Run extract_gaps.py first.")
        return

    batch_size = 20
    batches    = [gaps[i:i+batch_size] for i in range(0, len(gaps), batch_size)]
    all_themes = []

    print(f"\n[2a] Synthesising {len(gaps)} gaps in {len(batches)} batches...")
    for i, batch in enumerate(batches, 1):
        print(f"  Batch {i}/{len(batches)} ({len(batch)} papers)...", flush=True)
        papers_json = json.dumps(
            [{"paper_id": g["paper_id"], "title": g["title"],
              "solved": g["solved"], "gaps": g["gaps"], "key_methods": g["key_methods"]}
             for g in batch],
            ensure_ascii=False, indent=2
        )
        raw    = _llm(client, _BATCH_PROMPT.format(n=len(batch), papers_json=papers_json))
        themes = json.loads(raw)
        all_themes.extend(themes)
        print(f"    → {len(themes)} themes found", flush=True)

    with open(BATCH_FILE, "w", encoding="utf-8") as f:
        json.dump(all_themes, f, ensure_ascii=False, indent=2)
    print(f"  Saved {len(all_themes)} themes to {BATCH_FILE}")


# ── Step 2b ────────────────────────────────────────────────────────────────

def step_2b(client: OpenAI):
    if not os.path.exists(BATCH_FILE):
        print("  batch_themes.json not found. Run --step 2a first.")
        return

    with open(BATCH_FILE, encoding="utf-8") as f:
        themes = json.load(f)

    gaps = _load_gaps()
    # Brief all-gaps summary for context (title + top 2 gaps per paper)
    all_gaps_summary = "\n".join(
        f"[{g['paper_id']}] {g['title']}: " + "; ".join(g["gaps"][:2])
        for g in gaps
    )

    n_ideas = max(20, len(themes) * 2)
    print(f"\n[2b] Generating {n_ideas} draft ideas from {len(themes)} themes...", flush=True)

    raw   = _llm(client, _IDEA_PROMPT.format(
        n_papers=len(gaps), n_ideas=n_ideas,
        themes_json=json.dumps(themes, ensure_ascii=False, indent=2),
        all_gaps_summary=all_gaps_summary[:8000],
    ), temperature=0.7)
    ideas = json.loads(raw)

    # Build paper metadata index for link rendering
    paper_meta = {g["paper_id"]: {"title": g["title"], "year": g["year"], "venue": g["venue"]}
                  for g in gaps}

    os.makedirs(DRAFT_DIR, exist_ok=True)
    for idea in ideas:
        fname = os.path.join(DRAFT_DIR, f"idea_{idea['id']:03d}.md")
        with open(fname, "w", encoding="utf-8") as f:
            f.write(_idea_to_markdown(idea, paper_meta, final=False))

    # Save raw JSON for step 2c
    draft_json = os.path.join(BASE_DIR, "ideas_draft.json")
    with open(draft_json, "w", encoding="utf-8") as f:
        json.dump(ideas, f, ensure_ascii=False, indent=2)

    print(f"  ✓ {len(ideas)} draft ideas written to {DRAFT_DIR}/")


# ── Step 2c ────────────────────────────────────────────────────────────────

def step_2c(client: OpenAI):
    draft_json = os.path.join(BASE_DIR, "ideas_draft.json")
    if not os.path.exists(draft_json):
        print("  ideas_draft.json not found. Run --step 2b first.")
        return

    with open(draft_json, encoding="utf-8") as f:
        draft_ideas = json.load(f)

    gaps       = _load_gaps()
    paper_meta = {g["paper_id"]: {"title": g["title"], "year": g["year"], "venue": g["venue"]}
                  for g in gaps}

    print(f"\n[2c] Refining {len(draft_ideas)} draft ideas (merge/split)...", flush=True)

    raw   = _llm(client, _REFINE_PROMPT.format(
        n=len(draft_ideas),
        ideas_json=json.dumps(draft_ideas, ensure_ascii=False, indent=2),
    ), temperature=0.4)
    final_ideas = json.loads(raw)

    os.makedirs(FINAL_DIR, exist_ok=True)
    for idea in final_ideas:
        fname = os.path.join(FINAL_DIR, f"idea_final_{idea['id']:03d}.md")
        with open(fname, "w", encoding="utf-8") as f:
            f.write(_idea_to_markdown(idea, paper_meta, final=True))

    # Save final JSON
    final_json = os.path.join(BASE_DIR, "ideas_final.json")
    with open(final_json, "w", encoding="utf-8") as f:
        json.dump(final_ideas, f, ensure_ascii=False, indent=2)

    print(f"  ✓ {len(final_ideas)} final ideas written to {FINAL_DIR}/")
    _print_provenance(final_ideas)


def _print_provenance(ideas: list[dict]):
    merged = [i for i in ideas if i.get("provenance") == "merged"]
    split  = [i for i in ideas if i.get("provenance") == "split"]
    orig   = [i for i in ideas if i.get("provenance", "original") == "original"]
    print(f"\n  Provenance: {len(orig)} original, {len(merged)} merged, {len(split)} split")


# ── Main ───────────────────────────────────────────────────────────────────

def run(step: str):
    os.makedirs(DRAFT_DIR, exist_ok=True)
    os.makedirs(FINAL_DIR, exist_ok=True)
    client = OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)

    if step in ("2a", "all"):
        step_2a(client)
    if step in ("2b", "all"):
        step_2b(client)
    if step in ("2c", "all"):
        step_2c(client)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate research ideas from gap analyses")
    parser.add_argument("--step", default="all", choices=["2a", "2b", "2c", "all"],
                        help="Which step to run (default: all)")
    args = parser.parse_args()
    run(args.step)
