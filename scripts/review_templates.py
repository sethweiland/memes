#!/usr/bin/env python3
"""
Local Flask web app for reviewing AI-generated template descriptions.

Usage:
    python scripts/review_templates.py
    # Opens at http://localhost:5000
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Flask, request, jsonify, render_template_string

from src.core.templates import TemplatesCatalog, TEMPLATE_DESCRIPTIONS

AI_DESCRIPTIONS_PATH = Path("data/ai_template_descriptions.json")
REVIEW_QUEUE_PATH = Path("data/template_descriptions_review.json")

app = Flask(__name__)


def load_json(path: Path) -> dict:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def save_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# HTML Templates
# ---------------------------------------------------------------------------

BASE_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       background: #f5f5f5; color: #333; }
nav { background: #1a1a2e; color: #fff; padding: 12px 24px; display: flex;
      align-items: center; gap: 24px; }
nav a { color: #e0e0e0; text-decoration: none; font-size: 14px; }
nav a:hover { color: #fff; }
nav a.active { color: #fff; font-weight: 600; border-bottom: 2px solid #4fc3f7; }
nav .brand { font-size: 18px; font-weight: 700; margin-right: 16px; }
.container { max-width: 1100px; margin: 24px auto; padding: 0 16px; }
h1 { margin-bottom: 16px; }
.counter { background: #e3f2fd; padding: 8px 16px; border-radius: 6px;
           display: inline-block; margin-bottom: 16px; font-size: 14px; }
.card { background: #fff; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,.12);
        margin-bottom: 20px; padding: 20px; display: flex; gap: 20px; }
.card img { width: 200px; height: auto; object-fit: contain; border-radius: 4px;
            background: #fafafa; flex-shrink: 0; }
.card-body { flex: 1; min-width: 0; }
.card-body h3 { margin-bottom: 8px; }
.meta { font-size: 13px; color: #666; margin-bottom: 8px; }
.meta span { margin-right: 12px; }
textarea { width: 100%; min-height: 80px; padding: 8px; border: 1px solid #ddd;
           border-radius: 4px; font-family: inherit; font-size: 14px; resize: vertical; }
.actions { margin-top: 12px; display: flex; gap: 8px; }
.btn { padding: 8px 16px; border: none; border-radius: 4px; cursor: pointer;
       font-size: 14px; font-weight: 500; }
.btn-approve { background: #4caf50; color: #fff; }
.btn-approve:hover { background: #43a047; }
.btn-reject { background: #f44336; color: #fff; }
.btn-reject:hover { background: #e53935; }
.btn-unapprove { background: #ff9800; color: #fff; }
.btn-unapprove:hover { background: #fb8c00; }
.btn:disabled { opacity: .5; cursor: not-allowed; }
.empty { text-align: center; padding: 60px; color: #999; }
.stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
             gap: 16px; margin-top: 16px; }
.stat-card { background: #fff; border-radius: 8px; padding: 20px; text-align: center;
             box-shadow: 0 1px 3px rgba(0,0,0,.12); }
.stat-card .number { font-size: 36px; font-weight: 700; color: #1a1a2e; }
.stat-card .label { font-size: 13px; color: #666; margin-top: 4px; }
.fade-out { opacity: 0; transform: translateX(40px);
            transition: opacity .3s, transform .3s; }
"""

NAV_HTML = """
<nav>
  <span class="brand">Bluegrass Review</span>
  <a href="/" class="{{ 'active' if page == 'review' }}">Review Queue</a>
  <a href="/approved" class="{{ 'active' if page == 'approved' }}">Approved</a>
  <a href="/stats" class="{{ 'active' if page == 'stats' }}">Stats</a>
</nav>
"""

REVIEW_PAGE = (
    "<!DOCTYPE html><html><head><meta charset='utf-8'>"
    "<meta name='viewport' content='width=device-width,initial-scale=1'>"
    "<title>Review Queue</title><style>" + BASE_CSS + "</style></head><body>"
    + NAV_HTML.replace("{{ 'active' if page == 'review' }}", "active")
        .replace("{{ 'active' if page == 'approved' }}", "")
        .replace("{{ 'active' if page == 'stats' }}", "")
    + """
<div class="container">
<h1>Review Queue</h1>
<div class="counter" id="counter"></div>
<div id="cards">{{ cards_html }}</div>
</div>
<script>
function updateCounter() {
  var cards = document.querySelectorAll('.card:not(.fade-out)');
  var total = {{ total }};
  var remaining = cards.length;
  document.getElementById('counter').textContent =
    (total - remaining) + ' of ' + total + ' reviewed';
}
updateCounter();

function doAction(templateId, action, cardEl) {
  var url = '/api/' + action + '/' + templateId;
  var body = {};
  if (action === 'approve') {
    var ta = cardEl.querySelector('textarea');
    if (ta) body.description = ta.value;
  }
  var btns = cardEl.querySelectorAll('.btn');
  btns.forEach(function(b) { b.disabled = true; });
  fetch(url, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  }).then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.ok) {
        cardEl.classList.add('fade-out');
        setTimeout(function() { cardEl.remove(); updateCounter(); }, 300);
      } else {
        alert('Error: ' + (data.error || 'unknown'));
        btns.forEach(function(b) { b.disabled = false; });
      }
    }).catch(function(err) {
      alert('Request failed: ' + err);
      btns.forEach(function(b) { b.disabled = false; });
    });
}
</script>
</body></html>"""
)

APPROVED_PAGE = (
    "<!DOCTYPE html><html><head><meta charset='utf-8'>"
    "<meta name='viewport' content='width=device-width,initial-scale=1'>"
    "<title>Approved Descriptions</title><style>" + BASE_CSS + "</style></head><body>"
    + NAV_HTML.replace("{{ 'active' if page == 'review' }}", "")
        .replace("{{ 'active' if page == 'approved' }}", "active")
        .replace("{{ 'active' if page == 'stats' }}", "")
    + """
<div class="container">
<h1>Approved Descriptions</h1>
<div class="counter">{{ count }} approved templates</div>
<div id="cards">{{ cards_html }}</div>
</div>
<script>
function unapprove(templateId, cardEl) {
  var btns = cardEl.querySelectorAll('.btn');
  btns.forEach(function(b) { b.disabled = true; });
  fetch('/api/unapprove/' + templateId, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'}
  }).then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.ok) {
        cardEl.classList.add('fade-out');
        setTimeout(function() { cardEl.remove(); }, 300);
      } else {
        alert('Error: ' + (data.error || 'unknown'));
        btns.forEach(function(b) { b.disabled = false; });
      }
    });
}
</script>
</body></html>"""
)

STATS_PAGE = (
    "<!DOCTYPE html><html><head><meta charset='utf-8'>"
    "<meta name='viewport' content='width=device-width,initial-scale=1'>"
    "<title>Stats</title><style>" + BASE_CSS + "</style></head><body>"
    + NAV_HTML.replace("{{ 'active' if page == 'review' }}", "")
        .replace("{{ 'active' if page == 'approved' }}", "")
        .replace("{{ 'active' if page == 'stats' }}", "active")
    + """
<div class="container">
<h1>Template Stats</h1>
<div class="stat-grid">
  <div class="stat-card"><div class="number">{{ total }}</div><div class="label">Total in Catalog</div></div>
  <div class="stat-card"><div class="number">{{ handwritten }}</div><div class="label">Hand-written</div></div>
  <div class="stat-card"><div class="number">{{ ai_approved }}</div><div class="label">AI Approved</div></div>
  <div class="stat-card"><div class="number">{{ review_queue }}</div><div class="label">Review Queue</div></div>
  <div class="stat-card"><div class="number">{{ undescribed }}</div><div class="label">Undescribed</div></div>
</div>
</div>
</body></html>"""
)


def _escape(text: str) -> str:
    """Minimal HTML escaping."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _build_review_card(tid: str, entry: dict, catalog: TemplatesCatalog) -> str:
    template = catalog.templates.get(tid)
    img_url = template.url if template else ""
    name = _escape(entry.get("name", tid))
    desc = _escape(entry.get("description", ""))
    panel = _escape(entry.get("panel_structure", ""))
    pattern = _escape(entry.get("comedic_pattern", ""))
    confidence = entry.get("confidence", "?")
    box_count = template.box_count if template else "?"

    return f"""
    <div class="card" id="card-{tid}">
      <img src="{img_url}" alt="{name}" loading="lazy">
      <div class="card-body">
        <h3>{name}</h3>
        <div class="meta">
          <span>ID: {tid}</span>
          <span>Boxes: {box_count}</span>
          <span>Confidence: {confidence}</span>
        </div>
        <div class="meta">
          <span>Panel: {panel}</span>
          <span>Pattern: {pattern}</span>
        </div>
        <textarea>{desc}</textarea>
        <div class="actions">
          <button class="btn btn-approve"
            onclick="doAction('{tid}','approve',document.getElementById('card-{tid}'))">
            Approve
          </button>
          <button class="btn btn-reject"
            onclick="doAction('{tid}','reject',document.getElementById('card-{tid}'))">
            Reject
          </button>
        </div>
      </div>
    </div>"""


def _build_approved_card(tid: str, entry: dict, catalog: TemplatesCatalog) -> str:
    template = catalog.templates.get(tid)
    img_url = template.url if template else ""
    name = _escape(entry.get("name", tid))
    desc = _escape(entry.get("description", ""))
    panel = _escape(entry.get("panel_structure", ""))
    pattern = _escape(entry.get("comedic_pattern", ""))
    confidence = entry.get("confidence", "?")

    return f"""
    <div class="card" id="card-{tid}">
      <img src="{img_url}" alt="{name}" loading="lazy">
      <div class="card-body">
        <h3>{name}</h3>
        <div class="meta">
          <span>ID: {tid}</span>
          <span>Confidence: {confidence}</span>
        </div>
        <div class="meta">
          <span>Panel: {panel}</span>
          <span>Pattern: {pattern}</span>
        </div>
        <p style="margin-top:8px;">{desc}</p>
        <div class="actions">
          <button class="btn btn-unapprove"
            onclick="unapprove('{tid}',document.getElementById('card-{tid}'))">
            Move to Review
          </button>
        </div>
      </div>
    </div>"""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def review_page():
    review_queue = load_json(REVIEW_QUEUE_PATH)
    catalog = TemplatesCatalog()
    cards = "".join(
        _build_review_card(tid, entry, catalog)
        for tid, entry in review_queue.items()
    )
    if not cards:
        cards = '<div class="empty">Review queue is empty.</div>'
    total = len(review_queue)
    html = REVIEW_PAGE.replace("{{ cards_html }}", cards).replace("{{ total }}", str(total))
    return html


@app.route("/approved")
def approved_page():
    ai_descriptions = load_json(AI_DESCRIPTIONS_PATH)
    catalog = TemplatesCatalog()
    cards = "".join(
        _build_approved_card(tid, entry, catalog)
        for tid, entry in ai_descriptions.items()
    )
    if not cards:
        cards = '<div class="empty">No approved descriptions yet.</div>'
    html = APPROVED_PAGE.replace("{{ cards_html }}", cards).replace(
        "{{ count }}", str(len(ai_descriptions))
    )
    return html


@app.route("/stats")
def stats_page():
    catalog = TemplatesCatalog()
    ai_descriptions = load_json(AI_DESCRIPTIONS_PATH)
    review_queue = load_json(REVIEW_QUEUE_PATH)

    total = len(catalog.templates)
    handwritten = sum(
        1 for t in catalog.templates.values() if t.name in TEMPLATE_DESCRIPTIONS
    )
    ai_approved = len(ai_descriptions)
    in_review = len(review_queue)
    undescribed = total - handwritten - ai_approved - in_review

    html = (
        STATS_PAGE.replace("{{ total }}", str(total))
        .replace("{{ handwritten }}", str(handwritten))
        .replace("{{ ai_approved }}", str(ai_approved))
        .replace("{{ review_queue }}", str(in_review))
        .replace("{{ undescribed }}", str(max(0, undescribed)))
    )
    return html


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

@app.route("/api/approve/<template_id>", methods=["POST"])
def api_approve(template_id):
    review_queue = load_json(REVIEW_QUEUE_PATH)
    ai_descriptions = load_json(AI_DESCRIPTIONS_PATH)

    if template_id not in review_queue:
        return jsonify({"ok": False, "error": "Not in review queue"}), 404

    entry = review_queue.pop(template_id)

    # Accept edited description from request body
    body = request.get_json(silent=True) or {}
    if body.get("description"):
        entry["description"] = body["description"]

    ai_descriptions[template_id] = entry

    save_json(REVIEW_QUEUE_PATH, review_queue)
    save_json(AI_DESCRIPTIONS_PATH, ai_descriptions)

    return jsonify({"ok": True})


@app.route("/api/reject/<template_id>", methods=["POST"])
def api_reject(template_id):
    review_queue = load_json(REVIEW_QUEUE_PATH)

    if template_id not in review_queue:
        return jsonify({"ok": False, "error": "Not in review queue"}), 404

    review_queue.pop(template_id)
    save_json(REVIEW_QUEUE_PATH, review_queue)

    return jsonify({"ok": True})


@app.route("/api/unapprove/<template_id>", methods=["POST"])
def api_unapprove(template_id):
    ai_descriptions = load_json(AI_DESCRIPTIONS_PATH)
    review_queue = load_json(REVIEW_QUEUE_PATH)

    if template_id not in ai_descriptions:
        return jsonify({"ok": False, "error": "Not in approved"}), 404

    entry = ai_descriptions.pop(template_id)
    review_queue[template_id] = entry

    save_json(AI_DESCRIPTIONS_PATH, ai_descriptions)
    save_json(REVIEW_QUEUE_PATH, review_queue)

    return jsonify({"ok": True})


@app.route("/api/stats")
def api_stats():
    catalog = TemplatesCatalog()
    ai_descriptions = load_json(AI_DESCRIPTIONS_PATH)
    review_queue = load_json(REVIEW_QUEUE_PATH)

    total = len(catalog.templates)
    handwritten = sum(
        1 for t in catalog.templates.values() if t.name in TEMPLATE_DESCRIPTIONS
    )
    ai_approved = len(ai_descriptions)
    in_review = len(review_queue)
    undescribed = total - handwritten - ai_approved - in_review

    return jsonify({
        "total": total,
        "handwritten": handwritten,
        "ai_approved": ai_approved,
        "review_queue": in_review,
        "undescribed": max(0, undescribed),
    })


if __name__ == "__main__":
    port = 5050
    print(f"Starting review UI at http://localhost:{port}")
    app.run(debug=False, port=port)
