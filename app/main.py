"""FastAPI application — Sunniye, Samjhiye (सुनिए, समझिए)."""
import logging
import os
import pathlib
import shutil
import tempfile
import unicodedata
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

from . import store
from .audio import to_chunks
from .sarvam import stt_chunk, docai_digitise, STT_MODEL
from .summarize import generate_summary
from .signoff import create_signoff
from .provenance import canon

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Sunniye, Samjhiye", version="1.0.0")

# Serve static files
static_dir = pathlib.Path(__file__).parent.parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# ---------- Health ----------

@app.get("/api/health")
def health():
    key = os.environ.get("SARVAM_API_KEY", "")
    ffmpeg = shutil.which("ffmpeg")
    return {
        "status": "ok" if key and ffmpeg else "degraded",
        "api_key_set": bool(key),
        "ffmpeg_available": bool(ffmpeg),
    }


# ---------- Cases ----------

@app.post("/api/cases")
def create_case():
    return store.new_case()


@app.get("/api/cases")
def list_cases():
    return store.list_cases()


@app.get("/api/cases/{case_id}")
def get_case(case_id: str):
    try:
        meta = store.load_meta(case_id)
    except FileNotFoundError:
        raise HTTPException(404, "Case not found")
    # Attach available data
    meta["transcript"] = store.load_json(case_id, "transcript.json")
    meta["rx_text"] = store.load_json(case_id, "rx_text.json")
    meta["summary"] = store.load_json(case_id, "summary.json")
    meta["review"] = store.load_json(case_id, "review.json")
    meta["signoff"] = store.load_json(case_id, "signoff.json")
    return meta


# ---------- Audio ----------

@app.post("/api/cases/{case_id}/audio")
async def upload_audio(case_id: str, file: UploadFile = File(...),
                       language_code: str = Form("unknown")):
    meta = store.load_meta(case_id)
    if meta.get("locked"):
        raise HTTPException(409, "Case is locked")

    case_dir = store.case_path(case_id)

    # Save uploaded file
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".audio",
                                     dir=str(case_dir))
    try:
        content = await file.read()
        tmp.write(content)
        tmp.close()

        # Convert and chunk
        chunks_dir = str(case_dir / "chunks")
        wav_path, chunks_info = to_chunks(tmp.name, chunks_dir)
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

    # Transcribe chunks in parallel
    detected_lang = None

    def transcribe_chunk(ci):
        nonlocal detected_lang
        lc = language_code
        if detected_lang and language_code == "unknown":
            lc = detected_lang
        result = stt_chunk(ci["path"], mode="transcribe", language_code=lc)
        # Detect language from first non-empty result
        if not detected_lang and result.get("language_code"):
            detected_lang = result["language_code"]
        return ci["idx"], ci, result

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(transcribe_chunk, ci) for ci in chunks_info]
        results = sorted([f.result() for f in futures], key=lambda x: x[0])

    # Build transcript
    segments = []
    full_parts = []
    char_offset = 0

    for idx, ci, resp in results:
        text = resp.get("transcript", "")
        text = canon(text) if text else ""

        # Normalise timestamps
        words = _normalise_words(resp.get("timestamps"), ci["offset_s"])

        seg = {
            "idx": idx,
            "offset_s": ci["offset_s"],
            "end_s": round(ci["offset_s"] + ci["dur_s"], 3),
            "text": text,
            "words": words,
            "char_start": char_offset,
            "char_end": char_offset + len(text),
        }
        segments.append(seg)
        full_parts.append(text)
        char_offset += len(text) + 1  # +1 for the newline join

    full_text = canon("\n".join(full_parts))

    transcript = {
        "language_code": detected_lang or language_code,
        "segments": segments,
        "full_text": full_text,
    }
    store.save_json(case_id, "transcript.json", transcript)

    return {"status": "ok", "segments": len(segments),
            "language_code": transcript["language_code"]}


def _normalise_words(ts, offset_s: float):
    """Normalise the timestamps object from Saaras into [{w, start, end}].

    The shape may be parallel arrays, a list of dicts, or null.
    """
    if not ts:
        return None

    # Shape 1: list of dicts [{word, start, end}]
    if isinstance(ts, list) and len(ts) > 0 and isinstance(ts[0], dict):
        return [
            {"w": w.get("word", w.get("w", "")),
             "start": round((w.get("start", w.get("start_time", 0)) or 0) + offset_s, 3),
             "end": round((w.get("end", w.get("end_time", 0)) or 0) + offset_s, 3)}
            for w in ts
        ]

    # Shape 2: dict with parallel arrays
    if isinstance(ts, dict):
        words = ts.get("words", ts.get("word", []))
        starts = ts.get("start_time_seconds", ts.get("starts", []))
        ends = ts.get("end_time_seconds", ts.get("ends", []))
        if words and starts and ends and len(words) == len(starts) == len(ends):
            return [
                {"w": w, "start": round(s + offset_s, 3), "end": round(e + offset_s, 3)}
                for w, s, e in zip(words, starts, ends)
            ]

    logger.info(f"Timestamp shape not recognised, returning None. Type: {type(ts)}")
    return None


# ---------- Prescription ----------

@app.post("/api/cases/{case_id}/prescription")
async def upload_prescription(case_id: str, file: UploadFile = File(...),
                              language: str = Form("en-IN")):
    meta = store.load_meta(case_id)
    if meta.get("locked"):
        raise HTTPException(409, "Case is locked")

    case_dir = store.case_path(case_id)
    rx_dir = case_dir / "rx"
    rx_dir.mkdir(exist_ok=True)

    # Save file
    fname = file.filename or "prescription"
    dest = rx_dir / fname
    content = await file.read()
    dest.write_bytes(content)

    # OCR via Document AI
    try:
        result = docai_digitise(str(dest), language=language, output_format="md")
    except Exception as e:
        logger.error(f"Document AI failed: {e}")
        # Fallback: return empty with manual entry option
        result = {"pages": [{"page": 1, "text": ""}], "raw_format": "md"}

    # Combine pages
    all_text = canon("\n\n".join(p["text"] for p in result["pages"]))

    rx_text = {
        "pages": result["pages"],
        "raw_format": result["raw_format"],
        "combined_text": all_text,
    }
    store.save_json(case_id, "rx_text.json", rx_text)

    return {"status": "ok", "pages": len(result["pages"]), "text_preview": all_text[:200]}


# ---------- Summary ----------

@app.post("/api/cases/{case_id}/summary")
def generate_case_summary(case_id: str):
    meta = store.load_meta(case_id)
    if meta.get("locked"):
        raise HTTPException(409, "Case is locked")

    transcript = store.load_json(case_id, "transcript.json")
    if not transcript:
        raise HTTPException(400, "No transcript — record audio first")

    rx_data = store.load_json(case_id, "rx_text.json")
    rx_text = rx_data.get("combined_text") if rx_data else None

    summary = generate_summary(transcript, rx_text, stt_model=STT_MODEL)
    store.save_json(case_id, "summary.json", summary)

    return summary


@app.get("/api/cases/{case_id}/summary")
def get_summary(case_id: str):
    summary = store.load_json(case_id, "summary.json")
    if not summary:
        raise HTTPException(404, "No summary yet")
    return summary


# ---------- Review ----------

@app.post("/api/cases/{case_id}/review")
async def save_review(case_id: str, body: dict = None):
    """Save per-item review decisions. Body: {decisions: {F1: "confirmed", ...}}."""
    from fastapi import Request
    meta = store.load_meta(case_id)
    if meta.get("locked"):
        raise HTTPException(409, "Case is locked")

    if body is None:
        body = {}

    store.save_json(case_id, "review.json", body)
    return {"status": "ok"}


# ---------- Sign-off ----------

@app.post("/api/cases/{case_id}/signoff")
async def sign_off(case_id: str, body: dict = None):
    """Doctor sign-off. Body: {doctor_name, registration_no?, attestation: true}."""
    if body is None:
        raise HTTPException(400, "Body required")

    try:
        result = create_signoff(
            case_id,
            doctor_name=body.get("doctor_name", ""),
            registration_no=body.get("registration_no"),
            attestation=body.get("attestation", False),
        )
    except ValueError as e:
        raise HTTPException(400 if "attestation" in str(e) or "Fact" in str(e)
                            else 409, str(e))

    return result


@app.get("/api/cases/{case_id}/signoff.json")
def get_signoff(case_id: str):
    signoff = store.load_json(case_id, "signoff.json")
    if not signoff:
        raise HTTPException(404, "No sign-off yet")
    return signoff


# ---------- Audio file serving ----------

@app.get("/api/cases/{case_id}/audio.wav")
def serve_audio(case_id: str):
    wav = store.case_path(case_id) / "audio.wav"
    if not wav.exists():
        raise HTTPException(404, "No audio file")
    return FileResponse(str(wav), media_type="audio/wav")


# ---------- Prescription image serving ----------

@app.get("/api/cases/{case_id}/prescription-file")
def serve_prescription(case_id: str):
    rx_dir = store.case_path(case_id) / "rx"
    if not rx_dir.exists():
        raise HTTPException(404, "No prescription")
    files = list(rx_dir.iterdir())
    if not files:
        raise HTTPException(404, "No prescription file")
    f = files[0]
    ext = f.suffix.lower()
    mime = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }.get(ext, "application/octet-stream")
    return FileResponse(str(f), media_type=mime)


# ---------- Root → index.html ----------

@app.get("/")
def root():
    return FileResponse(str(static_dir / "index.html"))
