"""Persistent JSON-on-disk case store."""
import json
import pathlib
import uuid
from datetime import datetime, timezone


DATA_DIR = pathlib.Path("data/cases")


def _case_dir(case_id: str) -> pathlib.Path:
    d = DATA_DIR / case_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def new_case() -> dict:
    cid = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    d = _case_dir(cid)
    meta = {
        "case_id": cid,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "locked": False,
    }
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    return meta


def load_meta(case_id: str) -> dict:
    p = _case_dir(case_id) / "meta.json"
    if not p.exists():
        raise FileNotFoundError(f"Case {case_id} not found")
    return json.loads(p.read_text())


def save_meta(case_id: str, meta: dict):
    (_case_dir(case_id) / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2)
    )


def save_json(case_id: str, name: str, data: dict):
    (_case_dir(case_id) / name).write_text(
        json.dumps(data, ensure_ascii=False, indent=2)
    )


def load_json(case_id: str, name: str) -> dict | None:
    p = _case_dir(case_id) / name
    if not p.exists():
        return None
    return json.loads(p.read_text())


def case_path(case_id: str) -> pathlib.Path:
    return _case_dir(case_id)


def list_cases() -> list[dict]:
    if not DATA_DIR.exists():
        return []
    cases = []
    for d in sorted(DATA_DIR.iterdir(), reverse=True):
        if d.is_dir():
            meta_p = d / "meta.json"
            if meta_p.exists():
                cases.append(json.loads(meta_p.read_text()))
    return cases
