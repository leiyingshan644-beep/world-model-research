import argparse
import json
import os
from datetime import datetime, timezone

from openai import OpenAI

from config import LLM_BASE_URL, LLM_API_KEY, LLM_MODEL
from utils.db import get_papers, upsert_summary, update_paper
from utils.pdf_parser import extract_text

_PROMPT = """\
You are a research paper analyst. Read the paper text below and return ONLY a \
valid JSON object with exactly these five string keys:

  problem     — The core problem addressed (2-3 sentences)
  innovation  — Key innovation vs. prior work (2-3 sentences)
  method      — Main technical approach (3-5 sentences)
  results     — Key experimental results (2-3 sentences)
  gaps        — Limitations and open problems (2-3 sentences)

Return ONLY the JSON object. No markdown fences, no explanation.

Paper text:
{text}
"""


def summarize_paper(paper: dict) -> tuple:
    """Return (summary_dict, status_str). Status is 'ok', 'no_pdf', or 'empty_pdf'."""
    pdf_path = paper.get("pdf_path")
    if not pdf_path or not os.path.exists(pdf_path):
        return None, "no_pdf"

    text = extract_text(pdf_path)
    if not text.strip():
        return None, "empty_pdf"

    client = OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)
    resp = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": _PROMPT.format(text=text)}],
        temperature=0.1,
    )
    raw = resp.choices[0].message.content.strip()

    # Strip markdown code fences if model wrapped output
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    data = json.loads(raw)
    summary = {
        "paper_id":   paper["id"],
        "problem":    data.get("problem", ""),
        "innovation": data.get("innovation", ""),
        "method":     data.get("method", ""),
        "results":    data.get("results", ""),
        "gaps":       data.get("gaps", ""),
        "model_used": LLM_MODEL,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return summary, "ok"


def run_summarize(labels: str = None, paper_id: str = None):
    if paper_id:
        clean_id = paper_id.replace("arxiv:", "")
        papers = [p for p in get_papers() if p["id"] == clean_id]
    elif labels:
        label_list = [l.strip() for l in labels.split(",")]
        papers = []
        for label in label_list:
            papers.extend(get_papers(label=label))
    else:
        papers = get_papers(status="downloaded")

    papers = [p for p in papers if p.get("pdf_path")]
    print(f"Summarizing {len(papers)} papers...")

    ok = failed = 0
    for i, p in enumerate(papers, 1):
        print(f"[{i}/{len(papers)}] {p['title'][:60]}...")
        summary, status = summarize_paper(p)
        if status == "ok":
            upsert_summary(summary)
            update_paper(p["id"], status="summarized")
            print("  ✓")
            ok += 1
        else:
            print(f"  ✗ {status}")
            failed += 1

    print(f"\nDone: {ok} summarized, {failed} failed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI summarization of downloaded papers")
    parser.add_argument("--label",     help="Comma-separated labels, e.g. high or high,mid")
    parser.add_argument("--id", dest="paper_id", help="Summarize a single paper, e.g. arxiv:2301.04589")
    args = parser.parse_args()
    run_summarize(labels=args.label, paper_id=args.paper_id)
