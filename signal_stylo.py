"""
signal_stylo.py — Signal 2: Stylometric heuristics.

Computes statistical structural properties of text that differ
between human and AI writing. AI text tends toward uniformity;
human writing is messier and more variable.

Returns a float 0.0–1.0 (higher = more AI-like structure).
"""

import re
import math


# ── Sub-metric helpers ─────────────────────────────────────────────────────────

def _sentences(text: str) -> list[str]:
    """Split text into sentences using punctuation boundaries."""
    raw = re.split(r'(?<=[.!?])\s+', text.strip())
    return [s for s in raw if len(s.split()) >= 2]


def _words(text: str) -> list[str]:
    """Extract lowercase alphabetic words."""
    return re.findall(r"[a-z']+", text.lower())


def sentence_length_variance(text: str) -> float:
    """
    Measure how much sentence length varies.
    Low variance = AI-like (uniform sentences).
    High variance = human-like (irregular rhythm).

    Returns 0.0–1.0 where 1.0 = most AI-like (low variance).
    """
    sents = _sentences(text)
    if len(sents) < 2:
        return 0.5  # Not enough data

    lengths = [len(s.split()) for s in sents]
    mean = sum(lengths) / len(lengths)
    variance = sum((l - mean) ** 2 for l in lengths) / len(lengths)
    std_dev = math.sqrt(variance)

    # Human writing typically has std_dev > 6 words
    # AI writing typically clusters around std_dev 3–5
    # Normalize: std_dev=0 → 1.0 (AI), std_dev=10+ → 0.0 (human)
    normalized = max(0.0, 1.0 - (std_dev / 10.0))
    return round(normalized, 4)


def type_token_ratio(text: str) -> float:
    """
    Vocabulary diversity: unique words / total words.
    Mid-range TTR is AI-like; very high (rich) or very low (casual) is human-like.

    Returns 0.0–1.0 where 1.0 = most AI-like.
    """
    words = _words(text)
    if len(words) < 10:
        return 0.5  # Not enough data

    ttr = len(set(words)) / len(words)

    # TTR naturally decreases with text length (longer text = more repetition)
    # AI text tends to cluster around 0.55–0.75 TTR
    # Human casual text is lower; human rich prose is higher
    # Most AI-like zone: 0.55–0.72
    # Score peaks at TTR=0.63 (center of AI zone) and drops toward extremes
    center = 0.63
    width = 0.15
    distance = abs(ttr - center)
    ai_score = max(0.0, 1.0 - (distance / width))
    return round(min(1.0, ai_score), 4)


def punctuation_density(text: str) -> float:
    """
    Punctuation marks per 100 words.
    AI text tends to be clean (low punctuation density).
    Human text has more dashes, ellipses, exclamations, etc.

    Returns 0.0–1.0 where 1.0 = most AI-like (low density).
    """
    words = _words(text)
    if not words:
        return 0.5

    punct_chars = re.findall(r'[^\w\s]', text)
    density = (len(punct_chars) / len(words)) * 100

    # Human writing typically has density > 15 per 100 words
    # AI writing tends toward 8–13 per 100 words
    # Normalize: density=5 → 1.0 (very AI-like), density=25+ → 0.0 (human-like)
    normalized = max(0.0, 1.0 - ((density - 5) / 20.0))
    return round(min(1.0, normalized), 4)


def average_word_length(text: str) -> float:
    """
    Mean characters per word.
    AI writing tends toward moderate, consistent word lengths (4.5–6.5 chars).
    Very short (casual) or very long (technical) avg word length = more human.

    Returns 0.0–1.0 where 1.0 = most AI-like.
    """
    words = _words(text)
    if not words:
        return 0.5

    avg = sum(len(w) for w in words) / len(words)

    # AI-like zone: 4.5–6.5 characters average
    # Score peaks at 5.5, drops toward extremes
    center = 5.5
    width = 1.5
    distance = abs(avg - center)
    ai_score = max(0.0, 1.0 - (distance / width))
    return round(min(1.0, ai_score), 4)


# ── Main scoring function ──────────────────────────────────────────────────────

def score_stylometrics(text: str) -> tuple[float, dict]:
    """
    Compute stylometric AI-probability score.

    Returns:
        (combined_score: float, sub_metrics: dict)
        combined_score is 0.0–1.0, higher = more AI-like structure.
        sub_metrics contains individual metric scores for the audit log.
    """
    word_count = len(_words(text))

    slv = sentence_length_variance(text)
    ttr = type_token_ratio(text)
    pd  = punctuation_density(text)
    awl = average_word_length(text)

    sub_metrics = {
        "sentence_length_variance": slv,
        "type_token_ratio": ttr,
        "punctuation_density": pd,
        "average_word_length": awl,
        "word_count": word_count,
    }

    # Weight sub-metrics — SLV and TTR are most reliable; AWL is weakest
    weights = {"slv": 0.35, "ttr": 0.30, "pd": 0.20, "awl": 0.15}
    combined = (
        slv * weights["slv"]
        + ttr * weights["ttr"]
        + pd  * weights["pd"]
        + awl * weights["awl"]
    )

    # Reduce confidence on very short texts
    if word_count < 50:
        # Blend toward neutral 0.5 proportionally
        blend_factor = word_count / 50
        combined = combined * blend_factor + 0.5 * (1 - blend_factor)

    return round(combined, 4), sub_metrics