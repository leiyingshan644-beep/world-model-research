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
GAPS_DIR    = os.path.join(BASE_DIR, "gaps")
PASSED_JSON = os.path.join(BASE_DIR, "passed_ideas.json")  # permanent, never overwritten by pipeline

BROWSE_URL = "http://localhost:5000"

app = Flask(__name__)

# Pre-load gap metadata once at startup (paper_id → {title, year, venue})
def _build_paper_meta() -> dict:
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
            meta[pid] = {"title": g.get("title", pid), "year": g.get("year", ""),
                         "venue": g.get("venue", "")}
        except Exception:
            pass
    return meta

_PAPER_META: dict = {}

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


def _load_passed() -> dict:
    """Return {uid: idea_dict}. uid = '{source}:{id}' e.g. 'final:3'"""
    if not os.path.exists(PASSED_JSON):
        return {}
    with open(PASSED_JSON, encoding="utf-8") as f:
        return json.load(f)


def _save_passed(passed: dict):
    with open(PASSED_JSON, "w", encoding="utf-8") as f:
        json.dump(passed, f, ensure_ascii=False, indent=2)


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
  <a href="/passed" style="color:#f7c948;font-weight:600">★ Passed Ideas</a>
  <a href="/run">Run Pipeline</a>
  <a href="{browse}" target="_blank">↗ Paper Browser</a>
</nav>
""".format(browse=BROWSE_URL)

_LIST_HTML = """<!DOCTYPE html><html><head>
<meta charset="utf-8"><title>Ideas — {{title}}</title>
<style>""" + _BASE_CSS + """
.search { margin-bottom: 20px; }
.search input { width: 100%; padding: 10px 14px; border: 1px solid #ddd;
                border-radius: 6px; font-size: 15px; }
.card-footer { display:flex; align-items:center; justify-content:space-between; margin-top:10px; }
.pass-btn { padding:4px 14px; border-radius:20px; border:none; cursor:pointer;
            font-size:12px; font-weight:600; transition:all .15s; }
.pass-btn.off { background:#f0f0f0; color:#666; }
.pass-btn.off:hover { background:#ffe066; color:#333; }
.pass-btn.on  { background:#f7c948; color:#333; }
.tag-passed { background:#fff3cd; color:#856404; }
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
      {%- if idea.passed %}<span class="tag tag-passed">★ passed</span>{%- endif %}
      {%- if idea.provenance == 'merged' %}<span class="tag tag-merged">merged</span>{%- endif %}
      {%- if idea.provenance == 'split'  %}<span class="tag tag-split">split</span>{%- endif %}
    </h3>
    <p>{{idea.problem[:220]}}{% if idea.problem|length > 220 %}…{% endif %}</p>
    <div class="card-footer">
      <span class="badge">Sources: {{idea.source_ids|length}} papers</span>
      <button class="pass-btn {{'on' if idea.passed else 'off'}}"
              id="pb-{{idea.source}}-{{idea.id}}"
              onclick="togglePass('{{idea.source}}', {{idea.id}}, this)">
        {{'★ Passed' if idea.passed else '☆ Pass'}}
      </button>
    </div>
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
async function togglePass(source, id, btn) {
  const isPassed = btn.classList.contains('on');
  const method = isPassed ? 'DELETE' : 'POST';
  const r = await fetch('/pass/' + source + '/' + id, {method});
  const d = await r.json();
  if (d.ok) {
    if (d.passed) {
      btn.classList.replace('off','on'); btn.textContent = '★ Passed';
    } else {
      btn.classList.replace('on','off'); btn.textContent = '☆ Pass';
    }
  }
}
</script></body></html>"""

_DETAIL_HTML = """<!DOCTYPE html><html><head>
<meta charset="utf-8"><title>{{idea.title}}</title>
<style>""" + _BASE_CSS + """
.lang-toggle { display:flex; gap:8px; margin-bottom:20px; }
.lang-btn { padding:6px 16px; border-radius:20px; border:1px solid #ccc;
            background:#fff; cursor:pointer; font-size:13px; }
.lang-btn.active { background:#0057d9; color:#fff; border-color:#0057d9; }
.lang-section { display:none; }
.lang-section.active { display:block; }
hr.divider { border:none; border-top:2px solid #eee; margin:32px 0; }
</style></head><body>
""" + _NAV + """
<div class="container">
  <p style="margin-bottom:12px"><a href="{{back_url}}">← Back to list</a></p>
  <div class="card">
    <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:10px;margin-bottom:8px">
      <div>
        <h1 style="font-size:20px;margin:0 0 6px">
          {{idea.id}}. {{idea.title}}
          {%- if idea.title_zh %} <span style="color:#666;font-size:15px">/ {{idea.title_zh}}</span>{%- endif %}
        </h1>
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
        {%- if passed %}<span class="tag" style="background:#fff3cd;color:#856404">★ Passed</span>{%- endif %}
      </div>
      <button id="pass-btn"
              style="padding:8px 18px;border-radius:20px;border:none;cursor:pointer;font-weight:600;
                     white-space:nowrap;background:{{'#f7c948' if passed else '#f0f0f0'}};
                     color:{{'#333' if passed else '#666'}};"
              onclick="togglePass('{{source}}', {{idea.id}}, this)">
        {{'★ Passed' if passed else '☆ Pass this Idea'}}
      </button>
    </div>

    <div class="lang-toggle">
      <button class="lang-btn active" onclick="switchLang('en', this)">English</button>
      <button class="lang-btn" onclick="switchLang('zh', this)">中文</button>
      <button class="lang-btn" onclick="switchLang('both', this)">双语</button>
    </div>

    <div class="prose">
      <!-- English -->
      <div class="lang-section active" id="sec-en">
        <h2>Current Problem</h2><p>{{idea.problem}}</p>
        <h2>Innovation</h2><p>{{idea.innovation}}</p>
        <h2>Proposed Method</h2><p>{{idea.method}}</p>
      </div>
      <!-- Chinese -->
      <div class="lang-section" id="sec-zh">
        <h2>当前问题</h2><p>{{idea.problem_zh or idea.problem}}</p>
        <h2>创新点</h2><p>{{idea.innovation_zh or idea.innovation}}</p>
        <h2>方法</h2><p>{{idea.method_zh or idea.method}}</p>
      </div>
      <!-- Both -->
      <div class="lang-section" id="sec-both">
        <h2>Current Problem / 当前问题</h2>
        <p>{{idea.problem}}</p>
        <p style="color:#555;margin-top:6px">{{idea.problem_zh or ''}}</p>
        <h2>Innovation / 创新点</h2>
        <p>{{idea.innovation}}</p>
        <p style="color:#555;margin-top:6px">{{idea.innovation_zh or ''}}</p>
        <h2>Proposed Method / 方法</h2>
        <p>{{idea.method}}</p>
        <p style="color:#555;margin-top:6px">{{idea.method_zh or ''}}</p>
      </div>

      <hr class="divider">
      <h2>Source Papers / 参考文献</h2>
      <ul>
      {%- for src in sources %}
        <li><a href="{{src.url}}" target="_blank">{{src.title}}</a>
            <span class="badge">[{{src.venue}} {{src.year}}]</span></li>
      {%- else %}
        <li style="color:#999">No specific papers cited.</li>
      {%- endfor %}
      </ul>
    </div>
  </div>
</div>
<script>
function switchLang(lang, btn) {
  document.querySelectorAll('.lang-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  document.querySelectorAll('.lang-section').forEach(s => s.classList.remove('active'));
  document.getElementById('sec-' + lang).classList.add('active');
}
async function togglePass(source, id, btn) {
  const isPassed = btn.textContent.includes('★');
  const method = isPassed ? 'DELETE' : 'POST';
  const r = await fetch('/pass/' + source + '/' + id, {method});
  const d = await r.json();
  if (d.ok) {
    if (d.passed) {
      btn.textContent = '★ Passed';
      btn.style.background = '#f7c948'; btn.style.color = '#333';
    } else {
      btn.textContent = '☆ Pass this Idea';
      btn.style.background = '#f0f0f0'; btn.style.color = '#666';
    }
  }
}
</script>
</body></html>"""

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

def _idea_list_context(ideas: list[dict], final: bool, passed: dict | None = None) -> list[dict]:
    prefix = "/idea/" if final else "/draft/"
    source = "final" if final else "draft"
    if passed is None:
        passed = _load_passed()
    return [
        {
            "id":          i.get("id"),
            "title":       i.get("title", ""),
            "problem":     i.get("problem", ""),
            "provenance":  i.get("provenance", "original"),
            "merged_from": i.get("merged_from", []),
            "source_ids":  i.get("source_ids", []),
            "url":         f"{prefix}{i.get('id')}",
            "passed":      f"{source}:{i.get('id')}" in passed,
            "source":      source,
        }
        for i in ideas
    ]


def _source_context(idea: dict) -> list[dict]:
    sources = []
    for pid in idea.get("source_ids", []):
        meta = _PAPER_META.get(pid, {})
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
    ideas  = _load_ideas(FINAL_JSON)
    idea   = next((i for i in ideas if i.get("id") == idea_id), None)
    if not idea:
        return "Idea not found", 404
    passed = _load_passed()
    return render_template_string(_DETAIL_HTML, idea=idea, sources=_source_context(idea),
                                  final=True, back_url="/",
                                  passed=f"final:{idea_id}" in passed, source="final")


@app.route("/draft/<int:idea_id>")
def draft_detail(idea_id: int):
    ideas  = _load_ideas(DRAFT_JSON)
    idea   = next((i for i in ideas if i.get("id") == idea_id), None)
    if not idea:
        return "Idea not found", 404
    passed = _load_passed()
    return render_template_string(_DETAIL_HTML, idea=idea, sources=_source_context(idea),
                                  final=False, back_url="/draft",
                                  passed=f"draft:{idea_id}" in passed, source="draft")


@app.route("/passed")
def passed_list():
    passed = _load_passed()
    ideas  = list(passed.values())
    ctx    = [
        {
            "id":         i.get("id"),
            "title":      i.get("title", ""),
            "problem":    i.get("problem", ""),
            "provenance": i.get("provenance", "original"),
            "merged_from":i.get("merged_from", []),
            "source_ids": i.get("source_ids", []),
            "source":     i.get("_source", "final"),
            "passed":     True,
            "url":        f"/{i.get('_source','idea')}/{i.get('id')}",
        }
        for i in ideas
    ]
    return render_template_string(_LIST_HTML, ideas=ctx, title=f"★ Passed Ideas")


@app.route("/pass/<source>/<int:idea_id>", methods=["POST", "DELETE"])
def toggle_pass(source: str, idea_id: int):
    if source not in ("final", "draft"):
        return jsonify({"ok": False}), 400
    json_path = FINAL_JSON if source == "final" else DRAFT_JSON
    ideas     = _load_ideas(json_path)
    idea      = next((i for i in ideas if i.get("id") == idea_id), None)
    if not idea:
        return jsonify({"ok": False, "reason": "idea not found"}), 404

    passed = _load_passed()
    uid    = f"{source}:{idea_id}"

    if request.method == "POST":
        idea["_source"] = source
        passed[uid]     = idea
        _save_passed(passed)
        return jsonify({"ok": True, "passed": True})
    else:  # DELETE = unpass
        passed.pop(uid, None)
        _save_passed(passed)
        return jsonify({"ok": True, "passed": False})


@app.route("/run")
def run_page():
    stats = {
        "gaps":   len([f for f in os.listdir(GAPS_DIR) if f.endswith(".json") and not f.startswith("._")]) if os.path.exists(GAPS_DIR) else 0,
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
    _PAPER_META.update(_build_paper_meta())
    print(f"  Loaded metadata for {len(_PAPER_META)} papers")
    print("  Idea Bench running at http://localhost:5001")
    print("  Paper browser at     http://localhost:5000")
    app.run(host="0.0.0.0", port=5001, debug=False)
