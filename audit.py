
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
from audit import log_classification, log_appeal, get_entry, get_recent_entries
 
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
 