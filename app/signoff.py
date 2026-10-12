"""Doctor sign-off artifact: hashing, locking, export."""
import hashlib
import json
import pathlib
from datetime import datetime, timezone

from . import store


def _hash(obj) -> str:
    """SHA-256 of canonical JSON."""
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, ensure_ascii=False,
                   separators=(",", ":")).encode()
    ).hexdigest()


def _file_hash(path: str) -> str | None:
    """SHA-256 of a file's bytes."""
    p = pathlib.Path(path)
    if not p.exists():
        return None
    return hashlib.sha256(p.read_bytes()).hexdigest()


def create_signoff(case_id: str, doctor_name: str,
                   registration_no: str | None,
                   attestation: bool) -> dict:
    """Build and write the sign-off artifact, then lock the case.

    Returns the signoff dict or raises.
    """
    meta = store.load_meta(case_id)
    if meta.get("locked"):
        raise ValueError("Case is already locked (signed off)")

    if not attestation:
        raise ValueError("Attestation must be true")

    # Load summary + review
    summary = store.load_json(case_id, "summary.json")
    review = store.load_json(case_id, "review.json") or {}

    if not summary:
        raise ValueError("No summary to sign off on")

    # Check all verbatim facts have a decision
    decisions = review.get("decisions", {})
    for fact in summary.get("verbatim_facts", []):
        fid = fact["id"]
        if fid not in decisions:
            raise ValueError(f"Fact {fid} has no review decision")

    # Build content for hashing
    content = {
        "summary": summary,
        "decisions": decisions,
    }

    # File hashes
    case_dir = store.case_path(case_id)
    audio_wav = case_dir / "audio.wav"
    rx_files = list((case_dir / "rx").glob("*")) if (case_dir / "rx").exists() else []

    signoff = {
        "case_id": case_id,
        "signed_at_utc": datetime.now(timezone.utc).isoformat(),
        "doctor": {
            "name": doctor_name,
            "registration_no": registration_no or "",
        },
        "attestation": "Reviewed all items; summary reflects my clinical judgement.",
        "content_sha256": _hash(content),
        "audio_sha256": _file_hash(str(audio_wav)),
        "prescription_sha256": [_file_hash(str(f)) for f in rx_files if f.is_file()],
        "models": summary.get("model", {}),
        "decisions": decisions,
        "disclaimer": "Documentation aid, not a diagnostic device. AI hypotheses are unverified.",
    }

    store.save_json(case_id, "signoff.json", signoff)

    # Lock the case
    meta["locked"] = True
    meta["signed_at_utc"] = signoff["signed_at_utc"]
    store.save_meta(case_id, meta)

    return signoff
