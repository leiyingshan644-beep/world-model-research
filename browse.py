import os
import subprocess

from flask import Flask, render_template_string, request, jsonify

from utils.db import (get_papers, get_summary, search_papers, update_my_thoughts,
                      update_paper, add_tag_to_paper, remove_tag_from_paper,
                      get_tags_for_paper, get_all_tags, get_papers_by_tag)

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Templates (inline — no separate template files needed)
# ---------------------------------------------------------------------------

_LIST_HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>World Model Papers</title>
<style>
  body{font-family:sans-serif;max-width:1200px;margin:0 auto;padding:20px}
  .filters{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap;align-items:center}
  .filters select,.filters input{padding:6px 10px;border:1px solid #ccc;border-radius:4px}
  .filters input{flex:1;min-width:200px}
  button{padding:6px 14px;background:#007bff;color:#fff;border:none;border-radius:4px;cursor:pointer}
  button:hover{background:#0056b3}
  table{width:100%;border-collapse:collapse}
  th,td{text-align:left;padding:8px;border-bottom:1px solid #eee}
  th{background:#f5f5f5;font-weight:600}
  .badge{padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600}
  .badge-high{background:#d4edda;color:#155724}
  .badge-mid{background:#fff3cd;color:#856404}
  .badge-low{background:#f8d7da;color:#721c24}
  .badge-skip{background:#e9ecef;color:#6c757d}
  .badge-summarized{background:#cce5ff;color:#004085}
  .badge-downloaded{background:#e2e3e5;color:#383d41}
  .badge-collected{background:#f8f9fa;color:#6c757d}
  a{color:#007bff;text-decoration:none}
  a:hover{text-decoration:underline}
  .count{color:#666;margin-bottom:8px;font-size:14px}
</style>
</head>
<body>
<h1>World Model Papers</h1>
<form method="get" action="/">
  <div class="filters">
    <input name="q" value="{{ q }}" placeholder="搜索标题/摘要...">
    <select name="venue">
      <option value="">所有会议</option>
      {% for v in ['neurips','icml','iclr','cvpr','corl'] %}
      <option value="{{ v }}" {{ 'selected' if venue==v }}>{{ v.upper() }}</option>
      {% endfor %}
    </select>
    <select name="year">
      <option value="">所有年份</option>
      {% for y in range(2025,2020,-1) %}
      <option value="{{ y }}" {{ 'selected' if year==y|string }}>{{ y }}</option>
      {% endfor %}
    </select>
    <select name="label">
      <option value="">所有标记</option>
      {% for l in ['high','mid','low','skip'] %}
      <option value="{{ l }}" {{ 'selected' if label==l }}>{{ l }}</option>
      {% endfor %}
    </select>
    <select name="status">
      <option value="">所有状态</option>
      {% for s in ['collected','downloaded','summarized'] %}
      <option value="{{ s }}" {{ 'selected' if status==s }}>{{ s }}</option>
      {% endfor %}
    </select>
    <button type="submit">筛选</button>
  </div>
</form>
<p class="count">共 {{ papers|length }} 篇</p>
<table>
  <tr><th>标题</th><th>会议</th><th>年份</th><th>标记</th><th>状态</th><th>得分</th></tr>
  {% for p in papers %}
  <tr>
    <td><a href="{{ url_for('paper_detail', paper_id=p.id) }}">{{ p.title[:80] }}</a></td>
    <td>{{ (p.venue or '')|upper }}</td>
    <td>{{ p.year or '' }}</td>
    <td><span class="badge badge-{{ p.relevance_label or '' }}">{{ p.relevance_label or '-' }}</span></td>
    <td><span class="badge badge-{{ p.status }}">{{ p.status }}</span></td>
    <td>{{ '%.2f'|format(p.relevance_score or 0) }}</td>
  </tr>
  {% endfor %}
</table>
</body>
</html>"""

_DETAIL_HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>{{ paper.title }}</title>
<style>
  body{font-family:sans-serif;max-width:900px;margin:0 auto;padding:20px}
  .meta{color:#555;margin-bottom:20px;font-size:14px}
  .section{margin-bottom:20px}
  .section h3{margin-bottom:6px;color:#222;border-bottom:1px solid #eee;padding-bottom:4px}
  .section p{margin:0;line-height:1.7}
  textarea{width:100%;min-height:100px;padding:8px;border:1px solid #ccc;
           border-radius:4px;font-family:inherit;font-size:14px;box-sizing:border-box}
  .btn{padding:8px 16px;border:none;border-radius:4px;cursor:pointer;color:#fff}
  .btn-save{background:#007bff}.btn-save:hover{background:#0056b3}
  .btn-pdf{background:#28a745;margin-left:10px}.btn-pdf:hover{background:#1e7e34}
  .no-summary{color:#999;font-style:italic}
  a{color:#007bff;text-decoration:none}
  code{background:#f5f5f5;padding:2px 6px;border-radius:3px;font-size:13px}
</style>
</head>
<body>
<p><a href="/">← 返回列表</a></p>
<h1>{{ paper.title }}</h1>
<div class="meta">
  {{ (paper.venue or '')|upper }} {{ paper.year or '' }} &nbsp;|&nbsp;
  标记: <strong>{{ paper.relevance_label or '-' }}</strong> &nbsp;|&nbsp;
  状态: <strong>{{ paper.status }}</strong> &nbsp;|&nbsp;
  得分: {{ '%.2f'|format(paper.relevance_score or 0) }}
  {% if paper.pdf_path %}
  <button class="btn btn-pdf" onclick="openPdf()">打开 PDF</button>
  {% endif %}
</div>
<div class="section"><h3>摘要</h3><p>{{ paper.abstract or '(无)' }}</p></div>

{% if summary %}
<div class="section"><h3>核心问题</h3><p>{{ summary.problem }}</p></div>
<div class="section"><h3>Innovation</h3><p>{{ summary.innovation }}</p></div>
<div class="section"><h3>方法</h3><p>{{ summary.method }}</p></div>
<div class="section"><h3>实验结果</h3><p>{{ summary.results }}</p></div>
<div class="section"><h3>不足与空白</h3><p>{{ summary.gaps }}</p></div>
<div class="section">
  <h3>我的思考</h3>
  <textarea id="thoughts">{{ summary.my_thoughts or '' }}</textarea><br><br>
  <button class="btn btn-save" onclick="saveThoughts()">保存</button>
</div>
{% else %}
<p class="no-summary">
  尚无 AI 总结。运行：<code>python summarize.py --id {{ paper.id }}</code>
</p>
{% endif %}

<script>
function openPdf() {
  fetch('/open_pdf/{{ paper.id }}', {method:'POST'});
}
function saveThoughts() {
  fetch('/save_thoughts/{{ paper.id }}', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({thoughts: document.getElementById('thoughts').value})
  }).then(r=>r.json()).then(d=>{ if(d.ok) alert('已保存'); else alert('保存失败'); });
}
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    q      = request.args.get("q", "")
    venue  = request.args.get("venue", "")
    year   = request.args.get("year", "")
    label  = request.args.get("label", "")
    status = request.args.get("status", "")

    if q:
        papers = search_papers(q)
        # Apply any active dropdown filters on top of the text search results
        if venue:
            papers = [p for p in papers if p.get("venue") == venue]
        if year:
            papers = [p for p in papers if str(p.get("year") or "") == year]
        if label:
            papers = [p for p in papers if p.get("relevance_label") == label]
        if status:
            papers = [p for p in papers if p.get("status") == status]
    else:
        papers = get_papers(
            venue=venue or None,
            year=int(year) if year else None,
            label=label or None,
            status=status or None,
        )
    return render_template_string(
        _LIST_HTML, papers=papers,
        q=q, venue=venue, year=year, label=label, status=status,
    )


@app.route("/paper/<path:paper_id>")
def paper_detail(paper_id):
    all_papers = get_papers()
    paper = next((p for p in all_papers if p["id"] == paper_id), None)
    if not paper:
        return "Paper not found", 404
    summary = get_summary(paper_id)
    return render_template_string(_DETAIL_HTML, paper=paper, summary=summary)


@app.route("/open_pdf/<path:paper_id>", methods=["POST"])
def open_pdf(paper_id):
    all_papers = get_papers()
    paper = next((p for p in all_papers if p["id"] == paper_id), None)
    if paper and paper.get("pdf_path") and os.path.exists(paper["pdf_path"]):
        subprocess.Popen(["open", paper["pdf_path"]])
        return jsonify({"ok": True})
    return jsonify({"ok": False})


@app.route("/save_thoughts/<path:paper_id>", methods=["POST"])
def save_thoughts(paper_id):
    data = request.get_json() or {}
    update_my_thoughts(paper_id, data.get("thoughts", ""))
    return jsonify({"ok": True})


@app.route("/tags", methods=["GET"])
def list_tags():
    return jsonify({"tags": get_all_tags()})


@app.route("/tags/<path:paper_id>", methods=["GET"])
def paper_tags_get(paper_id):
    return jsonify({"tags": get_tags_for_paper(paper_id)})


@app.route("/tags/<path:paper_id>", methods=["POST"])
def paper_tags_add(paper_id):
    data = request.get_json() or {}
    tag = data.get("tag", "").strip()
    if tag:
        add_tag_to_paper(paper_id, tag)
    return jsonify({"ok": bool(tag)})


@app.route("/tags/<path:paper_id>/<tag_name>", methods=["DELETE"])
def paper_tags_remove(paper_id, tag_name):
    remove_tag_from_paper(paper_id, tag_name)
    return jsonify({"ok": True})


@app.route("/boost/<path:paper_id>", methods=["POST"])
def set_boost(paper_id):
    data = request.get_json() or {}
    try:
        boost = float(data.get("boost", 0))
        boost = max(-1.0, min(1.0, boost))
    except (TypeError, ValueError):
        boost = 0.0
    update_paper(paper_id, manual_boost=boost)
    return jsonify({"ok": True, "boost": boost})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
