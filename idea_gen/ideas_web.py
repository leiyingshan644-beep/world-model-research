"""
ideas_web.py — Web UI for browsing and generating research ideas.
Runs on port 5001, independent from browse.py (port 5000).

Routes:
    GET  /              — idea list (final > draft fallback)
    GET  /idea/<id>     — full Markdown rendering of one idea
    GET  /draft         — draft ideas list
    GET  /run           — pipeline control page
    POST /run/<step>    — trigger extract / 2a / 2b / 2c / all
    GET  /status        — JSON status of pipeline artifacts
"""

import json
import os
import subprocess
import sys
import threading

from flask import Flask, jsonify, redirect, render_template_string, request, url_for

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
FINAL_DIR  = os.path.join(BASE_DIR, "ideas_final")
DRAFT_DIR  = os.path.join(BASE_DIR, "ideas_draft")
FINAL_JSON = os.path.join(BASE_DIR, "ideas_final.json")
DRAFT_JSON = os.path.join(BASE_DIR, "ideas_draft.json")
GAPS_DIR   = os.path.join(BASE_DIR, "gaps")

BROWSE_URL = "http://localhost:5000"

app = Flask(__name__)

# ── Running jobs tracker ───────────────────────────────────────────────────
_jobs: dict[str, dict] = {}  # step -> {status, log}
_jobs_lock = threading.Lock()


def _run_job(step: str, script: str, args: list[str]):
    with _jobs_lock:
        _jobs[step] = {"status": "running", "log": ""}

    try:
        proc = subprocess.run(
            [sys.executable, script] + args,
            capture_output=True, text=True, cwd=os.path.dirname(BASE_DIR),
        )
        log = proc.stdout + proc.stderr
        status = "done" if proc.returncode == 0 else "error"
    except Exception as e:
        log    = str(e)
        status = "error"

    with _jobs_lock:
        _jobs[step] = {"status": status, "log": log}


# ── Data loaders ───────────────────────────────────────────────────────────

def _load_ideas(json_path: str) -> list[dict]:
    if not os.path.exists(json_path):
        return []
    with open(json_path, encoding="utf-8") as f:
        return json.load(f)


def _md_to_sections(md: str) -> dict:
    """Parse Markdown into title + sections dict."""
    lines  = md.splitlines()
    title  = ""
    sections: dict[str, list[str]] = {}
    current = None

    for line in lines:
        if line.startswith("# ") and not title:
            title = line[2:].strip()
        elif line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
        elif current is not None:
            sections[current].append(line)

    return {
        "title": title,
        "sections": {k: "\n".join(v).strip() for k, v in sections.items()},
    }


def _load_idea_md(idea_id: int, final: bool = True) -> str | None:
    d    = FINAL_DIR if final else DRAFT_DIR
    prefix = "idea_final_" if final else "idea_"
    fname  = os.path.join(d, f"{prefix}{idea_id:03d}.md")
    if not os.path.exists(fname):
        return None
    with open(fname, encoding="utf-8") as f:
        return f.read()


# ── Templates ─────────────────────────────────────────────────────────────

_BASE_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background: #f5f5f5; color: #222; }
a { color: #0057d9; text-decoration: none; }
a:hover { text-decoration: underline; }
.container { max-width: 1000px; margin: 0 auto; padding: 24px 20px; }
nav { background: #1a1a2e; color: #fff; padding: 12px 20px; display: flex;
      align-items: center; gap: 24px; }
nav .logo { font-size: 18px; font-weight: 700; color: #fff; }
nav a { color: #aac; font-size: 14px; }
nav a:hover { color: #fff; }
.card { background: #fff; border-radius: 8px; padding: 20px 24px;
        margin-bottom: 16px; box-shadow: 0 1px 4px rgba(0,0,0,.08); }
.card h3 { font-size: 16px; margin-bottom: 8px; }
.card p  { font-size: 14px; color: #555; line-height: 1.5; }
.tag { display: inline-block; padding: 2px 8px; border-radius: 12px;
       font-size: 12px; margin-right: 6px; }
.tag-final  { background: #d4edda; color: #155724; }
.tag-draft  { background: #fff3cd; color: #856404; }
.tag-merged { background: #cce5ff; color: #004085; }
.tag-split  { background: #f8d7da; color: #721c24; }
.badge { font-size: 12px; color: #888; }
h1 { font-size: 24px; margin-bottom: 20px; }
h2 { font-size: 18px; margin: 24px 0 10px; border-bottom: 1px solid #eee; padding-bottom: 6px; }
pre { background: #f8f8f8; padding: 12px; border-radius: 6px; overflow-x: auto;
      font-size: 13px; white-space: pre-wrap; }
.prose p  { margin-bottom: 12px; line-height: 1.7; font-size: 15px; }
.prose ul { margin: 8px 0 12px 20px; }
.prose li { margin-bottom: 6px; line-height: 1.6; font-size: 14px; }
.btn { display: inline-block; padding: 8px 18px; border-radius: 6px;
       border: none; cursor: pointer; font-size: 14px; font-weight: 500; }
.btn-primary { background: #0057d9; color: #fff; }
.btn-primary:hover { background: #0047b5; }
.btn-sm { padding: 4px 12px; font-size: 13px; }
.status-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px,1fr)); gap: 12px; }
.stat-box { background: #fff; border-radius: 8px; padding: 16px;
            box-shadow: 0 1px 4px rgba(0,0,0,.08); text-align: center; }
.stat-box .num { font-size: 32px; font-weight: 700; color: #0057d9; }
.stat-box .lbl { font-size: 13px; color: #888; margin-top: 4px; }
.log-box { background: #1e1e1e; color: #d4d4d4; border-radius: 6px;
           padding: 14px; font-size: 13px; white-space: pre-wrap;
           max-height: 400px; overflow-y: auto; margin-top: 12px; }
"""

_NAV = """
<nav>
  <span class="logo">💡 Idea Bench</span>
  <a href="/">Final Ideas</a>
  <a href="/draft">Draft Ideas</a>
  <a href="/run">Run Pipeline</a>
  <a href="{browse}" target="_blank">↗ Paper Browser</a>
</nav>
""".format(browse=BROWSE_URL)

_LIST_HTML = """<!DOCTYPE html><html><head>
<meta charset="utf-8"><title>Ideas — {{title}}</title>
<style>""" + _BASE_CSS + """
.search {{ margin-bottom: 20px; }}
.search input {{ width: 100%; padding: 10px 14px; border: 1px solid #ddd;
                 border-radius: 6px; font-size: 15px; }}
</style></head><body>
""" + _NAV + """
<div class="container">
  <h1>{{title}} <span class="badge">({{ideas|length}} ideas)</span></h1>
  <div class="search"><input type="text" id="q" placeholder="Search ideas…" oninput="filter()"></div>
  <div id="list">
  {%- for idea in ideas %}
  <div class="card" data-text="{{idea.title|lower}} {{idea.problem|lower}}">
    <h3>
      <a href="{{idea.url}}">{{idea.id}}. {{idea.title}}</a>
      {%- if idea.provenance == 'merged' %}<span class="tag tag-merged">merged</span>{%- endif %}
      {%- if idea.provenance == 'split'  %}<span class="tag tag-split">split</span>{%- endif %}
    </h3>
    <p>{{idea.problem[:220]}}{% if idea.problem|length > 220 %}…{% endif %}</p>
    <p style="margin-top:8px" class="badge">
      Sources: {{idea.source_ids|length}} papers
    </p>
  </div>
  {%- endfor %}
  </div>
</div>
<script>
function filter() {
  const q = document.getElementById('q').value.toLowerCase();
  document.querySelectorAll('#list .card').forEach(c => {
    c.style.display = c.dataset.text.includes(q) ? '' : 'none';
  });
}
</script></body></html>"""

_DETAIL_HTML = """<!DOCTYPE html><html><head>
<meta charset="utf-8"><title>{{idea.title}}</title>
<style>""" + _BASE_CSS + """</style></head><body>
""" + _NAV + """
<div class="container">
  <p style="margin-bottom:12px"><a href="{{back_url}}">← Back to list</a></p>
  <div class="card">
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px">
      <h1 style="font-size:20px;margin:0">{{idea.id}}. {{idea.title}}</h1>
      {%- if final %}
        {%- if idea.provenance == 'merged' %}
          <span class="tag tag-merged">merged from {{idea.merged_from}}</span>
        {%- elif idea.provenance == 'split' %}
          <span class="tag tag-split">split from #{{idea.split_from}}</span>
        {%- else %}
          <span class="tag tag-final">final</span>
        {%- endif %}
      {%- else %}
        <span class="tag tag-draft">draft</span>
      {%- endif %}
    </div>
    <div class="prose">
      <h2>Current Problem</h2><p>{{idea.problem}}</p>
      <h2>Innovation</h2><p>{{idea.innovation}}</p>
      <h2>Proposed Method</h2><p>{{idea.method}}</p>
      <h2>Source Papers</h2>
      <ul>
      {%- for src in sources %}
        <li><a href="{{src.url}}" target="_blank">{{src.title}}</a>
            <span class="badge">[{{src.venue}} {{src.year}}]</span></li>
      {%- endfor %}
      </ul>
    </div>
  </div>
</div></body></html>"""

_RUN_HTML = """<!DOCTYPE html><html><head>
<meta charset="utf-8"><title>Run Pipeline</title>
<style>""" + _BASE_CSS + """
.step-card { background:#fff;border-radius:8px;padding:20px 24px;
             margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,.08); }
.step-card h3 { margin-bottom:6px; }
.step-card p  { font-size:14px;color:#555;margin-bottom:12px; }
</style></head><body>
""" + _NAV + """
<div class="container">
  <h1>Pipeline Control</h1>

  <div class="status-grid" style="margin-bottom:24px">
    <div class="stat-box"><div class="num">{{stats.gaps}}</div><div class="lbl">Gap files</div></div>
    <div class="stat-box"><div class="num">{{stats.drafts}}</div><div class="lbl">Draft ideas</div></div>
    <div class="stat-box"><div class="num">{{stats.finals}}</div><div class="lbl">Final ideas</div></div>
  </div>

  <div class="step-card">
    <h3>Step 1 — Extract Gaps</h3>
    <p>Select ~200 papers and extract research gaps via LLM. Skips already-processed papers.</p>
    <button class="btn btn-primary" onclick="trigger('extract')">Run Extract</button>
  </div>
  <div class="step-card">
    <h3>Step 2a — Batch Synthesis</h3>
    <p>Group gaps into batches of 20, find common themes. Requires Step 1.</p>
    <button class="btn btn-primary" onclick="trigger('2a')">Run 2a</button>
  </div>
  <div class="step-card">
    <h3>Step 2b — Generate Draft Ideas</h3>
    <p>Synthesise all themes into 20+ draft idea reports. Requires Step 2a.</p>
    <button class="btn btn-primary" onclick="trigger('2b')">Run 2b</button>
  </div>
  <div class="step-card">
    <h3>Step 2c — Refine Ideas</h3>
    <p>Merge similar ideas, split broad ideas → final reports. Requires Step 2b.</p>
    <button class="btn btn-primary" onclick="trigger('2c')">Run 2c</button>
  </div>
  <div class="step-card">
    <h3>Run All Steps</h3>
    <p>Extract → 2a → 2b → 2c in sequence. May take 10-20 minutes.</p>
    <button class="btn btn-primary" onclick="trigger('all')">Run All</button>
  </div>

  <div id="log-section" style="display:none">
    <h2 style="margin-top:24px">Job Log</h2>
    <div id="log" class="log-box"></div>
  </div>
</div>
<script>
async function trigger(step) {
  document.getElementById('log-section').style.display = '';
  document.getElementById('log').textContent = 'Starting ' + step + '...';
  const r = await fetch('/run/' + step, {method:'POST'});
  const d = await r.json();
  if (d.status === 'started') poll(step);
}
async function poll(step) {
  const r = await fetch('/status');
  const d = await r.json();
  const job = d.jobs[step] || {};
  document.getElementById('log').textContent = job.log || '(running…)';
  if (job.status === 'running' || !job.status) {
    setTimeout(() => poll(step), 2000);
  } else {
    document.getElementById('log').textContent += '\\n\\n[' + job.status.toUpperCase() + ']';
    setTimeout(() => location.reload(), 1500);
  }
}
</script></body></html>"""


# ── Routes ─────────────────────────────────────────────────────────────────

def _idea_list_context(ideas: list[dict], final: bool) -> list[dict]:
    prefix = "/idea/" if final else "/draft/"
    return [
        {
            "id":          i.get("id"),
            "title":       i.get("title", ""),
            "problem":     i.get("problem", ""),
            "provenance":  i.get("provenance", "original"),
            "merged_from": i.get("merged_from", []),
            "source_ids":  i.get("source_ids", []),
            "url":         f"{prefix}{i.get('id')}",
        }
        for i in ideas
    ]


def _source_context(idea: dict) -> list[dict]:
    gap_meta = {}
    for fname in os.listdir(GAPS_DIR):
        if not fname.endswith(".json"):
            continue
        pid = fname[:-5]
        fpath = os.path.join(GAPS_DIR, fname)
        with open(fpath, encoding="utf-8") as f:
            g = json.load(f)
        gap_meta[pid] = g

    sources = []
    for pid in idea.get("source_ids", []):
        meta = gap_meta.get(pid, {})
        sources.append({
            "title": meta.get("title", pid),
            "year":  meta.get("year", ""),
            "venue": (meta.get("venue") or "arXiv").upper(),
            "url":   f"{BROWSE_URL}/paper/{pid}",
        })
    return sources


@app.route("/")
def index():
    ideas = _load_ideas(FINAL_JSON)
    if not ideas:
        ideas = _load_ideas(DRAFT_JSON)
        title = "Draft Ideas (no final ideas yet)"
    else:
        title = "Final Research Ideas"
    ctx = _idea_list_context(ideas, final=bool(os.path.exists(FINAL_JSON)))
    return render_template_string(_LIST_HTML, ideas=ctx, title=title)


@app.route("/draft")
def draft_list():
    ideas = _load_ideas(DRAFT_JSON)
    ctx   = _idea_list_context(ideas, final=False)
    return render_template_string(_LIST_HTML, ideas=ctx, title="Draft Ideas")


@app.route("/idea/<int:idea_id>")
def idea_detail(idea_id: int):
    ideas = _load_ideas(FINAL_JSON)
    idea  = next((i for i in ideas if i.get("id") == idea_id), None)
    if not idea:
        return "Idea not found", 404
    sources = _source_context(idea)
    return render_template_string(_DETAIL_HTML, idea=idea, sources=sources,
                                  final=True, back_url="/")


@app.route("/draft/<int:idea_id>")
def draft_detail(idea_id: int):
    ideas = _load_ideas(DRAFT_JSON)
    idea  = next((i for i in ideas if i.get("id") == idea_id), None)
    if not idea:
        return "Idea not found", 404
    sources = _source_context(idea)
    return render_template_string(_DETAIL_HTML, idea=idea, sources=sources,
                                  final=False, back_url="/draft")


@app.route("/run")
def run_page():
    stats = {
        "gaps":   len([f for f in os.listdir(GAPS_DIR) if f.endswith(".json")]) if os.path.exists(GAPS_DIR) else 0,
        "drafts": len(_load_ideas(DRAFT_JSON)),
        "finals": len(_load_ideas(FINAL_JSON)),
    }
    return render_template_string(_RUN_HTML, stats=stats)


@app.route("/run/<step>", methods=["POST"])
def run_step(step: str):
    valid = {"extract", "2a", "2b", "2c", "all"}
    if step not in valid:
        return jsonify({"error": "invalid step"}), 400

    with _jobs_lock:
        job = _jobs.get(step, {})
        if job.get("status") == "running":
            return jsonify({"status": "already_running"})

    script_map = {
        "extract": (os.path.join(BASE_DIR, "extract_gaps.py"),    []),
        "2a":      (os.path.join(BASE_DIR, "generate_ideas.py"),  ["--step", "2a"]),
        "2b":      (os.path.join(BASE_DIR, "generate_ideas.py"),  ["--step", "2b"]),
        "2c":      (os.path.join(BASE_DIR, "generate_ideas.py"),  ["--step", "2c"]),
        "all":     (os.path.join(BASE_DIR, "generate_ideas.py"),  ["--step", "all"]),
    }
    # For "all", also run extract first
    if step == "all":
        # chain: extract then all
        def _chain():
            _run_job("extract", os.path.join(BASE_DIR, "extract_gaps.py"), [])
            _run_job("all",     os.path.join(BASE_DIR, "generate_ideas.py"), ["--step", "all"])
        t = threading.Thread(target=_chain, daemon=True)
    else:
        script, args = script_map[step]
        t = threading.Thread(target=_run_job, args=(step, script, args), daemon=True)

    t.start()
    return jsonify({"status": "started"})


@app.route("/status")
def status():
    with _jobs_lock:
        return jsonify({"jobs": dict(_jobs)})


if __name__ == "__main__":
    os.makedirs(GAPS_DIR,   exist_ok=True)
    os.makedirs(DRAFT_DIR,  exist_ok=True)
    os.makedirs(FINAL_DIR,  exist_ok=True)
    print("  Idea Bench running at http://localhost:5001")
    print("  Paper browser at     http://localhost:5000")
    app.run(host="0.0.0.0", port=5001, debug=False)
