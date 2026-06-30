"""
audit.py — Structured JSON audit log for Provenance Guard.
All attribution decisions and appeals are written here.
"""

import json
import os
from datetime import datetime, timezone

LOG_FILE = os.environ.get("AUDIT_LOG_FILE", "audit_log.json")


def _read_log() -> list:
    if not os.path.exists(LOG_FILE):
        return []
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []


def _write_log(entries: list) -> None:
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)


def log_classification(
    content_id: str,
    creator_id: str,
    attribution: str,
    confidence: float,
    llm_score: float,
    stylo_score: float,
    perp_score: float | None,
    label_variant: str,
) -> None:
    """Write a new classification entry to the audit log."""
    entries = _read_log()
    entry = {
        "entry_type": "classification",
        "content_id": content_id,
        "creator_id": creator_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "attribution": attribution,
        "confidence": round(confidence, 4),
        "llm_score": round(llm_score, 4),
        "stylo_score": round(stylo_score, 4),
        "perp_score": round(perp_score, 4) if perp_score is not None else None,
        "label_variant": label_variant,
        "status": "classified",
    }
    entries.append(entry)
    _write_log(entries)


def log_appeal(
    content_id: str,
    creator_id: str,
    creator_reasoning: str,
    original_attribution: str,
    original_confidence: float,
) -> None:
    """Append an appeal entry and update the original classification status."""
    entries = _read_log()

    # Update the original classification entry status
    for entry in entries:
        if entry.get("content_id") == content_id and entry.get("entry_type") == "classification":
            entry["status"] = "under_review"
            break

    # Append the appeal entry
    appeal_entry = {
        "entry_type": "appeal",
        "content_id": content_id,
        "creator_id": creator_id,
        "appeal_timestamp": datetime.now(timezone.utc).isoformat(),
        "creator_reasoning": creator_reasoning,
        "original_attribution": original_attribution,
        "original_confidence": round(original_confidence, 4),
        "status": "under_review",
    }
    entries.append(appeal_entry)
    _write_log(entries)


def get_entry(content_id: str) -> dict | None:
    """Return the most recent classification entry for a content_id, or None."""
    entries = _read_log()
    matches = [
        e for e in entries
        if e.get("content_id") == content_id and e.get("entry_type") == "classification"
    ]
    return matches[-1] if matches else None


def get_recent_entries(limit: int = 50) -> list:
    """Return the most recent log entries, newest first."""
    entries = _read_log()
    return list(reversed(entries[-limit:]))