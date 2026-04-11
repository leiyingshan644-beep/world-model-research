"""
plan_web.py — Web UI for browsing and marking research plans.
Port 5002, independent from browse.py (5000) and ideas_web.py (5001).

Routes:
    GET  /                   — plan list
    GET  /plan/<plan_id>     — full plan Markdown rendered
    POST /feasible/<plan_id> — mark feasible
    DELETE /feasible/<plan_id> — unmark feasible
"""

import json
import os
import re
import sys

from flask import Flask, jsonify, render_template_string, request

BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
PLANS_DIR      = os.path.join(BASE_DIR, "plans")
LOCAL_IDEAS    = os.path.join(BASE_DIR, "local_ideas.json")
PASSED_IDEAS   = os.path.join(BASE_DIR, "..", "idea_gen", "passed_ideas.json")
FEASIBLE_JSON  = os.path.join(BASE_DIR, "feasible_plans.json")

app = Flask(__name__)

IDEAS_WEB_URL = "http://localhost:5001"
BROWSE_URL    = "http://localhost:5000"


# ── Data helpers ───────────────────────────────────────────────────────────

def _load_feasible() -> dict:
    if not os.path.exists(FEASIBLE_JSON):
        return {}
    with open(FEASIBLE_JSON, encoding="utf-8") as f:
        return json.load(f)


def _save_feasible(data: dict):
    with open(FEASIBLE_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _load_idea_meta() -> dict:
    """Build {idea_id: {title, source}} from local + passed ideas."""
    meta = {}
    if os.path.exists(LOCAL_IDEAS):
        with open(LOCAL_IDEAS, encoding="utf-8") as f:
            for idea in json.load(f):
                meta[idea["id"]] = {
                    "title":  idea.get("title", idea.get("title_en", "")),
                    "source": "local",
                    "notes":  idea.get("notes", ""),
                }
    passed_path = os.path.normpath(PASSED_IDEAS)
    if os.path.exists(passed_path):
        with open(passed_path, encoding="utf-8") as f:
            for uid, idea in json.load(f).items():
                meta[uid] = {
                    "title":  idea.get("title", idea.get("title_en", "")),
                    "source": "passed",
                    "notes":  "",
                }
    return meta


def _list_plans() -> list[dict]:
    """Scan plans/ dir, return list of plan info dicts sorted by filename."""
    if not os.path.exists(PLANS_DIR):
        return []
    idea_meta = _load_idea_meta()
    feasible  = _load_feasible()
    plans = []
    for fname in sorted(os.listdir(PLANS_DIR)):
        if not fname.endswith(".md") or fname.startswith("._"):
            continue
        plan_id = fname[:-3]  # strip .md
        fpath   = os.path.join(PLANS_DIR, fname)
        # Extract idea_id from filename prefix (e.g. "local_1a_..." → "local:1a")
        m = re.match(r"^(local|final|draft)_(.+?)_", fname)
        idea_id = f"{m.group(1)}:{m.group(2)}" if m else plan_id
        # Read first non-empty line as title
        with open(fpath, encoding="utf-8") as f:
            raw = f.read()
        title_match = re.search(r"^# (.+)$", raw, re.MULTILINE)
        title = title_match.group(1).strip() if title_match else plan_id
        # Get idea source tag
        imeta  = idea_meta.get(idea_id, {})
        source = imeta.get("source", "local")
        plans.append({
            "plan_id":   plan_id,
            "idea_id":   idea_id,
            "title":     title,
            "source":    source,
            "notes":     imeta.get("notes", ""),
            "feasible":  plan_id in feasible,
            "fname":     fname,
        })
    return plans


def _render_md(md: str) -> str:
    """Minimal Markdown → HTML: headers, bold, refs, line breaks."""
    lines = []
    for line in md.splitlines():
        # Headers
        if line.startswith("### "):
            line = f"<h3>{line[4:]}</h3>"
        elif line.startswith("## "):
            line = f"<h2>{line[3:]}</h2>"
        elif line.startswith("# "):
            line = f"<h1>{line[2:]}</h1>"
        elif line.startswith("---"):
            line = "<hr>"
        elif line.startswith("- ") or line.startswith("* "):
            line = f"<li>{line[2:]}</li>"
        elif line.startswith("> "):
            line = f"<blockquote>{line[2:]}</blockquote>"
        else:
            # Bold **text**
            line = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)
            # Inline code
            line = re.sub(r"`(.+?)`", r"<code>\1</code>", line)
            # Citations [N]
            line = re.sub(r"\[(\d+)\]", r'<sup class="ref">[\1]</sup>', line)
            if line.strip():
                line = f"<p>{line}</p>"
        lines.append(line)
    return "\n".join(lines)


# ── CSS & Nav ──────────────────────────────────────────────────────────────

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background: #f5f5f5; color: #222; }
a { color: #0057d9; text-decoration: none; }
a:hover { text-decoration: underline; }
nav { background: #1a1a2e; color: #fff; padding: 12px 20px;
      display: flex; align-items: center; gap: 20px; flex-wrap: wrap; }
nav .logo { font-size: 18px; font-weight: 700; color: #fff; }
nav a { color: #aac; font-size: 14px; }
nav a:hover { color: #fff; }
.container { max-width: 960px; margin: 0 auto; padding: 24px 20px; }
.card { background: #fff; border-radius: 8px; padding: 18px 22px;
        margin-bottom: 14px; box-shadow: 0 1px 4px rgba(0,0,0,.08);
        display: flex; align-items: flex-start; gap: 16px; }
.card-body { flex: 1; }
.card h3 { font-size: 15px; margin-bottom: 6px; }
.card .meta { font-size: 12px; color: #888; }
.tag { display: inline-block; padding: 2px 8px; border-radius: 10px;
       font-size: 11px; font-weight: 600; margin-right: 6px; }
.tag-local  { background: #e8f4ff; color: #0057d9; }
.tag-passed { background: #d4edda; color: #155724; }
.feas-btn { padding: 6px 16px; border-radius: 20px; border: none;
            cursor: pointer; font-size: 13px; font-weight: 600;
            transition: all .15s; white-space: nowrap; }
.feas-btn.off { background: #f0f0f0; color: #888; }
.feas-btn.off:hover { background: #ffe066; color: #333; }
.feas-btn.on  { background: #ffe066; color: #333; }
.feas-tag { display: inline-block; background: #ffe066; color: #7a5c00;
            padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; }
.search { margin-bottom: 20px; }
.search input { width: 100%; padding: 10px 14px; border: 1px solid #ddd;
                border-radius: 6px; font-size: 15px; }
h1 { font-size: 22px; margin-bottom: 18px; }
/* Detail page */
.plan-body h1 { font-size: 22px; margin: 20px 0 10px; border-bottom: 2px solid #0057d9; padding-bottom: 6px; }
.plan-body h2 { font-size: 17px; margin: 20px 0 8px; border-bottom: 1px solid #eee; padding-bottom: 4px; color: #333; }
.plan-body h3 { font-size: 15px; margin: 16px 0 6px; color: #444; }
.plan-body p  { font-size: 14px; line-height: 1.8; margin-bottom: 10px; }
.plan-body li { font-size: 14px; line-height: 1.7; margin-left: 20px; margin-bottom: 4px; }
.plan-body hr { border: none; border-top: 1px solid #eee; margin: 20px 0; }
.plan-body blockquote { border-left: 3px solid #0057d9; padding-left: 12px;
                        color: #555; margin: 10px 0; font-size: 13px; }
.plan-body code { background: #f5f5f5; padding: 2px 5px; border-radius: 3px; font-size: 13px; }
sup.ref { color: #0057d9; font-size: 11px; }
.action-bar { display: flex; align-items: center; gap: 12px;
              background: #fff; border-radius: 8px; padding: 14px 20px;
              margin-bottom: 20px; box-shadow: 0 1px 4px rgba(0,0,0,.08); }
.count { color: #666; font-size: 13px; margin-bottom: 14px; }
"""

_NAV = """
<nav>
  <span class="logo">📋 Plan Bench</span>
  <a href="/">所有计划</a>
  <a href="/?filter=feasible">★ 可行计划</a>
  <a href="{ideas}" target="_blank">↗ Idea Bench</a>
  <a href="{browse}" target="_blank">↗ Paper Browser</a>
</nav>
""".format(ideas=IDEAS_WEB_URL, browse=BROWSE_URL)


# ── Routes ─────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    plans      = _list_plans()
    filt       = request.args.get("filter", "")
    q          = request.args.get("q", "").lower()
    if filt == "feasible":
        plans = [p for p in plans if p["feasible"]]
    if q:
        plans = [p for p in plans if q in p["title"].lower()]

    cards_html = ""
    for p in plans:
        feas_cls  = "on" if p["feasible"] else "off"
        feas_lbl  = "★ 可行" if p["feasible"] else "标为可行"
        src_cls   = "tag-passed" if p["source"] == "passed" else "tag-local"
        src_lbl   = "Passed Idea" if p["source"] == "passed" else "本地 Idea"
        notes     = f'<span class="meta">{p["notes"]}</span>' if p["notes"] else ""
        cards_html += f"""
<div class="card" id="card-{p['plan_id']}">
  <div class="card-body">
    <h3><a href="/plan/{p['plan_id']}">{p['title']}</a></h3>
    <div style="margin-top:6px">
      <span class="tag {src_cls}">{src_lbl}</span>
      <span class="meta">{p['idea_id']}</span>
      {"&nbsp;&nbsp;" + '<span class="feas-tag">★ 可行</span>' if p['feasible'] else ""}
    </div>
    {notes}
  </div>
  <button class="feas-btn {feas_cls}" onclick="toggleFeasible('{p['plan_id']}', this)">
    {feas_lbl}
  </button>
</div>"""

    total = len(_list_plans())
    shown = len(plans)
    filter_links = f"""
<div style="margin-bottom:14px;display:flex;gap:8px;align-items:center">
  <a href="/" style="{'font-weight:700' if not filt else ''}">全部 ({total})</a>
  <a href="/?filter=feasible" style="{'font-weight:700' if filt=='feasible' else ''}">
    ★ 可行 ({sum(1 for p in _list_plans() if p['feasible'])})
  </a>
</div>"""

    html = f"""<!DOCTYPE html><html><head>
<meta charset="utf-8"><title>Plan Bench</title>
<style>{_CSS}</style></head><body>
{_NAV}
<div class="container">
<h1>研究计划库</h1>
{filter_links}
<div class="search">
  <input id="q" placeholder="搜索计划标题..." value="{q}"
         oninput="filterLocal(this.value)">
</div>
<p class="count">显示 {shown} / {total} 个计划</p>
{cards_html}
</div>
<script>
function filterLocal(v) {{
  document.querySelectorAll('.card').forEach(c => {{
    const txt = c.querySelector('h3').textContent.toLowerCase();
    c.style.display = txt.includes(v.toLowerCase()) ? '' : 'none';
  }});
}}
async function toggleFeasible(planId, btn) {{
  const isOn = btn.classList.contains('on');
  const method = isOn ? 'DELETE' : 'POST';
  const r = await fetch('/feasible/' + planId, {{method}});
  const d = await r.json();
  if (d.ok) {{
    btn.classList.toggle('on', !isOn);
    btn.classList.toggle('off', isOn);
    btn.textContent = isOn ? '标为可行' : '★ 可行';
    // update inline tag
    const tag = btn.closest('.card').querySelector('.feas-tag');
    if (!isOn) {{
      if (!tag) {{
        const span = document.createElement('span');
        span.className = 'feas-tag';
        span.textContent = '★ 可行';
        btn.closest('.card').querySelector('[style*="margin-top"]').appendChild(document.createTextNode('\u00a0\u00a0'));
        btn.closest('.card').querySelector('[style*="margin-top"]').appendChild(span);
      }}
    }} else if (tag) {{ tag.previousSibling?.remove(); tag.remove(); }}
  }}
}}
</script>
</body></html>"""
    return html


@app.route("/plan/<path:plan_id>")
def plan_detail(plan_id):
    fpath = os.path.join(PLANS_DIR, plan_id + ".md")
    if not os.path.exists(fpath):
        return "Plan not found", 404
    with open(fpath, encoding="utf-8") as f:
        raw = f.read()

    feasible   = _load_feasible()
    is_feasible = plan_id in feasible
    feas_cls   = "on" if is_feasible else "off"
    feas_lbl   = "★ 已标为可行" if is_feasible else "标为可行"

    # Extract idea_id for back-link
    m = re.match(r"^(local|final|draft)_(.+?)_", plan_id)
    idea_id = f"{m.group(1)}:{m.group(2)}" if m else ""

    body_html  = _render_md(raw)

    html = f"""<!DOCTYPE html><html><head>
<meta charset="utf-8"><title>计划详情</title>
<style>{_CSS}</style></head><body>
{_NAV}
<div class="container">
<div class="action-bar">
  <a href="/">← 返回列表</a>
  <span style="color:#888;font-size:13px">{plan_id}</span>
  <button class="feas-btn {feas_cls}" id="feas-btn"
          onclick="toggleFeasible('{plan_id}', this)" style="margin-left:auto">
    {feas_lbl}
  </button>
</div>
<div class="card plan-body">
  {body_html}
</div>
</div>
<script>
async function toggleFeasible(planId, btn) {{
  const isOn = btn.classList.contains('on');
  const method = isOn ? 'DELETE' : 'POST';
  const r = await fetch('/feasible/' + planId, {{method}});
  const d = await r.json();
  if (d.ok) {{
    btn.classList.toggle('on', !isOn);
    btn.classList.toggle('off', isOn);
    btn.textContent = isOn ? '标为可行' : '★ 已标为可行';
  }}
}}
</script>
</body></html>"""
    return html


@app.route("/feasible/<path:plan_id>", methods=["POST", "DELETE"])
def feasible(plan_id):
    data = _load_feasible()
    if request.method == "POST":
        # Store title for reference
        fpath = os.path.join(PLANS_DIR, plan_id + ".md")
        title = plan_id
        if os.path.exists(fpath):
            with open(fpath, encoding="utf-8") as f:
                m = re.search(r"^# (.+)$", f.read(), re.MULTILINE)
            if m:
                title = m.group(1).strip()
        data[plan_id] = {"title": title}
    else:
        data.pop(plan_id, None)
    _save_feasible(data)
    return jsonify({"ok": True, "count": len(data)})


if __name__ == "__main__":
    app.run(debug=True, port=5002)
