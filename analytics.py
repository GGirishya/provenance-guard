"""
analytics.py — Analytics helpers for Provenance Guard.

Computes detection patterns, appeal rates, and signal disagreement rate
from the audit log. Used by the GET /analytics endpoint.
"""

from audit import _read_log
from datetime import datetime, timezone, timedelta


def compute_analytics() -> dict:
    """
    Compute analytics metrics from the audit log.

    Metrics:
        - Total submissions (all time + last 7 days)
        - Attribution breakdown (% likely_ai / uncertain / likely_human)
        - Appeal rate (appeals filed / total submissions)
        - Signal disagreement rate (% where |llm_score - stylo_score| > 0.3)
    """
    entries = _read_log()

    classifications = [e for e in entries if e.get("entry_type") == "classification"]
    appeals = [e for e in entries if e.get("entry_type") == "appeal"]

    total = len(classifications)
    total_appeals = len(appeals)

    # Last 7 days
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    recent = [
        e for e in classifications
        if datetime.fromisoformat(e["timestamp"]) >= cutoff
    ]

    # Attribution breakdown
    counts = {"likely_ai": 0, "uncertain": 0, "likely_human": 0}
    for e in classifications:
        attr = e.get("attribution", "uncertain")
        counts[attr] = counts.get(attr, 0) + 1

    def pct(n):
        return round((n / total * 100), 1) if total > 0 else 0.0

    attribution_breakdown = {
        "likely_ai":     {"count": counts["likely_ai"],     "pct": pct(counts["likely_ai"])},
        "uncertain":     {"count": counts["uncertain"],     "pct": pct(counts["uncertain"])},
        "likely_human":  {"count": counts["likely_human"],  "pct": pct(counts["likely_human"])},
    }

    # Appeal rate
    appeal_rate = round((total_appeals / total * 100), 1) if total > 0 else 0.0

    # Signal disagreement rate: |llm_score - stylo_score| > 0.3
    disagreements = [
        e for e in classifications
        if abs(e.get("llm_score", 0) - e.get("stylo_score", 0)) > 0.3
    ]
    disagreement_rate = round((len(disagreements) / total * 100), 1) if total > 0 else 0.0

    # Average confidence by attribution
    def avg_confidence(attr):
        subset = [e["confidence"] for e in classifications if e.get("attribution") == attr]
        return round(sum(subset) / len(subset), 4) if subset else None

    return {
        "total_submissions": total,
        "submissions_last_7_days": len(recent),
        "total_appeals": total_appeals,
        "appeal_rate_pct": appeal_rate,
        "attribution_breakdown": attribution_breakdown,
        "signal_disagreement_rate_pct": disagreement_rate,
        "avg_confidence": {
            "likely_ai":    avg_confidence("likely_ai"),
            "uncertain":    avg_confidence("uncertain"),
            "likely_human": avg_confidence("likely_human"),
        },
    }