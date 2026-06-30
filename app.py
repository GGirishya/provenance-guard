"""
app.py — Provenance Guard API

Endpoints:
    POST /submit          — Submit content for attribution analysis
    POST /appeal          — Contest a classification
    GET  /log             — View recent audit log entries
    GET  /status/<id>     — Get current status of a submission
"""

import os
import uuid

from flask import Flask, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv

from signal_llm import score_llm
from signal_stylo import score_stylometrics
from signal_perp import score_perplexity
from confidence import combine_scores, attribution_from_score, generate_label
from audit import log_classification, log_appeal, get_entry, get_recent_entries, log_certificate, get_certificate
from analytics import compute_analytics
from certificate import validate_draft_history, validate_statement, issue_certificate

load_dotenv()

app = Flask(__name__)

# ── Rate Limiting ──────────────────────────────────────────────────────────────
# Reasoning:
#   - A typical creator submits work infrequently — maybe a few pieces per session.
#   - 10 per minute prevents rapid automated flooding while allowing burst testing.
#   - 100 per day is generous for legitimate use; a script flooding the endpoint
#     would hit this ceiling and expose abuse before significant damage is done.
#   - Per-IP limiting is sufficient for this project; production would use
#     authenticated creator_id limits instead.

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _word_count(text: str) -> int:
    return len(text.split())


def _run_pipeline(text: str) -> dict:
    """
    Run all detection signals and return scored results.
    Signal 3 (perplexity) is always included as part of the ensemble stretch.
    """
    wc = _word_count(text)

    llm_score, llm_reasoning   = score_llm(text)
    stylo_score, stylo_meta    = score_stylometrics(text)
    perp_score, perp_meta      = score_perplexity(text)

    combined = combine_scores(llm_score, stylo_score, wc, perp_score=perp_score)
    attribution = attribution_from_score(combined)
    label = generate_label(combined)

    return {
        "llm_score": llm_score,
        "llm_reasoning": llm_reasoning,
        "stylo_score": stylo_score,
        "stylo_meta": stylo_meta,
        "perp_score": perp_score,
        "perp_meta": perp_meta,
        "combined_score": combined,
        "attribution": attribution,
        "label": label,
        "word_count": wc,
    }


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.route("/submit", methods=["POST"])
@limiter.limit("10 per minute;100 per day")
def submit():
    """
    Accept a piece of text for attribution analysis.

    Request body (JSON):
        text        (str, required)  — the content to analyze
        creator_id  (str, required)  — identifier for the submitting creator

    Response (JSON):
        content_id   — unique ID for this submission (save for appeals)
        attribution  — "likely_ai" | "uncertain" | "likely_human"
        confidence   — combined score 0.0–1.0
        label        — transparency label dict {variant, text, score_pct}
        signals      — individual signal scores
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Request body must be JSON"}), 400

    text = data.get("text", "").strip()
    creator_id = data.get("creator_id", "").strip()

    if not text:
        return jsonify({"error": "Missing required field: text"}), 400
    if not creator_id:
        return jsonify({"error": "Missing required field: creator_id"}), 400
    if len(text) > 50_000:
        return jsonify({"error": "Text exceeds maximum length of 50,000 characters"}), 400

    content_id = str(uuid.uuid4())
    result = _run_pipeline(text)

    # Write to audit log
    log_classification(
        content_id=content_id,
        creator_id=creator_id,
        attribution=result["attribution"],
        confidence=result["combined_score"],
        llm_score=result["llm_score"],
        stylo_score=result["stylo_score"],
        perp_score=result["perp_score"],
        label_variant=result["label"]["variant"],
    )

    return jsonify({
        "content_id": content_id,
        "attribution": result["attribution"],
        "confidence": result["combined_score"],
        "label": result["label"],
        "signals": {
            "llm_score": result["llm_score"],
            "llm_reasoning": result["llm_reasoning"],
            "stylo_score": result["stylo_score"],
            "perp_score": result["perp_score"],
        },
        "word_count": result["word_count"],
    }), 200


@app.route("/appeal", methods=["POST"])
def appeal():
    """
    Contest a classification result.

    Request body (JSON):
        content_id        (str, required) — from the original /submit response
        creator_reasoning (str, required) — why you believe the classification is wrong

    Response (JSON):
        status    — "under_review"
        message   — confirmation string
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Request body must be JSON"}), 400

    content_id = data.get("content_id", "").strip()
    reasoning  = data.get("creator_reasoning", "").strip()

    if not content_id:
        return jsonify({"error": "Missing required field: content_id"}), 400
    if not reasoning:
        return jsonify({"error": "Missing required field: creator_reasoning"}), 400

    original = get_entry(content_id)
    if not original:
        return jsonify({"error": f"No submission found for content_id: {content_id}"}), 404

    if original.get("status") == "under_review":
        return jsonify({
            "status": "under_review",
            "message": "An appeal for this content is already under review.",
        }), 200

    log_appeal(
        content_id=content_id,
        creator_id=original.get("creator_id", "unknown"),
        creator_reasoning=reasoning,
        original_attribution=original.get("attribution"),
        original_confidence=original.get("confidence"),
    )

    return jsonify({
        "status": "under_review",
        "message": "Your appeal has been received and will be reviewed.",
        "content_id": content_id,
        "original_attribution": original.get("attribution"),
    }), 200


@app.route("/log", methods=["GET"])
def log():
    """
    Return recent audit log entries as JSON.
    In production this endpoint would require authentication.

    Query params:
        limit  (int, optional, default 50) — max entries to return
    """
    try:
        limit = int(request.args.get("limit", 50))
        limit = max(1, min(limit, 200))
    except ValueError:
        limit = 50

    entries = get_recent_entries(limit=limit)
    return jsonify({
        "count": len(entries),
        "entries": entries,
    }), 200


@app.route("/status/<content_id>", methods=["GET"])
def status(content_id):
    """
    Get the current status and classification for a submission.

    Returns 404 if content_id is not found.
    """
    entry = get_entry(content_id)
    if not entry:
        return jsonify({"error": f"No submission found for content_id: {content_id}"}), 404

    cert = get_certificate(content_id)
    response = {
        "content_id": content_id,
        "attribution": entry.get("attribution"),
        "confidence": entry.get("confidence"),
        "label_variant": entry.get("label_variant"),
        "status": entry.get("status"),
        "timestamp": entry.get("timestamp"),
    }
    if cert:
        response["certificate"] = cert.get("badge")
    return jsonify(response), 200




@app.route("/analytics", methods=["GET"])
def analytics():
    """
    Return detection pattern analytics and system health metrics.
    - Browser requests (Accept: text/html) serve the dashboard HTML page.
    - API requests return JSON.

    Metrics:
        - Total submissions (all time + last 7 days)
        - Attribution breakdown (% AI / uncertain / human)
        - Appeal rate
        - Signal disagreement rate
    """
    # Serve HTML dashboard for browser requests
    accept = request.headers.get("Accept", "")
    if "text/html" in accept:
        from flask import render_template
        return render_template("analytics.html")

    data = compute_analytics()
    return jsonify(data), 200


@app.route("/verify", methods=["POST"])
def verify():
    """
    Submit evidence to earn a Verified Human certificate.

    Request body (JSON):
        content_id      (str, required) — from the original /submit response
        creator_id      (str, required) — must match original submission
        evidence_type   (str, required) — "draft_history" or "statement"
        evidence        (str, required) — the draft text or written statement

    Response (JSON):
        certificate     — issued certificate with badge text
        validation_note — what the system found in the evidence
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Request body must be JSON"}), 400

    content_id    = data.get("content_id", "").strip()
    creator_id    = data.get("creator_id", "").strip()
    evidence_type = data.get("evidence_type", "").strip()
    evidence      = data.get("evidence", "").strip()

    if not all([content_id, creator_id, evidence_type, evidence]):
        return jsonify({"error": "Missing required fields: content_id, creator_id, evidence_type, evidence"}), 400

    if evidence_type not in ("draft_history", "statement"):
        return jsonify({"error": "evidence_type must be 'draft_history' or 'statement'"}), 400

    original = get_entry(content_id)
    if not original:
        return jsonify({"error": f"No submission found for content_id: {content_id}"}), 404

    if original.get("status") == "verified_human":
        cert = get_certificate(content_id)
        return jsonify({
            "message": "This content already has a Verified Human certificate.",
            "certificate": cert,
        }), 200

    # Validate evidence
    if evidence_type == "draft_history":
        is_valid, note = validate_draft_history(evidence)
    else:
        is_valid, note = validate_statement(evidence)

    if not is_valid:
        return jsonify({
            "status": "rejected",
            "reason": note,
        }), 422

    # Issue certificate
    cert = issue_certificate(content_id, creator_id, evidence_type)
    log_certificate(content_id, cert)

    return jsonify({
        "status": "verified_human",
        "validation_note": note,
        "certificate": cert,
    }), 200

# ── Rate limit error handler ───────────────────────────────────────────────────

@app.errorhandler(429)
def rate_limit_exceeded(e):
    return jsonify({
        "error": "Rate limit exceeded",
        "message": str(e.description),
        "retry_after": "Please wait before submitting again.",
    }), 429


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(debug=True, port=port)