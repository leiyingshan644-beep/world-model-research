"""
generate_plan.py — Generate a bilingual research plan for a given idea.

Pipeline:
  1. Load idea (from local_ideas.json or passed_ideas.json)
  2. Extract keywords → search real papers (local DB + arXiv + S2)
  3. LLM writes plan sections grounded in retrieved papers
  4. Output bilingual Markdown to plans/{idea_id}.md

Usage:
    python plan_gen/generate_plan.py --id local:1a
    python plan_gen/generate_plan.py --id final:3
    python plan_gen/generate_plan.py --all-local
    python plan_gen/generate_plan.py --all-passed
"""

import argparse
import json
import os
import sys

from openai import OpenAI

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import LLM_BASE_URL, LLM_API_KEY, LLM_MODEL

BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
LOCAL_IDEAS    = os.path.join(BASE_DIR, "local_ideas.json")
PASSED_IDEAS   = os.path.join(BASE_DIR, "..", "idea_gen", "passed_ideas.json")
PLANS_DIR      = os.path.join(BASE_DIR, "plans")

# ── Prompts ────────────────────────────────────────────────────────────────

_KEYWORD_PROMPT = """\
You are a research librarian. Given a research idea, extract 5-8 English search keywords
most likely to retrieve relevant papers on arXiv or Semantic Scholar.

Focus on technical concepts, method names, and domain terms. Return a JSON array of strings only.

Idea title: {title}
Problem: {problem}
Innovation: {innovation}
"""

_PLAN_PROMPT = """\
你是一位世界模型和视觉生成领域的资深研究员，正在为一个研究想法撰写正式的研究计划书。

【重要约束】
1. 引言和当前问题部分必须大量引用文献，引用格式为 [序号]，每段至少3-4处引用。
2. 只能引用我提供的论文列表中的文献，绝对不能编造不存在的文献。
3. 如果某处需要引用但列表中没有合适文献，用 [待补充] 标注，不得捏造。
4. 关键术语格式：中文术语后括号标注英文，如"世界模型(World Model)"。
5. 研究计划必须基于idea的实际内容，不要无关扩展。
6. 实验部分只写与本idea创新点直接相关的实验，不相关的不写。
7. 开销部分根据实际需要估算，不要照抄模版。

【输出格式】
按以下章节结构输出，每个章节之间用 --- 分隔：

# 一、引言
（高引用密度，600-900字，介绍领域背景→现有方法→核心不足→本文方案，每个论断都要有文献支撑）

# 二、当前核心问题
（按子问题列出，每个问题配引用，200-400字）

# 三、研究创新点
（逐点列出，每个创新点50-100字，无需引用）

# 四、实验设计
（只写与创新点直接相关的实验，每个实验写：目的、环境、步骤、预期结果；包含消融实验）

# 五、项目开销估算
（器材/算力/存储/API，按实际需要估算，给出合理区间）

# 六、参考文献
（列出引言和问题部分实际引用的文献，格式：[序号] 作者. 题目[J/C]. 来源, 年份.）

---

研究想法：
标题：{title}
问题：{problem}
创新点：{innovation}

可用文献列表（只能引用这些，不得编造其他）：
{papers_list}
"""


# ── Helpers ────────────────────────────────────────────────────────────────

def _load_idea(idea_id: str) -> dict:
    """Load idea by ID from local_ideas.json or passed_ideas.json."""
    if idea_id.startswith("local:"):
        with open(LOCAL_IDEAS, encoding="utf-8") as f:
            ideas = json.load(f)
        match = next((i for i in ideas if i["id"] == idea_id), None)
        if not match:
            raise ValueError(f"Idea '{idea_id}' not found in local_ideas.json")
        return match

    # passed idea (final:N or draft:N)
    passed_path = os.path.normpath(PASSED_IDEAS)
    if not os.path.exists(passed_path):
        raise FileNotFoundError(f"passed_ideas.json not found at {passed_path}")
    with open(passed_path, encoding="utf-8") as f:
        passed = json.load(f)
    if idea_id not in passed:
        raise ValueError(f"Idea '{idea_id}' not found in passed_ideas.json")
    return passed[idea_id]


def _llm(client: OpenAI, prompt: str, temperature: float = 0.4) -> str:
    resp = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    return resp.choices[0].message.content.strip()


def _extract_keywords(client: OpenAI, idea: dict) -> list[str]:
    """Use LLM to extract search keywords, fall back to idea's keywords_en field."""
    if idea.get("keywords_en"):
        return idea["keywords_en"]
    raw = _llm(client, _KEYWORD_PROMPT.format(
        title=idea.get("title", ""),
        problem=idea.get("problem", ""),
        innovation=idea.get("innovation", ""),
    ), temperature=0.2)
    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        return json.loads(raw)
    except Exception:
        # Fallback: split by comma
        return [k.strip().strip('"') for k in raw.split(",")][:8]


def _format_papers_list(papers: list[dict]) -> str:
    """Format retrieved papers as a numbered list for the LLM prompt."""
    lines = []
    for i, p in enumerate(papers, 1):
        venue_year = f"{p['venue']} {p['year']}".strip()
        abstract   = p.get("abstract", "")[:200]
        arxiv_note = f" [arXiv:{p['arxiv_id']}]" if p.get("arxiv_id") else ""
        lines.append(
            f"[{i}] {p['title']}{arxiv_note} ({venue_year})\n"
            f"     摘要: {abstract}"
        )
    return "\n\n".join(lines)


def _idea_title(idea: dict) -> str:
    return idea.get("title") or idea.get("title_en", "Untitled")


def _safe_filename(idea_id: str, title: str) -> str:
    safe = "".join(c if c.isalnum() or c in " -_\u4e00-\u9fff" else "_" for c in title)
    safe = safe.strip()[:60]
    return f"{idea_id.replace(':', '_')}_{safe}.md"


# ── Core: generate one plan ─────────────────────────────────────────────────

def generate_plan(idea_id: str, client: OpenAI, verbose: bool = True) -> str:
    """Generate a research plan for one idea. Returns output file path."""
    if verbose:
        print(f"\n{'='*60}")
        print(f"Generating plan for: {idea_id}")

    # 1. Load idea
    idea = _load_idea(idea_id)
    title = _idea_title(idea)
    if verbose:
        print(f"  Title: {title}")

    # 2. Extract keywords
    keywords = _extract_keywords(client, idea)
    if verbose:
        print(f"  Keywords: {keywords}")

    # 3. Search papers
    from plan_gen.search_papers import search_all
    papers = search_all(keywords, n=30, verbose=verbose)

    # 4. Build prompt and generate plan
    papers_list = _format_papers_list(papers)
    prompt = _PLAN_PROMPT.format(
        title=title,
        problem=idea.get("problem", ""),
        innovation=idea.get("innovation", ""),
        papers_list=papers_list,
    )

    if verbose:
        print(f"  Calling LLM ({LLM_MODEL})...")
    plan_text = _llm(client, prompt, temperature=0.4)

    # 5. Assemble final Markdown
    output = f"# {title}\n\n"
    output += f"> **Idea ID:** {idea_id}  |  **Keywords:** {', '.join(keywords)}\n\n"
    output += "---\n\n"
    output += plan_text
    output += "\n\n---\n\n"
    output += "_本计划由 plan_gen/generate_plan.py 自动生成，引用文献均来自真实数据库。_\n"

    # 6. Save
    os.makedirs(PLANS_DIR, exist_ok=True)
    fname = _safe_filename(idea_id, title)
    fpath = os.path.join(PLANS_DIR, fname)
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(output)

    if verbose:
        print(f"  ✓ Saved: {fpath}")
    return fpath


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate research plans from ideas")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--id",          help="Generate plan for one idea (e.g. local:1a, final:3)")
    group.add_argument("--all-local",   action="store_true", help="Generate plans for all local ideas")
    group.add_argument("--all-passed",  action="store_true", help="Generate plans for all passed ideas")
    args = parser.parse_args()

    client = OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)

    if args.id:
        generate_plan(args.id, client)

    elif args.all_local:
        with open(LOCAL_IDEAS, encoding="utf-8") as f:
            ideas = json.load(f)
        for idea in ideas:
            try:
                generate_plan(idea["id"], client)
            except Exception as e:
                print(f"  [ERROR] {idea['id']}: {e}")

    elif args.all_passed:
        passed_path = os.path.normpath(PASSED_IDEAS)
        with open(passed_path, encoding="utf-8") as f:
            passed = json.load(f)
        for uid in passed:
            try:
                generate_plan(uid, client)
            except Exception as e:
                print(f"  [ERROR] {uid}: {e}")


if __name__ == "__main__":
    main()
