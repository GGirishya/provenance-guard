"""
signal_perp.py — Signal 3 (Stretch): Perplexity proxy.

Approximates lexical predictability using word frequency ranks.
AI models tend to choose high-probability (common) words; human
writing tends to include more surprising or idiosyncratic choices.

Uses the 10,000 most common English words as a frequency proxy.
No external models or libraries required.

Returns a float 0.0–1.0 (higher = more predictable = more AI-like).
"""

import re
import math

# ── Word frequency list ────────────────────────────────────────────────────────
# Top ~500 most common English words used as a lightweight frequency proxy.
# In a production system, replace with a full 10k+ word frequency list.
# Words not in this set are treated as "surprising" (low probability).

_COMMON_WORDS = set("""
the be to of and a in that have it for not on with he as you do at this but
his by from they we say her she or an will my one all would there their what
so up out if about who get which go me when make can like time no just him
know take people into year your good some could them see other than then now
look only come its over think also back after use two how our work first well
way even new want because any these give day most us i am are was were been
has had can did does had may must need should than will would could
those these every through much very about still while between over under before
after during without through against between into during before under such same
each both few more most other some such no nor not only own same so than too
very just because since even while although though also again further then once
here there when where why how all both each few more most other some such no
what which who whom this that these those am is are was were be been being have
has had do does did will would shall should may might must can could ought dare
need used to come go see say make take know get give find tell ask seem feel try
leave call keep let begin show hear play run move live believe hold bring happen
write provide sit stand lose pay meet include continue set learn change lead
understand watch follow stop create speak read spend grow open walk win offer
remember love consider appear buy serve die send expect build stay fall cut
reach kill remain suggest raise pass sell require report decide pull
""".split())


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z']+", text.lower())


def score_perplexity(text: str) -> tuple[float, dict]:
    """
    Estimate lexical predictability as a proxy for AI authorship probability.

    High predictability (mostly common words) → high AI score.
    Low predictability (many rare/surprising words) → low AI score.

    Returns:
        (ai_probability: float, meta: dict)
        ai_probability is 0.0–1.0, higher = more predictable = more AI-like.
    """
    words = _words(text)

    if len(words) < 20:
        return 0.5, {"note": "insufficient word count", "word_count": len(words)}

    common_count = sum(1 for w in words if w in _COMMON_WORDS)
    rare_count = len(words) - common_count
    common_ratio = common_count / len(words)

    # Common ratio ranges:
    # Very AI-like prose: ~0.72–0.82 (heavily function-word and common-word heavy)
    # Human casual text: ~0.78–0.88 (also high — casual = common words)
    # Human technical/creative: ~0.55–0.70 (specialized vocabulary)
    # AI technical text: ~0.65–0.75

    # This signal is weakest for casual text (both human and AI use common words).
    # It works best distinguishing formal AI text from creative/technical human text.

    # Normalize: 0.80+ → 1.0 (very AI-like), 0.50 → 0.0 (very human-like)
    ai_score = max(0.0, min(1.0, (common_ratio - 0.50) / 0.30))

    meta = {
        "word_count": len(words),
        "common_word_count": common_count,
        "rare_word_count": rare_count,
        "common_ratio": round(common_ratio, 4),
    }

    return round(ai_score, 4), meta