"""
export_passed.py — Export all passed ideas as Markdown files to a dedicated directory.

Usage:
    python idea_gen/export_passed.py                  # export to idea_gen/passed_ideas/
    python idea_gen/export_passed.py --out /some/dir  # export to custom path
"""
import argparse
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
PASSED_JSON = os.path.join(BASE_DIR, "passed_ideas.json")
FINAL_DIR   = os.path.join(BASE_DIR, "ideas_final")
DRAFT_DIR   = os.path.join(BASE_DIR, "ideas_draft")
GAPS_DIR    = os.path.join(BASE_DIR, "gaps")
BROWSE_URL  = "http://localhost:5000"


def _load_gap_meta() -> dict:
    meta = {}
    if not os.path.exists(GAPS_DIR):
        return meta
    for fname in os.listdir(GAPS_DIR):
        if not fname.endswith(".json") or fname.startswith("._"):
            continue
        try:
            with open(os.path.join(GAPS_DIR, fname), encoding="utf-8") as f:
                g = json.load(f)
            meta[fname[:-5]] = g
        except Exception:
            pass
    return meta


def _idea_to_markdown(idea: dict, paper_meta: dict) -> str:
    source_links = []
    for pid in idea.get("source_ids", []):
        meta  = paper_meta.get(pid, {})
        title = meta.get("title", pid)
        year  = meta.get("year", "")
        venue = (meta.get("venue") or "").upper() or "arXiv"
        link  = f"{BROWSE_URL}/paper/{pid}"
        source_links.append(f"- [{title}]({link}) [{venue} {year}]")
    sources_md = "\n".join(source_links) if source_links else "_No specific papers cited._"

    return f"""# {idea['title']}

> **Saved from:** {idea.get('_source', 'final')} ideas  |  **Original ID:** {idea.get('id')}

## Current Problem

{idea.get('problem', '')}

## Innovation

{idea.get('innovation', '')}

## Proposed Method

{idea.get('method', '')}

## Source Papers

{sources_md}

---

## 当前问题

{idea.get('problem_zh') or idea.get('problem', '')}

## 创新点

{idea.get('innovation_zh') or idea.get('innovation', '')}

## 方法

{idea.get('method_zh') or idea.get('method', '')}
"""


def export(out_dir: str):
    if not os.path.exists(PASSED_JSON):
        print("No passed_ideas.json found.")
        return

    with open(PASSED_JSON, encoding="utf-8") as f:
        passed = json.load(f)

    if not passed:
        print("No passed ideas to export.")
        return

    os.makedirs(out_dir, exist_ok=True)
    paper_meta = _load_gap_meta()

    print(f"Exporting {len(passed)} passed ideas → {out_dir}/")
    for uid, idea in passed.items():
        # Sanitize title for filename
        safe_title = "".join(c if c.isalnum() or c in " -_" else "_" for c in idea.get("title", uid))
        safe_title = safe_title.strip()[:80]
        fname = f"{uid.replace(':', '_')}_{safe_title}.md"
        fpath = os.path.join(out_dir, fname)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(_idea_to_markdown(idea, paper_meta))
        print(f"  ✓ {fname}")

    # Also copy the raw JSON
    shutil.copy(PASSED_JSON, os.path.join(out_dir, "passed_ideas.json"))
    print(f"\nDone. {len(passed)} files written to {out_dir}/")
    print(f"Raw JSON also copied to {out_dir}/passed_ideas.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=os.path.join(BASE_DIR, "passed_ideas"),
                        help="Output directory (default: idea_gen/passed_ideas/)")
    args = parser.parse_args()
    export(args.out)
