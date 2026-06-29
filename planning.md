# Provenance Guard — planning.md

> Written before implementation. Updated before any stretch features.

---

## Table of Contents

1. [Architecture](#architecture)
2. [Detection Signals](#detection-signals)
3. [Uncertainty Representation](#uncertainty-representation)
4. [Transparency Label Design](#transparency-label-design)
5. [Appeals Workflow](#appeals-workflow)
6. [Anticipated Edge Cases](#anticipated-edge-cases)
7. [AI Tool Plan](#ai-tool-plan)
8. [Stretch Features](#stretch-features)

---

## Architecture

### Diagram

```
SUBMISSION FLOW
===============
POST /submit  {text, creator_id}
    │
    ▼
[Rate Limiter]  ──(429 Too Many Requests)──► error response
    │
    ▼
┌──────────────────────────────────────────────────────┐
│                  Detection Pipeline                  │
│                                                      │
│  [Signal 1: Groq LLM] ──────────► llm_score (0–1)   │
│  [Signal 2: Stylometrics] ──────► stylo_score (0–1)  │
│  [Signal 3: Perplexity proxy] ──► perp_score (0–1)   │
│                   (stretch — ensemble)               │
└──────────────────────────────────────────────────────┘
    │  llm_score, stylo_score, [perp_score]
    ▼
[Confidence Scorer]
  • length-aware weighting
  • weighted average → combined_score
  • bias correction (shift borderline scores toward human)
    │  combined_score (0–1)
    ▼
[Label Generator]
  • score ≥ 0.75  → HIGH-CONFIDENCE AI label
  • score 0.45–0.74 → UNCERTAIN label
  • score < 0.45  → HIGH-CONFIDENCE HUMAN label
    │  label_text, attribution, confidence
    ▼
[Audit Log]  ◄── writes structured JSON entry:
  {content_id, creator_id, timestamp, llm_score,
   stylo_score, combined_score, attribution,
   label_variant, status="classified"}
    │
    ▼
JSON response: {content_id, attribution, confidence, label}


APPEAL FLOW
===========
POST /appeal  {content_id, creator_reasoning}
    │
    ▼
[Lookup original entry by content_id]
    │
    ▼
[Update status → "under_review"]
    │
    ▼
[Audit Log]  ◄── appends appeal entry:
  {content_id, creator_reasoning, original_attribution,
   original_confidence, appeal_timestamp, status="under_review"}
    │
    ▼
JSON response: {status: "under_review", message: "Appeal received"}
```

### Narrative

**Submission flow:** When a creator POSTs to `/submit`, the request first passes through rate limiting. If allowed, the text is sent simultaneously to two (or three, with ensemble stretch) detection signals. Each signal returns an independent score between 0 and 1 representing estimated probability of AI authorship. The confidence scorer combines those scores using a length-aware weighted average, then applies a small bias correction that nudges borderline scores toward "human" to reduce false positives. The resulting combined score maps to one of three transparency label variants. The full decision — all individual scores, combined score, label, and status — is written to the audit log before returning the response.

**Appeal flow:** When a creator POSTs to `/appeal` with a content ID and their reasoning, the system retrieves the original log entry, updates the submission status to `"under_review"`, and appends the appeal (including the creator's reasoning and the original decision) to the audit log. No automated re-classification occurs — a human reviewer would see both the original classification and the appeal side by side.

---

## Detection Signals

### Signal 1 — LLM Classification (Groq)

**Model:** `llama-3.3-70b-versatile`

**What it measures:** Holistic semantic and stylistic coherence. The LLM evaluates whether the writing "reads" as AI-generated — capturing subtle patterns like over-hedging language ("it is important to note that"), unnaturally balanced sentence rhythm, suspiciously smooth transitions, and the kind of comprehensive-but-shallow coverage that characterizes prompt-following outputs.

**Prompt approach:** Send the text with a system prompt instructing the model to return a structured JSON object with a single field `ai_probability` (float 0.0–1.0) and a brief `reasoning` string. Parse the float directly as `llm_score`.

**Output:** Float 0.0–1.0. Higher = more likely AI-generated.

**What it misses:**
- AI text that has been deliberately prompted to sound casual or personal will fool it.
- Highly formal human writing (legal briefs, academic papers) may score unexpectedly high because it superficially resembles AI output.
- It reflects the LLM's own training biases — it may be better at detecting output from models similar to itself.

---

### Signal 2 — Stylometric Heuristics (Pure Python)

**What it measures:** Statistical structural properties that differ between human and AI writing. AI-generated text tends toward uniformity — consistent sentence lengths, moderate and predictable vocabulary, smooth punctuation patterns. Human writing is messier: sentences vary wildly in length, vocabulary is either very rich or colloquially narrow, and punctuation reflects personality.

**Sub-metrics computed:**

| Sub-metric | What it captures | AI tendency |
|---|---|---|
| Sentence length variance | How much sentence length fluctuates | Low variance (uniform) |
| Type-token ratio (TTR) | Vocabulary diversity: unique words / total words | Mid-range TTR (not too rich, not too poor) |
| Punctuation density | Punctuation marks per 100 words | Low density (clean, smooth) |
| Average word length | Mean characters per word | Moderate, consistent |

**Combining sub-metrics:** Each sub-metric is normalized to 0–1 based on empirically reasonable human/AI ranges, then averaged into a single `stylo_score`. Sub-metrics that indicate "more AI-like" contribute positively to the score.

**Output:** Float 0.0–1.0. Higher = more AI-like structural properties.

**What it misses:**
- Short texts (< ~100 words) don't provide enough data for reliable statistics — the score is noisy and less trustworthy.
- Simple, informal human writing (casual messages, non-native English speakers writing carefully) may score as AI-like because vocabulary is limited and sentences are short and uniform.
- A sophisticated attacker who knows these heuristics could deliberately introduce variance to fool them.

---

### Signal 3 — Perplexity Proxy (Stretch — Ensemble)

**What it measures:** Lexical predictability. AI language models tend to choose high-probability next words, producing text that is statistically "expected." This signal approximates that by computing a simple word-level entropy or n-gram frequency score using a lightweight word frequency list — no external model required.

**Approach:** Use a word frequency list (e.g., derived from common English corpora) to estimate how "surprising" each word choice is. Compute the mean log-probability of word choices across the text. Lower log-probability (more surprising choices) = more human-like.

**Output:** Float 0.0–1.0 normalized to AI-probability direction. Higher = more predictable word choices = more AI-like.

**What it misses:**
- Technical writing with specialized vocabulary will appear "surprising" even if AI-generated, because the frequency list is general-purpose.
- Creative human writing that deliberately uses common words simply will score as AI-like.

---

## Uncertainty Representation

### What a score of 0.6 means

A score of 0.6 means the signals lean toward AI authorship but without strong agreement or high individual signal confidence. It is not a reliable classification — it sits in a zone where the system genuinely cannot distinguish. The label must reflect this honestly: the user should see "uncertain," not a soft version of "AI-generated."

### Combining signals into a calibrated score

**Length-aware weighting:** Stylometrics become more statistically reliable as text length increases. LLM classification is reliable across all lengths but expensive and slower. Weight accordingly:

```
word_count = len(text.split())

if word_count < 100:
    weights = {"llm": 0.80, "stylo": 0.20}
elif word_count < 200:
    weights = {"llm": 0.65, "stylo": 0.35}
else:
    weights = {"llm": 0.50, "stylo": 0.50}

# With ensemble stretch (Signal 3 active):
if word_count < 100:
    weights = {"llm": 0.70, "stylo": 0.15, "perp": 0.15}
elif word_count < 200:
    weights = {"llm": 0.55, "stylo": 0.25, "perp": 0.20}
else:
    weights = {"llm": 0.40, "stylo": 0.35, "perp": 0.25}
```

**Bias correction:** After computing the weighted average, apply a small correction that nudges scores below 0.55 downward — reflecting the design decision that false positives (labeling a human's work as AI) are worse than false negatives. The correction is small (subtract up to 0.05 in the 0.45–0.55 band) and only applies near the boundary, not at the extremes.

### Threshold mapping

| Combined score | Label category | Reasoning |
|---|---|---|
| ≥ 0.75 | High-confidence AI | Both signals agree strongly; confident enough to label |
| 0.45 – 0.74 | Uncertain | Signals disagree, or neither is high-confidence |
| < 0.45 | High-confidence human | Both signals agree there are no strong AI indicators |

**Why not 0.5 as the boundary?** A score of exactly 0.5 means the signals are split — that is the definition of uncertain, not a soft AI classification. Shifting the lower boundary of "uncertain" to 0.45 (not 0.50) reflects the false-positive asymmetry: we require more evidence to call something AI-generated than to call it human-written.

---

## Transparency Label Design

The label is returned in the API response as a `label` field and is designed to be displayed directly to readers on the platform. It must be readable by a non-technical user and make the confidence level meaningful without requiring them to understand what a float score is.

### Variant 1 — High-Confidence AI (score ≥ 0.75)

```
⚠️ AI-Generated Content

Our system found strong indicators that this content was likely generated 
by AI (confidence: {score}%). This label reflects automated analysis and 
may not be fully accurate. If you are the creator and believe this is 
incorrect, you can submit an appeal.
```

### Variant 2 — Uncertain (score 0.45–0.74)

```
🔍 Authorship Uncertain

Our system could not confidently determine whether this content was written 
by a human or generated by AI (confidence: {score}%). It will be treated as 
unverified. Creators can submit an appeal to provide additional context.
```

### Variant 3 — High-Confidence Human (score < 0.45)

```
✅ Likely Human-Written

Our system found no strong indicators of AI generation in this content 
(confidence: {score}% human). This is an automated assessment, not a guarantee.
```

**Note on `{score}`:** The score is displayed as a human-readable percentage. For AI and uncertain variants, it represents the AI-probability percentage (e.g., a combined score of 0.82 → "82%"). For the human variant, it is inverted (e.g., a combined score of 0.31 → "69% human").

---

## Appeals Workflow

### Who can appeal

Any creator who submitted the content (matched by `creator_id` in the original submission). The `content_id` returned at submission time is required to file an appeal.

### What information they provide

- `content_id` (required): The ID returned when the content was submitted.
- `creator_reasoning` (required): A free-text explanation of why they believe the classification is incorrect. This is the primary signal for a human reviewer. Examples of useful reasoning: "I am a non-native English speaker and write formally," "This is a technical document in my field," "I can provide a draft history."

### What the system does on appeal receipt

1. Look up the original audit log entry by `content_id`. If not found, return 404.
2. Update the entry's `status` field from `"classified"` to `"under_review"`.
3. Append a new audit log entry of type `"appeal"` containing: `content_id`, `creator_id`, `creator_reasoning`, `appeal_timestamp`, `original_attribution`, `original_confidence`.
4. Return a confirmation response: `{"status": "under_review", "message": "Your appeal has been received and will be reviewed."}`

### What a human reviewer sees

When a reviewer queries `GET /log` or a future review queue endpoint, they see the original classification entry and the appeal entry linked by `content_id`. They can see: the original signals and scores, the attribution and confidence at the time of classification, and the creator's reasoning in full. Automated re-classification is not performed — the reviewer makes the final call.

### What the system does NOT do

- No automated re-classification on appeal.
- No notification system (out of scope).
- No authentication on the appeal endpoint (noted as a known limitation).

---

## Anticipated Edge Cases

### Edge case 1 — Non-native English speaker writing carefully

A non-native English speaker may write in a formal, grammatically careful style with limited vocabulary range and uniform sentence lengths — exactly the structural profile that stylometrics associates with AI. The LLM signal may also flag it if the writing lacks the idiomatic irregularities the model associates with native human writing.

**How the system handles it:** The uncertain band (0.45–0.74) exists precisely for this case. A score in this range produces the "Authorship Uncertain" label rather than a hard AI classification, and the label explicitly invites an appeal. The bias correction also nudges borderline scores away from the AI label. This is the designed response — not a perfect outcome, but an honest one.

### Edge case 2 — Lightly edited AI output

A user takes AI-generated text and manually edits 10–20% of it: changes a few word choices, adds a personal anecdote, breaks up a long sentence. The LLM signal may still detect it (the overall coherence and hedging patterns persist), but the stylometrics signal will score it as more human because variance was introduced. The signals will disagree.

**How the system handles it:** Disagreeing signals produce a score in the mid-range, landing in the uncertain band. This is the correct response — the system shouldn't confidently label something it genuinely can't resolve. The weighted scoring (LLM-dominant for short texts) means the LLM signal will pull the score upward even when stylometrics is fooled.

### Edge case 3 — Very short text (< 50 words)

A poem of three stanzas or a short caption doesn't provide enough tokens for stylometrics to be statistically meaningful, and may not provide enough context for the LLM to classify confidently.

**How the system handles it:** The length-aware weighting heavily favors the LLM signal for short texts (80% weight). If the LLM itself returns a low-confidence score, the combined result will fall in the uncertain band. A future improvement would be to flag short-text submissions explicitly and note the reduced reliability in the label.

---

## AI Tool Plan

### Milestone 3 — Submission endpoint + Signal 1

**Spec sections to provide:** Detection Signals (Signal 1 subsection) + Architecture diagram + API surface from README.

**What to ask the AI tool to generate:**
1. Flask app skeleton: `app.py` with `POST /submit` route stub that accepts `{text, creator_id}`, generates a `content_id` (UUID), and returns a hardcoded placeholder response.
2. `signal_llm.py`: a function `score_llm(text) -> float` that calls the Groq API with a structured prompt, parses the JSON response, and returns `ai_probability` as a float.

**How to verify before wiring in:**
- Call `score_llm()` directly on 3 inputs (clearly AI, clearly human, borderline) and confirm it returns a float between 0 and 1.
- Confirm the Flask route returns JSON with `content_id`, `attribution`, `confidence`, `label` fields before adding any real logic.
- Check that the Groq prompt actually returns parseable JSON (not markdown-wrapped).

---

### Milestone 4 — Signal 2 + Confidence Scoring

**Spec sections to provide:** Detection Signals (Signal 2 subsection) + Uncertainty Representation section + Architecture diagram.

**What to ask the AI tool to generate:**
1. `signal_stylo.py`: a function `score_stylometrics(text) -> float` that computes the four sub-metrics, normalizes each to 0–1, and returns their average.
2. `confidence.py`: a function `combine_scores(llm_score, stylo_score, word_count) -> float` that applies the length-aware weights from the spec and the bias correction.

**How to verify:**
- Run both signals on the four test inputs from the spec (clearly AI, clearly human, two borderline cases) and print scores side by side.
- Confirm clearly AI text scores ≥ 0.70 and clearly human text scores ≤ 0.40.
- If any test input produces a counterintuitive score, print sub-metric values separately to isolate which metric is misbehaving before moving on.

---

### Milestone 5 — Production layer

**Spec sections to provide:** Transparency Label Design section + Appeals Workflow section + Architecture diagram.

**What to ask the AI tool to generate:**
1. `labels.py`: a function `generate_label(combined_score) -> dict` that returns `{variant, text}` based on the three threshold ranges from the spec. Ask it to use the exact label text written in this document.
2. `POST /appeal` route: accepts `{content_id, creator_reasoning}`, updates status, appends to audit log, returns confirmation.
3. Flask-Limiter setup with `storage_uri="memory://"` applied to `/submit`.

**How to verify:**
- Submit inputs that produce all three score ranges and confirm all three label variants appear in responses.
- Submit an appeal with a known `content_id` and confirm `GET /log` shows `"status": "under_review"` and `appeal_reasoning` populated.
- Run the 12-request rate limit test from the spec and confirm requests 11–12 return 429.

---

## Stretch Features

> This section will be updated before implementing each stretch feature.

### S1 — Ensemble Detection (Signal 3: Perplexity Proxy)

**Status:** Planned — implement after M4 Signal 2 is verified.

**Approach:** See Signal 3 in Detection Signals section. Add `signal_perp.py` with `score_perplexity(text) -> float`. Update `combine_scores()` in `confidence.py` to accept an optional third signal and apply the three-signal weights from the Uncertainty Representation section.

**Verification:** The perplexity signal should agree with the LLM signal on the clear-AI test input and be lower (more surprising) on clearly human text.

---

### S2 — Provenance Certificate

**Status:** Planned — design after M5 is complete.

**Approach:** A creator can request a "Verified Human" badge through an additional verification step. Minimum viable version: the creator uploads a draft history artifact (e.g., a plain-text file showing iterative edits) via `POST /verify`. The system logs the verification attempt and, if the artifact contains meaningful revision history (at least 3 meaningfully different versions), marks the content as `"verified_human"` in the audit log. A `GET /status/<content_id>` response includes a `certificate` field that the platform can display.

**Display:** The label for verified content overrides the normal transparency label:
```
🏅 Verified Human-Written

This creator provided a draft history that was reviewed and verified.
```

---

### S3 — Analytics Dashboard

**Status:** Planned — build as a `GET /analytics` endpoint returning JSON, plus a simple HTML page.

**Metrics to track:**
- Total submissions (all time and last 7 days)
- Attribution breakdown: % high-confidence AI / uncertain / high-confidence human
- Appeal rate: appeals filed / total submissions
- One additional metric: **signal disagreement rate** — % of submissions where LLM and stylometrics scores differ by > 0.3 (a proxy for how often the system is genuinely uncertain vs. both signals agreeing).

---

### S4 — Multi-Modal Support

**Status:** Planned — design after S1–S3 are complete.

**Second content type:** Structured metadata — specifically, an image description submitted as a JSON object with fields like `caption`, `alt_text`, and `tags`. The same LLM signal can classify these, but stylometrics are replaced with a metadata-specific heuristic: tag density, description length, vocabulary overlap between caption and tags.

**Endpoint extension:** `/submit` will accept an optional `content_type` field (`"text"` or `"image_metadata"`). The pipeline routes to the appropriate signal combination based on this field.
