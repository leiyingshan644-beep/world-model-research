"""
translate_ideas.py — Post-process ideas_final.json / ideas_draft.json
to add Chinese (_zh) fields using free Google Translate.

Usage:
    python idea_gen/translate_ideas.py             # translate final ideas
    python idea_gen/translate_ideas.py --draft     # translate draft ideas
"""
import argparse
import json
import os
import sys
import time

from deep_translator import GoogleTranslator

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
FINAL_JSON = os.path.join(BASE_DIR, "ideas_final.json")
DRAFT_JSON = os.path.join(BASE_DIR, "ideas_draft.json")
FINAL_DIR  = os.path.join(BASE_DIR, "ideas_final")
DRAFT_DIR  = os.path.join(BASE_DIR, "ideas_draft")
GAPS_DIR   = os.path.join(BASE_DIR, "gaps")
BROWSE_URL = "http://localhost:5000"


def _translate(text: str, translator: GoogleTranslator, max_len: int = 4800) -> str:
    """Translate English text to Chinese, chunking if needed."""
    if not text or not text.strip():
        return ""
    # Split into sentences to stay under limit
    sentences = text.replace(". ", ".\n").split("\n")
    chunks, current = [], ""
    for s in sentences:
        if len(current) + len(s) > max_len:
            chunks.append(current.strip())
            current = s + " "
        else:
            current += s + " "
    if current.strip():
        chunks.append(current.strip())

    parts = []
    for chunk in chunks:
        try:
            parts.append(translator.translate(chunk))
            time.sleep(0.3)  # be polite to free API
        except Exception as e:
            print(f"    [translate error: {e}]")
            parts.append(chunk)
    return " ".join(parts)


def _load_gap_meta() -> dict:
    meta = {}
    if not os.path.exists(GAPS_DIR):
        return meta
    for fname in os.listdir(GAPS_DIR):
        if not fname.endswith(".json") or fname.startswith("._"):
            continue
        pid = fname[:-5]
        try:
            with open(os.path.join(GAPS_DIR, fname), encoding="utf-8") as f:
                g = json.load(f)
            meta[pid] = g
        except Exception:
            pass
    return meta


def _idea_to_markdown(idea: dict, paper_meta: dict, final: bool) -> str:
    source_links = []
    for pid in idea.get("source_ids", []):
        meta = paper_meta.get(pid, {})
        title = meta.get("title", pid)
        year  = meta.get("year", "")
        venue = (meta.get("venue") or "").upper() or "arXiv"
        link  = f"{BROWSE_URL}/paper/{pid}"
        source_links.append(f"- [{title}]({link}) [{venue} {year}]")
    sources_md = "\n".join(source_links) if source_links else "_No specific papers cited._"

    provenance_en = provenance_zh = ""
    if final:
        prov = idea.get("provenance", "original")
        if prov == "merged":
            provenance_en = f"\n> **Merged from ideas:** {idea.get('merged_from', [])}\n"
            provenance_zh = f"\n> **合并自 idea：** {idea.get('merged_from', [])}\n"
        elif prov == "split":
            provenance_en = f"\n> **Split from idea:** {idea.get('split_from')}\n"
            provenance_zh = f"\n> **拆分自 idea：** {idea.get('split_from')}\n"

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


def run(use_draft: bool = False):
    json_path = DRAFT_JSON if use_draft else FINAL_JSON
    out_dir   = DRAFT_DIR  if use_draft else FINAL_DIR
    prefix    = "idea_" if use_draft else "idea_final_"

    if not os.path.exists(json_path):
        print(f"No ideas found at {json_path}")
        return

    with open(json_path, encoding="utf-8") as f:
        ideas = json.load(f)

    translator = GoogleTranslator(source="en", target="zh-CN")
    paper_meta = _load_gap_meta()
    changed = 0

    print(f"Translating {len(ideas)} ideas...")
    for i, idea in enumerate(ideas, 1):
        # Skip if already has Chinese fields
        if idea.get("title_zh") and idea.get("problem_zh"):
            print(f"  [{i}/{len(ideas)}] already translated, skipping")
            continue

        print(f"  [{i}/{len(ideas)}] {idea['title'][:60]}...", flush=True)
        idea["title_zh"]      = _translate(idea.get("title", ""), translator)
        idea["problem_zh"]    = _translate(idea.get("problem", ""), translator)
        idea["innovation_zh"] = _translate(idea.get("innovation", ""), translator)
        idea["method_zh"]     = _translate(idea.get("method", ""), translator)
        print(f"    → {idea['title_zh'][:50]}")
        changed += 1

    # Save updated JSON
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(ideas, f, ensure_ascii=False, indent=2)

    # Re-render Markdown files
    os.makedirs(out_dir, exist_ok=True)
    for idea in ideas:
        fname = os.path.join(out_dir, f"{prefix}{idea['id']:03d}.md")
        with open(fname, "w", encoding="utf-8") as f:
            f.write(_idea_to_markdown(idea, paper_meta, final=not use_draft))

    print(f"\nDone: {changed} translated, {len(ideas)-changed} skipped.")
    print(f"Markdown files updated in {out_dir}/")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--draft", action="store_true", help="Translate draft ideas instead of final")
    args = parser.parse_args()
    run(use_draft=args.draft)
