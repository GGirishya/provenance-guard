# Provenance Guard

A backend attribution system for creative content platforms.
 Provenance Guard classifies submitted text as likely AI-generated, likely human-written, or uncertain.
 This is done through returning a confidence score and a plain-language transparency label that platforms can surface directly to readers. Creators can appeal misclassifications and earn a Verified Human certificate by submitting authorship evidence.

Built for creative content platforms.

---

## Architecture Overview

A submitted piece of text takes the following path through the system:

```
POST /submit {text, creator_id}
    │
    ▼
[Rate Limiter] — 10/min, 100/day per IP
    │
    ▼
[Detection Pipeline]
    ├── Signal 1: Groq LLM (llama-3.3-70b-versatile) → llm_score (0–1)
    ├── Signal 2: Stylometric heuristics              → stylo_score (0–1)
    └── Signal 3: Perplexity proxy                   → perp_score (0–1)
    │
    ▼
[Confidence Scorer] — length-aware weighting + bias correction → combined_score
    │
    ▼
[Label Generator] — maps score to one of three transparency label variants
    │
    ▼
[Audit Log] — writes structured JSON entry
    │
    ▼
JSON response: {content_id, attribution, confidence, label, signals}
```

**Appeal flow:** `POST /appeal {content_id, creator_reasoning}` → lookup original entry → update status to `under_review` → append appeal entry to audit log → return confirmation.

**Certificate flow:** `POST /verify {content_id, creator_id, evidence_type, evidence}` → validate draft history or written statement → issue certificate → update audit log entry to `verified_human` → badge appears in `GET /status/<content_id>`.

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| POST | `/submit` | Submit content for attribution analysis |
| POST | `/appeal` | Contest a classification |
| POST | `/verify` | Submit evidence for a Verified Human certificate |
| GET | `/log` | View recent audit log entries |
| GET | `/status/<content_id>` | Get current status and certificate for a submission |
| GET | `/analytics` | Detection patterns dashboard |

---

## Detection Signals

### Signal 1 — LLM Classification (Groq)

**Model:** `llama-3.3-70b-versatile`

**What it measures:** Holistic semantic and stylistic coherence. The model evaluates whether the writing reads as AI-generated — capturing over-hedging language, unnaturally balanced sentence rhythm, suspiciously smooth transitions, and the kind of comprehensive-but-shallow coverage that characterizes prompt-following outputs.

**Output:** Float 0.0–1.0. Higher = more likely AI-generated.

**What it misses:** AI text deliberately prompted to sound casual will fool it. Highly formal human writing (legal documents, academic papers) may score unexpectedly high because it superficially resembles AI output.

---

### Signal 2 — Stylometric Heuristics (Pure Python)

**What it measures:** Statistical structural properties that differ between human and AI writing. Four sub-metrics are computed and weighted:

| Sub-metric | Weight | AI tendency |
|---|---|---|
| Sentence length variance | 35% | Low variance (uniform sentences) |
| Type-token ratio | 30% | Mid-range vocabulary diversity |
| Punctuation density | 20% | Low density (clean, smooth prose) |
| Average word length | 15% | Moderate, consistent word length |

**Output:** Float 0.0–1.0. Higher = more AI-like structure. Scores on texts under 50 words are blended toward 0.5 to reflect reduced statistical reliability.

**What it misses:** Very short texts (< 50 words) don't provide enough data for reliable statistics. Non-native English speakers writing carefully may score as AI-like due to limited vocabulary range and uniform sentence structure.

---

### Signal 3 — Perplexity Proxy (Stretch — Ensemble)

**What it measures:** Lexical predictability. AI models tend to choose high-probability (common) words. This signal estimates how "surprising" the word choices are using a word frequency list — no external model required.

**Output:** Float 0.0–1.0. Higher = more predictable word choices = more AI-like.

**What it misses:** Technical or creative human writing with specialized vocabulary will appear "surprising" even if AI-generated, because the frequency list is general-purpose. This signal is weakest on casual text where both human and AI use common words.

---

## Confidence Scoring

### Combining signals

Signals are combined using **length-aware weighting** — stylometrics and the perplexity proxy become more statistically reliable on longer text, so their weights increase with word count:

| Word count | LLM weight | Stylo weight | Perp weight |
|---|---|---|---|
| < 100 words | 70% | 15% | 15% |
| 100–200 words | 55% | 25% | 20% |
| > 200 words | 40% | 35% | 25% |

After computing the weighted average, a **bias correction** nudges borderline scores (0.45–0.60) slightly toward "human." This reflects the design decision that false positives — labeling a human's work as AI — are worse than false negatives on a creative writing platform.

### Threshold mapping

| Combined score | Attribution | Label variant |
|---|---|---|
| ≥ 0.75 | `likely_ai` | High-confidence AI |
| 0.45 – 0.74 | `uncertain` | Uncertain |
| < 0.45 | `likely_human` | High-confidence human |

The lower boundary of "uncertain" is 0.45, not 0.50, to require more evidence before issuing an AI label.

### Example submissions with different confidence scores

**High-confidence human (combined: 0.21):**
```
Input: "ok so i finally tried that new ramen place downtown and honestly?
underwhelming. the broth was fine but they put WAY too much sodium in it..."

llm_score: 0.2  |  stylo_score: 0.38  |  perp_score: 0.09
combined: 0.2102  →  likely_human
```

**Uncertain — formal human writing (combined: 0.53):**
```
Input: "The relationship between monetary policy and asset price inflation
has been extensively studied in the literature. Central banks face a
fundamental tension between their mandate for price stability..."

llm_score: 0.7  |  stylo_score: 0.47  |  perp_score: 0.0
combined: 0.534  →  uncertain
```

The formal human writing example illustrates the false-positive asymmetry at work: the LLM scored it 0.7 (high), but the stylometric and perplexity signals pulled the combined score into the uncertain band rather than issuing a high-confidence AI label. That is the intended behavior.

---

## Transparency Label

All three variants are returned as the `label.text` field in `/submit` responses. `{score}` is replaced with a human-readable percentage.

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

---

## Rate Limiting

Rate limiting is applied to `POST /submit` using Flask-Limiter with in-memory storage.

**Limits:** `10 per minute` and `100 per day` per IP address.

**Reasoning:**
- A typical creator submits their own work infrequently — a few pieces per session at most. 10 per minute is generous for legitimate use.
- 100 per day prevents automated flooding while accommodating a heavy user or a platform doing batch ingestion in a controlled way.
- A script trying to flood the endpoint to probe detection thresholds would hit the per-minute limit within seconds and receive 429 responses.

**Rate limit test output** (12 rapid requests — first 10 return 200, requests 11–12 return 429):
```
200
200
200
200
200
200
200
200
200
200
429
429
```

---

## Appeals Workflow

Creators can contest a classification by POSTing to `/appeal` with their `content_id` and reasoning:

```bash
curl -s -X POST http://localhost:5001/appeal \
  -H "Content-Type: application/json" \
  -d '{
    "content_id": "<content_id>",
    "creator_reasoning": "I am a non-native English speaker and write formally."
  }'
```

On receipt the system: updates the submission status to `under_review`, appends an appeal entry to the audit log alongside the original classification, and returns a confirmation. No automated re-classification occurs — a human reviewer sees both the original decision and the creator's reasoning via `GET /log`.

---

## Provenance Certificate 

Creators can earn a **Verified Human** badge by submitting authorship evidence via `POST /verify`.

**Evidence types accepted:**
- `draft_history` — a plain text file containing at least 3 meaningfully different draft versions (separated by headers like `Draft 1:` or triple blank lines). The system validates that consecutive versions differ by more than 15% using word-level Jaccard similarity.
- `statement` — a written explanation of at least 50 words describing the creator's process or context.

**On successful verification:**
- Content status updates to `verified_human` in the audit log
- A certificate is issued with a unique `CERT-` ID and timestamp
- `GET /status/<content_id>` includes a `certificate` field with the badge text

**Certificate badge text:**
```
🏅 Verified Human-Written

This creator submitted evidence of human authorship that was reviewed by
our system. The original content label remains for transparency, but this
badge indicates the creator has provided supporting documentation.
```

The original transparency label is preserved alongside the badge — the certificate supplements the label rather than replacing it, maintaining transparency for readers.

---

## Analytics Dashboard 

Available at `GET /analytics` — serves an HTML dashboard in the browser, JSON for API requests.

**Metrics tracked:**
- Total submissions (all time + last 7 days)
- Total appeals and appeal rate (%)
- Verified certificates issued and certificate rate (%)
- Attribution breakdown — % likely AI / uncertain / likely human
- Signal disagreement rate — % of submissions where `|llm_score - stylo_score| > 0.3` (a proxy for genuine uncertainty vs. signal agreement)
- Average confidence score by attribution category

---

## Audit Log

Every attribution decision, appeal, and certificate is written to `audit_log.json` as a structured entry. The log is queryable via `GET /log`.

**Classification entry format:**
```json
{
  "entry_type": "classification",
  "content_id": "3f7a2b1e-...",
  "creator_id": "test-user-1",
  "timestamp": "2026-06-30T14:32:10.123Z",
  "attribution": "likely_human",
  "confidence": 0.2102,
  "llm_score": 0.2,
  "stylo_score": 0.3769,
  "perp_score": 0.0909,
  "label_variant": "high_confidence_human",
  "status": "classified"
}
```

**Appeal entry format:**
```json
{
  "entry_type": "appeal",
  "content_id": "3f7a2b1e-...",
  "creator_id": "test-user-1",
  "appeal_timestamp": "2026-06-30T15:10:22.456Z",
  "creator_reasoning": "I am a non-native English speaker and write formally.",
  "original_attribution": "likely_human",
  "original_confidence": 0.2102,
  "status": "under_review"
}
```

**Certificate entry format:**
```json
{
  "entry_type": "certificate",
  "content_id": "198e9fd9-...",
  "certificate_id": "CERT-2A509BB44351",
  "creator_id": "test-user-1",
  "evidence_type": "statement",
  "issued_at": "2026-06-30T21:01:53.023779+00:00",
  "status": "verified_human"
}
```

---

## Known Limitations

**Non-native English speakers writing carefully** will likely be misclassified or land in the uncertain band. Careful, formal writing from a non-native speaker exhibits limited vocabulary range and uniform sentence structure — the same structural profile that stylometrics associates with AI. The bias correction and uncertain band exist partly to handle this, but the system cannot distinguish "careful non-native writing" from "AI output" using structural signals alone. The appeal and certificate pathways are the designed response.

**Very short texts (< 50 words)** produce unreliable stylometric scores. A haiku or short caption doesn't provide enough tokens for sentence variance or TTR to be statistically meaningful. The system blends short-text stylometric scores toward 0.5 and weights the LLM signal heavily, but confidence is genuinely lower on short texts and the label should reflect that — a future improvement would be to surface a "low confidence due to text length" note explicitly in the label.

---

## Spec Reflection

**One way the spec helped:** Writing out the three label variants in `planning.md` before building forced a concrete decision about what the uncertain band actually means. The insight that 0.5 is the *definition* of uncertain — not a soft AI label — came directly from writing the label text first and realizing "Authorship Uncertain" implied a different threshold than 0.5. That shifted the lower boundary of uncertain to 0.45.

**One way implementation diverged:** The planning doc specified that stylometrics would use four sub-metrics averaged equally. During implementation it became clear that sentence length variance and type-token ratio are substantially more reliable than average word length, which is easily confounded by domain-specific vocabulary. The final implementation uses weighted sub-metric combination (35/30/20/15) rather than equal weighting. The overall signal behavior is the same, but the weighting produces more stable scores on technical and creative text.

---

## AI Usage

**Instance 1 — Flask app skeleton and signal functions:** I provided the Detection Signals section and architecture diagram from `planning.md` and asked for the Flask app skeleton, `signal_llm.py`, `signal_stylo.py`, and `confidence.py`. The generated `signal_llm.py` initially returned the raw Groq response without stripping markdown code fences, which caused JSON parse errors on some responses. I added the fence-stripping logic and a fallback neutral score on parse failure. The stylometric sub-metric normalization ranges were also adjusted — the generated ranges were too narrow and caused most texts to cluster near 0.5.

**Instance 2 — Appeals workflow and label generation:** I provided the Transparency Label Design and Appeals Workflow sections and asked for the label generation function and `POST /appeal` route. The generated label function used a hard flip at 0.5 rather than the 0.45/0.75 thresholds specified in the planning doc. I corrected the thresholds to match the spec and updated the human-facing score display to invert the percentage for the human label variant (showing "69% human" rather than "31% AI").

---

## Setup

```bash
git clone <your-repo-url>
cd provenance-guard
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file in the repo root:
```
GROQ_API_KEY=your_key_here
```

Run the server:
```bash
python app.py
```

The API runs at `http://localhost:5001`. The analytics dashboard is at `http://localhost:5001/analytics`.

---

## Requirements

```
flask>=3.0.0
flask-limiter>=3.5.0
groq==0.15.0
python-dotenv==1.0.1
```
