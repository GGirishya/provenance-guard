
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