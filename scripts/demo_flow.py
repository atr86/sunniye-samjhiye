"""End-to-end integration and verification script for Sunniye, Samjhiye."""
import os
import sys
import json
from pathlib import Path
from fastapi.testclient import TestClient
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")
load_dotenv("apikey/.gitenv")
load_dotenv(".env")

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.main import app
from app import store

client = TestClient(app)
cid = "20261012-092756-93c5e6"

print(f"Generating clinical summary for case {cid}...")
resp = client.post(f"/api/cases/{cid}/summary")
if resp.status_code != 200:
    print("Summary generation failed:", resp.status_code, resp.text)
    sys.exit(1)

summary = resp.json()
facts = summary.get("verbatim_facts", [])
hypotheses = summary.get("ai_hypotheses", [])

print(f"\n--- VERBATIM FACTS ({len(facts)}) ---")
for f in facts:
    time_str = f"Time: {f['time']['start_s']}s-{f['time']['end_s']}s" if f.get("time") else ""
    rx_str = f"Rx page: {f['rx']['page']}" if f.get("rx") else ""
    locator = time_str or rx_str
    print(f"[{f['id']}] [{f.get('category')}] {f.get('label')}: \"{f.get('quote')}\" ({locator})")

print(f"\n--- AI HYPOTHESES ({len(hypotheses)}) ---")
for h in hypotheses:
    print(f"[{h['id']}] [{h.get('type')}] {h.get('statement')} (conf: {h.get('confidence')})")

print("\nSubmitting review decisions...")
decisions = {f["id"]: "confirmed" for f in facts}
for h in hypotheses:
    decisions[h["id"]] = "acknowledged"

r = client.post(f"/api/cases/{cid}/review", json={"decisions": decisions})
assert r.status_code == 200, r.text

print("Signing off case...")
r = client.post(f"/api/cases/{cid}/signoff", json={
    "doctor_name": "Dr. R. K. Sharma",
    "registration_no": "MCI-49210",
    "attestation": True
})
assert r.status_code == 200, r.text
signoff = r.json()
print("Sign-off complete!")
print("Content SHA-256:", signoff["content_sha256"])
print("Audio SHA-256:", signoff.get("audio_sha256"))
print("Prescription SHA-256:", signoff.get("prescription_sha256"))
print("Signed At:", signoff["signed_at_utc"])

# Test lock
meta = store.load_meta(cid)
assert meta["locked"] is True
print("Case is locked: True")

# Test 409 conflict
r_conflict = client.post(f"/api/cases/{cid}/signoff", json={
    "doctor_name": "Dr. R. K. Sharma",
    "attestation": True
})
assert r_conflict.status_code == 409
print("Second sign-off returned 409 Conflict as expected!")
print("\nALL VERIFICATIONS COMPLETED SUCCESSFULLY!")
