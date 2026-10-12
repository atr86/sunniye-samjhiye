# Sunniye, Samjhiye (सुनिए, समझिए) — Patient Intake Storyteller

> **"Listen first. Understand next."**
> A clinical documentation aid for Indian outpatient (OPD) triage.
> Stack: **Saaras** (Indic Speech-to-Text), **Sarvam Vision / Document AI** (Prescription OCR), **Sarvam-105B** (Clinical Reasoning), FastAPI, Vanilla JS dark-mode web application.

---

## 1. Quick Start (One Command)

### Prerequisites
- Python 3.10+
- `SARVAM_API_KEY` (configured in `.env` or `apikey/.gitenv`)
- FFmpeg (bundled via `imageio-ffmpeg` / installed in virtual environment)

### Run the App
```bash
# Activate your environment
& "D:\Workspace\PythonEnv\.venv\Scripts\Activate.ps1"

# Launch the FastAPI server
uvicorn app.main:app --port 8000 --reload
```
Open your browser at: **[http://localhost:8000](http://localhost:8000)**

---

## 2. Environment Variables

Create a `.env` file in the project root (or `apikey/.gitenv`):

| Variable | Description | Default |
|---|---|---|
| `SARVAM_API_KEY` | Your Sarvam AI Subscription Key (**Required**) | `""` |
| `SARVAM_STT_MODEL` | Saaras speech model identifier | `saaras:v3` (stable, fallback to `saaras:v4`) |

---

## 3. Architecture & Pipeline

```text
Patient Voice (Mic / Upload) ──► FFmpeg (16 kHz mono WAV, 25s chunks) ──► Saaras STT (Parallel chunks + timestamps)
                                                                                  │
Prescription Photo / PDF / TXT ─► Sarvam Vision (Doc AI) or Direct UTF-8 ────────┤
                                                                                  ▼
                                                         Canonical Sources: Transcript segments + Rx text
                                                                                  ▼
                                                         Sarvam-105B (Zero-prose structured JSON extraction)
                                                                                  ▼
                                                         Provenance Verification Engine (NFC + Whitespace Squash)
                                                         ├─ Found verbatim: Left column ("Said / Written") + Seek Chips
                                                         └─ Not verbatim: Demoted to Right column ("AI Hypotheses")
                                                                                  ▼
                                                         Tablet UI: Confirm / Edit / Reject / Promote
                                                                                  ▼
                                                         Doctor Sign-off Artifact (SHA-256 Content & Media Hash) ──► Lock Case
```

---

## 4. The Verbatim-vs-Hypothesis Guarantee

A core safety feature of Sunniye, Samjhiye is strict separation of clinical facts and AI inferences:

### Left Column: "Said / Written — verbatim" (Green Accent)
- Every item **must be a character-for-character substring** of either the Saaras speech transcript or Document AI prescription text (after Unicode NFC normalisation and whitespace squashing).
- Provenance code locates the exact character span `[char_start, char_end]` and computes audio playback timestamps (`▶ mm:ss`).
- **Strict Demotion Rule:** If any item returned by the LLM cannot be located verbatim in the source text, it is **immediately demoted** to the right column with `type: "unverified_extraction"` and labelled as unverified. Code asserts zero unverified facts ever appear in the left column.

### Right Column: "AI Hypotheses — unverified" (Amber Accent)
- Inferences, possible conditions, red flags, medication notes, suggested follow-up questions, and data gaps.
- Clearly marked with an **AI** badge and confidence level.
- Always marked `needs_clinician_verification: true`.
- Clinicians can acknowledge, dismiss, or promote hypotheses (with an explicit clinician note).

---

## 5. Doctor Sign-Off & Tamper-Evident Artifact

When the doctor reviews every left-column fact and checks the attestation checkbox, the case is finalized:
- Generates a canonical JSON object of the summary and all doctor decisions.
- Computes **SHA-256** content integrity hash (`content_sha256`).
- Computes SHA-256 hashes of the original audio recording (`audio_sha256`) and all uploaded prescription documents (`prescription_sha256`).
- Writes `data/cases/<case_id>/signoff.json`.
- Locks the case: `locked: true`. Any subsequent mutation returns **HTTP 409 Conflict**.
- Enables one-click JSON download and printer-friendly view (`@media print`).

---

## 6. Synthetic Demo Script (for OPD Triage)

### Spoken Narrative (Hindi, ~20 seconds):
> *"मुझे पिछले तीन दिन से बुखार है और रात को खांसी बहुत बढ़ जाती है। सीने में हल्का दर्द भी होता है। मुझे शुगर की दवा चलती है, और पेनिसिलिन से एलर्जी है।"*

### English Translation:
> *"I have had fever for the past three days, and the cough gets much worse at night. I also feel mild chest discomfort. I take medication for diabetes, and I am allergic to penicillin."*

### Sample Data Included:
- Spoken Audio: `sample_data/sample_hindi_narrative.wav` (Generated via Sarvam AI)
- Prescription Image: `sample_data/sample_prescription.png` (Synthesized OPD slip with Metformin, Paracetamol, Penicillin allergy note)
- Prescription Text: `sample_data/sample_prescription.txt` (Plain text prescription for direct intake)

---

## 7. Automated Self-Tests

Run the 5 validation checks described in the definition of done:
```bash
& "D:\Workspace\PythonEnv\.venv\Scripts\python.exe" -c "
import tests.test_pipeline as t
for name in sorted(dir(t)):
    if name.startswith('test_'):
        getattr(t, name)()
print('All 5 pipeline checks passed!')
"
```

1. **Check 1:** Health endpoint & environment verification (API key + FFmpeg).
2. **Check 2:** Audio conversion, 25s chunking, and timestamp provenance mapping.
3. **Check 3:** 10-line assertion script verifying zero left-column facts are absent from source.
4. **Check 4:** Tamper test — modified/hallucinated quotes are reliably demoted to AI hypotheses.
5. **Check 5:** Sign-off artifact generation, SHA-256 integrity locking, and HTTP 409 conflict on re-signing.

---

## 8. Known Limitations & Roadmap

1. **Fixed 25s Audio Cuts:** Fixed segmentation can occasionally divide a word at chunk boundary.
   - *Roadmap:* Implement silence-aware segmentation (`silence_detect`) and Sarvam STT Batch API (up to 2h) with speaker diarization (Doctor / Patient / Attendant).
2. **Handwriting Legibility:** Unclear handwritten prescriptions emit `[illegible]` tokens.
   - *Roadmap:* Multi-pass enhancement with Document AI `extract` key-value schema.
3. **Digital Signature:** The current sign-off is a cryptographic SHA-256 content-integrity hash and attestation record.
   - *Roadmap:* Integration with Aadhaar eSign / Digital Signature Certificate (DSC) and ABDM / FHIR R4 clinical artifact export.
4. **Cloud Processing:** Audio and prescription images are processed via Sarvam AI Cloud APIs.
   - *Notice:* Synthetic data only for demonstration; do not upload real patient protected health information (PHI).
