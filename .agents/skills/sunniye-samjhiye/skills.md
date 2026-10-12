# Sunniye, Samjhiye (सुनिए, समझिए) — Patient Intake Storyteller
## Agent Instructions & Skills (`skills.md`)

> Drop this file into your coding agent as its instructions/skills file. Goal: a working, demo-ready app in **30 minutes**.
> Stack: **Saaras** (speech), **Sarvam Vision / Document AI** (prescription OCR), **Sarvam-105B** (reasoning), Python FastAPI + a single static HTML page.

---

## 0. Mission

Build a web app used at OPD triage that:

1. **Records** a patient's spoken narrative in a regional Indian language (Hindi, Bengali, Tamil, Telugu, Marathi, etc., including code-mixed speech) and transcribes it with **Saaras**.
2. **Parses prior scrawled/handwritten prescriptions** (photo or PDF) with **Sarvam Vision** (Document AI).
3. Generates a **two-column clinical summary**:
   - **Left column — "Said / Written" (verbatim facts):** only facts that are provably present in the transcript or prescription text, each shown with the exact quote.
   - **Right column — "AI Hypotheses" (unverified):** inferences, possible conditions, red flags, suggested follow-up questions, data gaps. Always labelled as AI-generated.
4. **Links every verbatim fact to its source**: audio timestamp (click to play from that second) or prescription page/region.
5. Captures a **doctor sign-off artifact**: per-item review, attestation, timestamp, content hash, exported as JSON + printable page.

Name shown in the UI: **Sunniye, Samjhiye** (Hindi: सुनिए, समझिए). Tagline: "Listen first. Understand next."

### Definition of Done (must all be true)
- [ ] Record or upload audio → transcript appears with per-segment timestamps.
- [ ] Upload prescription image/PDF → extracted text appears beside the image.
- [ ] "Generate summary" → two columns render; every left-column item has a source chip (▶ mm:ss or 📄 page).
- [ ] Clicking a ▶ chip seeks the audio player to that time.
- [ ] Doctor can confirm / edit / reject each item, promote or dismiss hypotheses, then sign off.
- [ ] `data/cases/<case_id>/signoff.json` is written and the case locks.
- [ ] App runs with one command and the README has the exact steps.

---

## 1. Non-negotiable rules (read twice)

1. **Verbatim means verbatim.** Left-column facts must be a character-for-character substring of the transcript or OCR text (after Unicode NFC + whitespace normalisation). Code verifies this. Anything that fails verification is **demoted to the right column** with the note "unverified extraction". Never silently keep it on the left.
2. **Timestamps come from code, never from the LLM.** The LLM returns quotes only; the backend locates each quote in the transcript and maps it to audio time.
3. **No diagnosis stated as fact.** Hypotheses use hedged language ("possible", "consider"), carry a confidence label, cite the left-column fact IDs that support them, and are marked `needs_clinician_verification: true`.
4. **Never guess illegible handwriting.** If OCR text is unclear, show `[illegible]`. Do not invent drug names or doses. A drug name that is not literally in the OCR text may only appear in the right column as "possible reading".
5. **Doctor has the last word.** Nothing is "final" until sign-off. After sign-off the case is read-only (edits create a new version).
6. **Synthetic data only for the demo.** Show a banner: "Demo — do not enter real patient data." Audio/images are sent to Sarvam's cloud APIs. Never log API keys, audio bytes, or transcripts to stdout.
7. **This is a documentation aid, not a diagnostic device.** Put that sentence in the footer and in the signed artifact.
8. **Don't ask the user questions** except for `SARVAM_API_KEY` if missing. Make reasonable assumptions, list them in the final report.

---

## 2. Verified Sarvam API facts (checked against docs.sarvam.ai, Oct 2026)

| Item | Value |
|---|---|
| Base URL | `https://api.sarvam.ai` |
| Auth header | `api-subscription-key: <SARVAM_API_KEY>` |
| Docs index for agents | `https://docs.sarvam.ai/llms.txt` (full: `/llms-full.txt`) · MCP server: `https://docs.sarvam.ai/_mcp/server` |

### Saaras (speech-to-text)
- Endpoint: `POST /speech-to-text`, **`multipart/form-data`**.
- Model: `saaras:v3` (documented, stable). Docs now also list `saaras:v4` as the newest default — try `SARVAM_STT_MODEL=saaras:v4` after the happy path works; keep v3 as fallback.
- Fields: `file`, `model`, `mode`, `language_code`, `with_timestamps` (`"true"`), optional `input_audio_codec`, optional `keyterms` (list of strings, ≤64 chars each).
- `mode` values: `transcribe` (default, native script), `translate` (English text), `verbatim`, `translit` (Roman script), `codemix` (English words in English, Indic words in native script).
- `language_code`: BCP-47 like `hi-IN`, `bn-IN`, `ta-IN`, `te-IN`, `mr-IN`, `gu-IN`, `kn-IN`, `ml-IN`, `pa-IN`, `en-IN`; or `unknown` to auto-detect (response then includes a detected language code).
- **REST limit: 30 seconds per request.** Longer audio → either chunk client-side (this build) or use Batch API (≤2 h/file, diarization + segment timestamps; stretch goal).
- Response has `transcript`, `language_code`, and `timestamps` (only when `with_timestamps=true`; may be `null`). **Inspect the real response shape on the first call and normalise it** (see S3). Docs conflict on whether word-level timestamps are always returned on REST, so the code must degrade to chunk-level timestamps.

### Sarvam Vision / Document AI (prescription OCR)
- Sarvam Vision (3B VLM, 23 languages = 22 Indian + English). Document AI (powered by Sarvam Vision 1.5) **supersedes** the older "Document Digitization" API.
- Async **job** API: create job → (upload file if the response asks for it) → poll status → download results.
- Endpoints: `POST /doc-ai/v1/job/digitise` (full OCR; `output_format`: `md` | `html` | `json`) and `POST /doc-ai/v1/job/extract` (schema-based key-value extraction → structured JSON). Status: `GET /doc-ai/v1/job/<JOB_ID>/status`.
- Python SDK (`pip install sarvamai`): `client.doc_ai.digitise(...)`, `client.doc_ai.get_status(job_id=...)`, `client.doc_ai.get_download_url(job_id=...)`, `client.doc_ai.extract(...)`, `client.doc_ai.get_results(job_id=...)`.
- **Before coding S4, fetch** `https://docs.sarvam.ai/api/api-guides-tutorials/document-intelligence/overview.md` and follow its exact upload/start/poll/download sequence. Do not guess parameter names.

### Sarvam-105B (LLM)
- Endpoint: `POST /v1/chat/completions` (OpenAI-compatible), model id `sarvam-105b` (128K context). Fallback model: `sarvam-30b` (64K context, faster).
- Standard `messages`, `temperature`, `max_tokens`, `stream`, tools supported. It is a reasoning-style model: **allow generous `max_tokens` (4096+)** and strip any `<think>…</think>` block before parsing JSON.
- Do not assume a JSON-mode flag exists. Prompt for JSON, then parse defensively (S5).

---

## 3. Architecture & file layout

```
sunniye-samjhiye/
├── README.md
├── requirements.txt          # fastapi uvicorn[standard] python-multipart requests sarvamai
├── .env.example              # SARVAM_API_KEY=...
├── app/
│   ├── main.py               # FastAPI routes + static mount
│   ├── sarvam.py             # thin clients: stt_chunk(), chat(), docai_digitise() + response cache
│   ├── audio.py              # ffmpeg convert + chunk
│   ├── provenance.py         # canon(), find_span(), time mapping
│   ├── summarize.py          # prompts, JSON parsing, verification, demotion
│   ├── signoff.py            # hashing, lock, export
│   └── store.py              # JSON-on-disk persistence
├── static/
│   └── index.html            # single-page UI (vanilla JS, no build step)
└── data/
    ├── cases/<case_id>/{audio.wav, chunks/, transcript.json, rx/, rx_text.json, summary.json, review.json, signoff.json}
    └── cache/                # cached Sarvam responses keyed by input hash (offline demo replay)
```

Pipeline:

```
mic/upload ─▶ ffmpeg (16 kHz mono WAV, 25 s chunks) ─▶ Saaras (parallel, per chunk, with_timestamps)
                                                           │
prescription image/PDF ─▶ Sarvam Vision (Document AI) ─────┤
                                                           ▼
                         canonical sources: transcript segments + rx text
                                                           ▼
                         Sarvam-105B ─▶ JSON {verbatim_facts[], ai_hypotheses[]}
                                                           ▼
                         verify quotes (substring) ─▶ demote failures ─▶ compute timestamps
                                                           ▼
                         two-column UI ─▶ doctor review ─▶ sign-off.json (SHA-256) ─▶ lock
```

### Data model (store as JSON)

```jsonc
// transcript.json
{
  "language_code": "hi-IN",
  "segments": [
    {"idx": 0, "offset_s": 0.0, "end_s": 24.8, "text": "…", "words": [{"w":"…","start":0.2,"end":0.6}] /* or null */}
  ],
  "full_text": "…segments joined with \n, NFC-normalised…"
}

// summary.json
{
  "verbatim_facts": [{
    "id":"F1","category":"chief_complaint|symptom|duration|history|medication|allergy|vitals_reported|other",
    "label":"short English label","quote":"exact substring","english_gloss":"AI translation of the quote (labelled as AI)",
    "source":"audio|prescription",
    "span":{"char_start":120,"char_end":165},
    "time":{"start_s":42.1,"end_s":47.9,"precision":"word|chunk"},   // audio only
    "rx":{"page":1}                                                    // prescription only
  }],
  "ai_hypotheses": [{
    "id":"H1","type":"possible_condition|red_flag|suggested_question|medication_note|data_gap|unverified_extraction",
    "statement":"…","rationale":"…","supports":["F1","F3"],"confidence":"low|medium|high",
    "needs_clinician_verification": true
  }],
  "model":{"stt":"saaras:v3","ocr":"sarvam-vision (doc-ai)","llm":"sarvam-105b"}
}
```

---

## 4. The 30-minute plan

| Minutes | Deliverable | Skill |
|---|---|---|
| 0–3 | Project scaffold, `.env`, smoke test of all 3 APIs | S1 |
| 3–8 | Record/upload → chunk → Saaras → transcript with timestamps | S2, S3 |
| 8–13 | Prescription upload → Document AI → OCR text (with fallbacks) | S4 |
| 13–19 | LLM summary → verify → demote → timestamps | S5, S6 |
| 19–25 | Two-column UI, audio seek, review controls | S7 |
| 25–28 | Sign-off artifact + lock + export | S8 |
| 28–30 | Resilience check, README, final report | S9, S10 |

If you can run sub-agents/parallel tasks: (A) S2+S3, (B) S4, (C) S7 UI against a mocked `summary.json`, then integrate at minute 19.

**Cut list if behind (drop in this order):** word-level timestamps → English `translate` pass → keyterms → prescription `extract` schema (keep `digitise`) → PDF print styling → diarization. **Never cut:** verbatim verification, source chips, sign-off.

---

## 5. Skills

### S1 — Environment & smoke test (0–3 min)

```bash
python -m venv .venv && source .venv/bin/activate
pip install fastapi "uvicorn[standard]" python-multipart requests sarvamai
which ffmpeg || echo "ffmpeg missing: install it (apt/brew) — required for audio chunking"
export SARVAM_API_KEY=...   # ask the user only if unset
```

Smoke tests (each must return 200 before moving on):

```bash
# LLM
curl -s -X POST https://api.sarvam.ai/v1/chat/completions \
  -H "api-subscription-key: $SARVAM_API_KEY" -H "Content-Type: application/json" \
  -d '{"model":"sarvam-105b","messages":[{"role":"user","content":"Reply with the single word: ready"}],"max_tokens":2000}'

# STT (use any short wav; generate one with ffmpeg if none: ffmpeg -f lavfi -i "sine=frequency=440:duration=2" t.wav)
curl -s -X POST https://api.sarvam.ai/speech-to-text \
  -H "api-subscription-key: $SARVAM_API_KEY" \
  -F file=@t.wav -F model=saaras:v3 -F mode=transcribe -F language_code=unknown -F with_timestamps=true
```

Document AI is smoke-tested in S4 via the SDK. If a call returns 401/403, stop and report the key problem; if 429, back off (S9).

### S2 — Audio capture & chunking

**Browser:** `MediaRecorder` on `navigator.mediaDevices.getUserMedia({audio:true})` (works on `localhost` without HTTPS). Choose a supported mime type (`audio/webm;codecs=opus` → `audio/mp4` → default). Upload the blob as `file` to `POST /api/cases/{id}/audio`. Also support file upload (`<input type=file accept="audio/*">`).

**Server (`audio.py`):** always normalise with ffmpeg — browser WebM/Opus is not a safe input for the STT API.

```python
import subprocess, pathlib, wave, contextlib

def to_chunks(src: str, out_dir: str, seg_s: int = 25):
    out = pathlib.Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    wav = out.parent / "audio.wav"
    subprocess.run(["ffmpeg","-y","-i",src,"-ar","16000","-ac","1","-c:a","pcm_s16le",str(wav)],
                   check=True, capture_output=True)
    subprocess.run(["ffmpeg","-y","-i",str(wav),"-f","segment","-segment_time",str(seg_s),
                    "-c","copy",str(out/"chunk_%03d.wav")], check=True, capture_output=True)
    chunks = sorted(out.glob("chunk_*.wav"))
    result, offset = [], 0.0
    for i, p in enumerate(chunks):
        with contextlib.closing(wave.open(str(p))) as w:
            dur = w.getnframes() / w.getframerate()
        result.append({"idx": i, "path": str(p), "offset_s": round(offset, 3), "dur_s": round(dur, 3)})
        offset += dur
    return str(wav), result
```

Use 25 s chunks (under the 30 s cap with margin). Known limitation: a fixed cut can split a word; mention in README. Stretch: split on silence (`ffmpeg -af silencedetect`) or use the Batch API with diarization.

### S3 — Saaras transcription

```python
# sarvam.py (STT + cache)
import os, json, hashlib, pathlib, time, requests
BASE = "https://api.sarvam.ai"
HDR = {"api-subscription-key": os.environ.get("SARVAM_API_KEY", "")}
CACHE = pathlib.Path("data/cache"); CACHE.mkdir(parents=True, exist_ok=True)
STT_MODEL = os.environ.get("SARVAM_STT_MODEL", "saaras:v3")

def _post_with_retry(fn, tries=4):
    for k in range(tries):
        try:
            r = fn()
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(1.5 * (k + 1)); continue
            r.raise_for_status(); return r
        except requests.Timeout:
            time.sleep(1.5 * (k + 1))
    raise RuntimeError("Sarvam API failed after retries")

def stt_chunk(path, mode="transcribe", language_code="unknown"):
    h = hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
    ck = CACHE / f"stt_{STT_MODEL}_{mode}_{language_code}_{h}.json"
    if ck.exists(): return json.loads(ck.read_text())
    def call():
        with open(path, "rb") as f:
            return requests.post(f"{BASE}/speech-to-text", headers=HDR,
                files={"file": (os.path.basename(path), f, "audio/wav")},
                data={"model": STT_MODEL, "mode": mode, "language_code": language_code,
                      "with_timestamps": "true"}, timeout=90)
    out = _post_with_retry(call).json()
    ck.write_text(json.dumps(out, ensure_ascii=False)); return out
```

Orchestration:
- Run chunks in a `ThreadPoolExecutor(max_workers=4)`; keep results ordered by `idx`.
- Default `language_code="unknown"` (auto-detect); let the UI override with a dropdown. Use the detected code from the first non-empty chunk for the rest if the user left it on auto, to avoid per-chunk language flips.
- Default `mode="transcribe"` (native script — this is the canonical source for verbatim quotes). Optional: a second `mode="translate"` pass for an English view, **stored separately and labelled "AI translation"** — never used as the verbatim source.
- **Normalise timestamps:** the `timestamps` object may be parallel arrays (`words`, `start_time_seconds`, `end_time_seconds`) or a list of dicts, or `null`. Write `normalise_words(resp_ts, offset_s)` that returns `[{"w","start","end"}]` with `offset_s` added, or `None`. Log (without transcript text) which shape you got.
- Segment `end_s` = `offset_s + dur_s`. Canonical `full_text` = NFC-normalised segment texts joined by `"\n"`.
- Empty/silent chunk → keep the segment with empty text so time offsets stay correct.

Optional `keyterms` (docs: list of strings, ≤64 chars each) can bias recognition toward medical terms; add only after the happy path works and check the docs for exact multipart encoding.

### S4 — Prescription parsing (Sarvam Vision / Document AI)

1. Accept JPG/PNG/PDF at `POST /api/cases/{id}/prescription`; store under `rx/`. For phone photos, don't pre-process beyond rotating by EXIF if trivial.
2. Read the Document AI overview page (see §2), then implement `docai_digitise(path, language="hi-IN", output_format="md")` with the SDK:
   - create the job (`client.doc_ai.digitise(...)`), perform any upload step the docs require, poll `get_status` every 2 s up to ~90 s, then `get_download_url` and download the result (it may be a ZIP — unzip and read the `.md`/`.json`).
   - `language` is the primary document language (BCP-47). For unknown/mixed prescriptions use the best guess from the audio's detected language, else `en-IN`; handwritten Indian prescriptions are often English drug names + regional-language instructions.
3. Save `rx_text.json`: `{ "pages": [{"page":1,"text":"…"}], "raw_format":"md" }` (NFC-normalised). If the json output contains layout boxes, keep them for source chips (`rx.bbox`); if not, page-level is enough.
4. Optional second pass with `extract` using a schema like `{drug_name, dose, frequency, duration, prescriber, date}` to render a neat table. **Table values are shown as "AI-extracted", and the verbatim quotes must still come from the digitised text.**
5. Fallbacks, in order: retry once → show the image with a "Type what you can read" textarea so the demo continues → continue without prescription.
6. Illegible handling: if the OCR emits obviously broken tokens, the prompt in S5 instructs the LLM to write `[illegible]` rather than guess.

### S5 — Clinical summary with Sarvam-105B

```python
def chat(messages, model="sarvam-105b", temperature=0.1, max_tokens=6000, timeout=150):
    def call():
        return requests.post(f"{BASE}/v1/chat/completions",
            headers={**HDR, "Content-Type": "application/json"},
            json={"model": model, "messages": messages, "temperature": temperature,
                  "max_tokens": max_tokens}, timeout=timeout)
    try:
        r = _post_with_retry(call, tries=2)
    except Exception:
        # fallback to the faster model once
        def call2():
            return requests.post(f"{BASE}/v1/chat/completions",
                headers={**HDR, "Content-Type": "application/json"},
                json={"model": "sarvam-30b", "messages": messages,
                      "temperature": temperature, "max_tokens": max_tokens}, timeout=timeout)
        r = _post_with_retry(call2, tries=2)
    return r.json()["choices"][0]["message"]["content"]

import re
def extract_json(txt):
    txt = re.sub(r"<think>.*?</think>", "", txt, flags=re.S)
    a, b = txt.find("{"), txt.rfind("}")
    if a < 0 or b < 0: raise ValueError("no JSON object")
    return json.loads(txt[a:b+1])
```

On parse failure: retry once appending "Your last reply was not valid JSON. Return ONLY the JSON object."

**System prompt (use as-is):**

```
You are a clinical documentation assistant for an Indian outpatient (OPD) triage desk.
You receive (A) a transcript of a patient's spoken narrative, possibly in an Indian language or code-mixed,
and (B) OCR text from a prior handwritten/printed prescription. Produce a JSON object only — no prose.

TWO LISTS, STRICTLY SEPARATED:

1) "verbatim_facts": things the patient/record explicitly states.
   - "quote" MUST be copied character-for-character from the provided text, in its ORIGINAL language and script.
     Do NOT translate, correct, summarise or merge quotes. Keep each quote short (a phrase or one sentence).
   - "label": short English label. "english_gloss": faithful English translation of the quote.
   - "source": "audio" if the quote is from (A), "prescription" if from (B).
   - "category": one of chief_complaint, symptom, duration, history, medication, allergy, vitals_reported, other.
   - If handwriting OCR is unclear, do not guess; skip that fact or note it as a data_gap hypothesis.
   - Never add anything the text does not say.

2) "ai_hypotheses": your inferences, clearly NOT facts.
   - "type": possible_condition | red_flag | suggested_question | medication_note | data_gap.
   - Use hedged language ("possible", "consider"). Never state a diagnosis as certain.
   - "supports": IDs of verbatim_facts that motivate it. "confidence": low|medium|high.
   - Include suggested_question items for what the doctor should ask next, and red_flag items only if the text supports concern.
   - Do not invent drug names or doses that are not in the text.

Output schema:
{"verbatim_facts":[{"id":"F1","category":"","label":"","quote":"","english_gloss":"","source":""}],
 "ai_hypotheses":[{"id":"H1","type":"","statement":"","rationale":"","supports":["F1"],"confidence":"low"}]}
Limit: at most 15 verbatim_facts and 10 ai_hypotheses.
```

**User message:** `=== A. TRANSCRIPT ===\n{full_text}\n\n=== B. PRESCRIPTION OCR ===\n{rx_text or "(none provided)"}`.

Settings: `temperature` 0.1. Check the docs for a reasoning-effort option; if present, set low for speed.

### S6 — Verification & provenance (the integrity core)

```python
# provenance.py
import unicodedata

def canon(t: str) -> str: return unicodedata.normalize("NFC", t)

_SKIP = {"\u200b", "\ufeff"}   # keep ZWJ/ZWNJ in canon text (they matter in Indic scripts), skip only in matching
def squash_map(t: str):
    chars, idx = [], []
    for i, ch in enumerate(t):
        if ch.isspace() or ch in _SKIP: continue
        chars.append(ch.lower()); idx.append(i)
    return "".join(chars), idx

def find_span(quote: str, text: str):
    q, _ = squash_map(canon(quote))
    s, idx = squash_map(text)
    if not q: return None
    k = s.find(q)
    if k < 0: return None
    return idx[k], idx[k + len(q) - 1] + 1      # char_start, char_end in canonical text

def to_time(span, segments):
    """segments carry char_start/char_end into full_text; refine to word-level when words exist."""
    a, b = span
    hit = [s for s in segments if s["char_end"] > a and s["char_start"] < b]
    if not hit: return None
    first, last = hit[0], hit[-1]
    return {"start_s": first["offset_s"], "end_s": last["end_s"], "precision": "chunk"}
```

Implementation steps in `summarize.py`:
1. When building `full_text`, record each segment's `char_start`/`char_end` inside it.
2. For each LLM fact: pick the right corpus (`audio` → transcript `full_text`; `prescription` → rx text, per page). `find_span`. 
   - **Found** → keep in `verbatim_facts`; attach `span`; audio facts get `time` via `to_time`; prescription facts get `rx.page`.
   - **Not found** → move to `ai_hypotheses` as `type="unverified_extraction"`, `statement` = the label + english_gloss, `rationale` = "Quote could not be located verbatim in the source; verify manually.", `confidence="low"`. Never drop silently; count them.
3. Word-level refinement (only if S3 produced words): walk `words` of the hit segments sequentially, match the quote's first/last word via `squash_map`, and set `precision:"word"` with `start_s = first_word.start`, `end_s = last_word.end`. Otherwise keep chunk-level and show "≈ chunk" in the UI.
4. Sanity checks to assert in code: every left-column item has `quote`, `span`, and a source locator; every hypothesis has `needs_clinician_verification=True`; every `supports` ID exists (drop dangling IDs).
5. Re-number IDs after demotion so the UI is consistent (`F1…`, `H1…`).

### S7 — Frontend (single `static/index.html`)

Design for a clinic tablet: large tap targets, high contrast, readable Indic fonts (`font-family: system-ui, "Noto Sans Devanagari", "Noto Sans Bengali", "Noto Sans Tamil", "Noto Sans Telugu", sans-serif`). No build step; vanilla JS + `fetch`.

Layout:
- **Header:** "Sunniye, Samjhiye · सुनिए, समझिए" + demo banner + language dropdown (Auto, Hindi, Bengali, Tamil, Telugu, Marathi, Gujarati, Kannada, Malayalam, Punjabi, English) + case ID.
- **Step 1 — Listen:** Record/Stop button with timer and level indicator, or upload. `<audio controls id="player">` once saved. Transcript list with ▶ mm:ss per segment (click → seek).
- **Step 2 — Prescription:** upload; show image/PDF preview on the left, extracted text on the right.
- **Step 3 — Summary:** "Generate summary" button with spinner; then two columns:
  - Left card title: **"Said / Written — verbatim"** (green accent). Each item: label, quote in original script (large), `english_gloss` in small italic with an "AI translation" tag, source chip (`▶ 00:42` or `📄 p1`), and buttons **Confirm · Edit · Reject**.
  - Right card title: **"AI Hypotheses — unverified"** (amber accent, "AI" badge on each item). Each: type tag, statement, rationale, "based on F1, F3" (hover/click highlights those left items), confidence, buttons **Acknowledge · Dismiss · Promote to confirmed** (promote requires a one-line doctor note and is recorded as `doctor_confirmed`, not as verbatim).
- **Step 4 — Sign-off panel (sticky bottom):** doctor name, registration no. (optional), checkbox "I have reviewed every item and the summary reflects my clinical judgement", **Sign & lock** button (disabled until all left items have a decision and the checkbox is ticked). After signing: show hash, timestamp, **Download signoff.json** and **Print view**.

Interactions:
- ▶ chips call `player.currentTime = start_s; player.play()`; for chunk-level precision seek to `max(0, start_s - 1)`.
- Clicking a hypothesis's "based on" IDs scrolls to and flashes the supporting left items.
- Autosave review decisions to `POST /api/cases/{id}/review` on each click (debounced).
- Persistent footer: "Documentation aid — not a diagnostic device. All AI content requires clinician verification."

### S8 — Doctor sign-off artifact

`POST /api/cases/{id}/signoff` body: `{doctor_name, registration_no?, attestation: true}`. Server:

1. Reject if the case is already locked, the attestation is false, or any left-column item lacks a decision.
2. Build the final content: summary + review decisions + doctor edits/notes.
3. Compute hashes with canonical JSON:
   ```python
   import hashlib, json
   def h(obj): return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False,
                                                separators=(",", ":")).encode()).hexdigest()
   ```
   Also `audio_sha256` (of `audio.wav`) and `prescription_sha256` (of each file).
4. Write `data/cases/<id>/signoff.json`:
   ```jsonc
   {
     "case_id":"…", "signed_at_utc":"2026-10-12T10:15:00Z",
     "doctor":{"name":"…","registration_no":"…"},
     "attestation":"Reviewed all items; summary reflects my clinical judgement.",
     "content_sha256":"…", "audio_sha256":"…", "prescription_sha256":["…"],
     "models":{"stt":"saaras:v3","ocr":"sarvam-vision (doc-ai)","llm":"sarvam-105b"},
     "decisions":{"F1":"confirmed","F2":{"status":"edited","new_text":"…"},"H1":"acknowledged","H2":{"status":"promoted","note":"…"}},
     "disclaimer":"Documentation aid, not a diagnostic device. AI hypotheses are unverified."
   }
   ```
5. Set `locked=true` in the case; all mutating endpoints return 409 afterwards. Provide `GET /api/cases/{id}/signoff.json` and a printable HTML (`@media print` CSS: two columns, source chips as text, hash in footer).
6. Be honest in the UI: this is a content-integrity hash plus attestation, **not** a legally valid digital signature (note as future work: DSC/eSign integration).

### S9 — Resilience (do before declaring done)
- **Response cache** keyed by input hash (already in S3; add for chat + Document AI) so a demo can replay offline.
- Retries with backoff on 429/5xx (done in `_post_with_retry`), timeouts everywhere, user-visible error toasts with a "retry" button.
- If STT returns an empty transcript for a non-silent clip, show a clear message and keep the audio.
- Never block the UI: spinners per step; steps are independent (prescription can be skipped).
- Add `GET /api/health` that checks the key is set and ffmpeg exists.

### S10 — QA, demo script, and README
**Self-test (5 quick checks, run them, don't just claim):**
1. Record ~20 s of speech (synthetic script below) → segments + ▶ chips seek correctly.
2. Upload a sample prescription image → text appears; illegible parts show `[illegible]`.
3. Summary: confirm there is **zero** left-column item whose quote is absent from the source (write a 10-line assertion script using `find_span`).
4. Tamper test: change a quote in `summary.json` → the verification step demotes it.
5. Sign-off writes the file, locks the case, and a second sign-off returns 409.

**Synthetic demo narrative (Hindi; read aloud, ~20 s):**
> "मुझे पिछले तीन दिन से बुखार है और रात को खांसी बहुत बढ़ जाती है। सीने में हल्का दर्द भी होता है। मुझे शुगर की दवा चलती है, और पेनिसिलिन से एलर्जी है।"

Adapt to Bengali/Tamil/etc. for the demo language. Use a blurred/synthetic handwritten prescription (never a real patient's).

**README.md must contain:** one-command run (`uvicorn app.main:app --port 8000`), env vars (`SARVAM_API_KEY`, optional `SARVAM_STT_MODEL`), ffmpeg requirement, architecture diagram (the pipeline above), the verbatim-vs-hypothesis guarantee and how it is enforced, known limitations (fixed 25 s chunks, handwriting accuracy, not a legal e-signature, cloud processing of audio/images), and the demo script.

---

## 6. Final report format (what you tell the user when done)

1. What works (checklist from §0 with ✅/❌).
2. How to run (exact commands).
3. Assumptions you made.
4. Deviations from this file and why (e.g., doc-ai flow differences, timestamp shape encountered).
5. Known limitations and the next 3 things to build (Batch API + diarization for doctor/patient/attendant, silence-aware chunking, real e-signature + EMR export such as FHIR/ABDM).

---

## 7. Quick reference — prompts to reuse inside the app

**English view of the transcript (optional, labelled "AI translation")** — call Saaras with `mode="translate"` per chunk, or ask Sarvam-105B: *"Translate faithfully to English. Do not add or remove information. Keep drug names, numbers, and units unchanged."*

**Follow-up questions for the doctor** — covered by `suggested_question` hypotheses in S5; render them as a checklist the doctor can tick during consultation.

**Tone of UI copy:** plain, bilingual where cheap (English + Hindi labels), no medical jargon in buttons.
