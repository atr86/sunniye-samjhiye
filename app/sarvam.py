"""Thin Sarvam API clients: STT, LLM chat, Document AI — with response caching."""
import hashlib
import json
import os
import pathlib
import re
import time

import requests

BASE = "https://api.sarvam.ai"
CACHE = pathlib.Path("data/cache")
CACHE.mkdir(parents=True, exist_ok=True)

STT_MODEL = os.environ.get("SARVAM_STT_MODEL", "saaras:v3")


def _hdr():
    key = os.environ.get("SARVAM_API_KEY")
    if not key:
        from dotenv import load_dotenv
        load_dotenv("apikey/.gitenv")
        load_dotenv(".env")
        key = os.environ.get("SARVAM_API_KEY", "")
    return {"api-subscription-key": key}


def _post_with_retry(fn, tries=4):
    for k in range(tries):
        try:
            r = fn()
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(1.5 * (k + 1))
                continue
            r.raise_for_status()
            return r
        except requests.Timeout:
            time.sleep(1.5 * (k + 1))
    raise RuntimeError("Sarvam API failed after retries")


# ---------- STT ----------

def stt_chunk(path: str, mode: str = "transcribe",
              language_code: str = "unknown") -> dict:
    """Transcribe a single audio chunk via Saaras."""
    h = hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
    ck = CACHE / f"stt_{STT_MODEL}_{mode}_{language_code}_{h}.json"
    if ck.exists():
        return json.loads(ck.read_text(encoding="utf-8"))

    def call():
        with open(path, "rb") as f:
            return requests.post(
                f"{BASE}/speech-to-text",
                headers=_hdr(),
                files={"file": (os.path.basename(path), f, "audio/wav")},
                data={
                    "model": STT_MODEL,
                    "mode": mode,
                    "language_code": language_code,
                    "with_timestamps": "true",
                },
                timeout=90,
            )

    out = _post_with_retry(call).json()
    ck.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


# ---------- LLM Chat ----------

def chat(messages: list[dict], model: str = "sarvam-105b",
         temperature: float = 0.1, max_tokens: int = 6000,
         timeout: int = 150) -> str:
    """Call Sarvam-105B chat completions. Falls back to sarvam-105b-conversations."""
    def call():
        return requests.post(
            f"{BASE}/v1/chat/completions",
            headers={**_hdr(), "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=timeout,
        )

    try:
        r = _post_with_retry(call, tries=2)
    except Exception:
        def call2():
            return requests.post(
                f"{BASE}/v1/chat/completions",
                headers={**_hdr(), "Content-Type": "application/json"},
                json={
                    "model": "sarvam-105b-conversations",
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
                timeout=timeout,
            )
        r = _post_with_retry(call2, tries=2)
    return r.json()["choices"][0]["message"]["content"]


def extract_json(txt: str) -> dict:
    """Parse JSON from LLM output, stripping <think> blocks."""
    txt = re.sub(r"<think>.*?</think>", "", txt, flags=re.S)
    a, b = txt.find("{"), txt.rfind("}")
    if a < 0 or b < 0:
        raise ValueError("no JSON object in LLM response")
    return json.loads(txt[a:b + 1])


# ---------- Document AI ----------

def docai_digitise(file_path: str, language: str = "en-IN",
                   output_format: str = "md") -> dict:
    """Upload a document to Sarvam Document AI (digitise) and poll until done.

    Returns dict with keys: pages (list of {page, text}), raw_format.
    Uses the REST API directly (not SDK) for reliability.
    """
    import io
    import zipfile

    fname = os.path.basename(file_path)
    ext = os.path.splitext(fname)[1].lower()
    mime_map = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }
    mime = mime_map.get(ext, "application/octet-stream")

    # Check cache
    h = hashlib.sha256(pathlib.Path(file_path).read_bytes()).hexdigest()
    ck = CACHE / f"docai_digitise_{language}_{output_format}_{h}.json"
    if ck.exists():
        return json.loads(ck.read_text(encoding="utf-8"))

    # Create job
    def create():
        with open(file_path, "rb") as f:
            return requests.post(
                f"{BASE}/doc-ai/v1/job/digitise",
                headers=_hdr(),
                files={"file": (fname, f, mime)},
                data={"language": language, "output_format": output_format},
                timeout=60,
            )

    resp = _post_with_retry(create, tries=2).json()
    job_id = resp.get("job_id")
    if not job_id:
        raise RuntimeError(f"Doc AI job creation failed: {resp}")

    # Poll
    terminal = {"completed", "partially_completed", "failed", "rejected"}
    for _ in range(45):  # ~90s
        time.sleep(2)
        sr = requests.get(
            f"{BASE}/doc-ai/v1/job/{job_id}/status",
            headers=_hdr(), timeout=30,
        )
        sr.raise_for_status()
        status = sr.json().get("status", "").lower()
        if status in terminal:
            break
    else:
        raise RuntimeError("Doc AI job timed out")

    if status in ("failed", "rejected"):
        raise RuntimeError(f"Doc AI job {status}: {sr.json()}")

    # Download result
    dl = requests.get(
        f"{BASE}/doc-ai/v1/job/{job_id}/download-url",
        headers=_hdr(), timeout=30,
    )
    dl.raise_for_status()
    dl_info = dl.json()
    result_resp = requests.get(dl_info["url"], timeout=60)
    result_resp.raise_for_status()

    # Parse result — it's a ZIP containing md/html/json + metadata
    pages = []
    try:
        zf = zipfile.ZipFile(io.BytesIO(result_resp.content))
        # Find the primary content file
        content_files = [
            n for n in zf.namelist()
            if not n.startswith("metadata/") and not n.endswith("manifest.json")
            and not n.endswith("/")
        ]
        for cf in sorted(content_files):
            text = zf.read(cf).decode("utf-8", errors="replace")
            pages.append({"page": len(pages) + 1, "text": text})
    except zipfile.BadZipFile:
        # Not a ZIP — try treating as plain text
        text = result_resp.content.decode("utf-8", errors="replace")
        pages.append({"page": 1, "text": text})

    result = {"pages": pages, "raw_format": output_format}
    ck.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result
