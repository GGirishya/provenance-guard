"""
certificate.py — Provenance certificate logic for Provenance Guard.

A creator earns a "Verified Human" certificate by submitting either:
  1. A plain text file containing 3+ meaningfully different draft versions
  2. A written statement explaining their authorship

The system validates the evidence, issues a certificate, and updates
the content's audit log entry with verified_human status.
"""

import re
import hashlib
from datetime import datetime, timezone


# ── Draft file validation ──────────────────────────────────────────────────────

def _split_drafts(text: str) -> list[str]:
    """
    Split a draft history file into individual versions.
    Looks for common draft separators:
      - "Draft 1:", "Version 2:", "v1:", "--- Draft 3 ---", blank lines (3+)
    """
    # Try explicit section headers first
    pattern = r'(?i)(?:^|\n)(?:draft\s*\d+|version\s*\d+|v\d+|revision\s*\d+)\s*[:\-–]'
    splits = re.split(pattern, text)
    splits = [s.strip() for s in splits if len(s.strip()) > 30]

    if len(splits) >= 3:
        return splits

    # Fall back: split on triple newlines
    splits = [s.strip() for s in re.split(r'\n{3,}', text) if len(s.strip()) > 30]
    return splits


def _meaningful_difference(a: str, b: str) -> bool:
    """
    Return True if two draft versions are meaningfully different.
    Uses word-level Jaccard similarity — drafts must be < 85% similar.
    """
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a or not words_b:
        return False
    intersection = words_a & words_b
    union = words_a | words_b
    similarity = len(intersection) / len(union)
    return similarity < 0.85  # More than 15% different = meaningful


def validate_draft_history(file_text: str) -> tuple[bool, str]:
    """
    Validate a draft history file.

    Returns:
        (is_valid: bool, reason: str)
    """
    if not file_text or len(file_text.strip()) < 50:
        return False, "Draft history file is too short to validate."

    drafts = _split_drafts(file_text)

    if len(drafts) < 3:
        return False, (
            f"Found {len(drafts)} draft section(s) — at least 3 are required. "
            "Separate drafts with headers like 'Draft 1:', 'Version 2:', or three blank lines."
        )

    # Check that at least 2 consecutive pairs are meaningfully different
    meaningful_pairs = 0
    for i in range(len(drafts) - 1):
        if _meaningful_difference(drafts[i], drafts[i + 1]):
            meaningful_pairs += 1

    if meaningful_pairs < 2:
        return False, (
            "The draft versions provided are too similar to each other. "
            "Please include drafts that show meaningful revision between versions."
        )

    return True, f"Draft history validated: {len(drafts)} versions with {meaningful_pairs} meaningful revisions detected."


# ── Statement validation ───────────────────────────────────────────────────────

def validate_statement(statement: str) -> tuple[bool, str]:
    """
    Validate a written authorship statement.
    Minimum bar: at least 50 words, not a one-liner.
    """
    words = statement.strip().split()
    if len(words) < 50:
        return False, (
            f"Authorship statement is too brief ({len(words)} words). "
            "Please provide at least 50 words describing your creative process, "
            "inspiration, or context that demonstrates human authorship."
        )
    return True, "Authorship statement received and logged."


# ── Certificate issuance ───────────────────────────────────────────────────────

def issue_certificate(content_id: str, creator_id: str, evidence_type: str) -> dict:
    """
    Issue a Verified Human certificate.

    Returns a certificate dict to be stored in the audit log and
    returned in API responses.
    """
    # Generate a short certificate ID from content_id + creator_id
    raw = f"{content_id}:{creator_id}:{evidence_type}"
    cert_id = "CERT-" + hashlib.sha256(raw.encode()).hexdigest()[:12].upper()

    return {
        "certificate_id": cert_id,
        "content_id": content_id,
        "creator_id": creator_id,
        "evidence_type": evidence_type,  # "draft_history" | "statement"
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "status": "verified_human",
        "badge": {
            "variant": "verified_human",
            "text": (
                "🏅 Verified Human-Written\n\n"
                "This creator submitted evidence of human authorship that was "
                "reviewed by our system. The original content label remains "
                "for transparency, but this badge indicates the creator has "
                "provided supporting documentation."
            ),
        },
    }