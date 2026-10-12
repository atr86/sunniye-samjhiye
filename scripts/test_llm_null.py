import sys, os, json, requests
sys.path.insert(0, ".")
from app import store
from app.sarvam import _hdr, BASE
from app.summarize import SYSTEM_PROMPT

transcript = store.load_json('20261012-094010-4603bc', 'transcript.json')
rx_data = store.load_json('20261012-094010-4603bc', 'rx_text.json')

user_msg = f"=== A. TRANSCRIPT ===\n{transcript['full_text']}\n\n=== B. PRESCRIPTION OCR ===\n{rx_data['combined_text']}"
messages = [{'role': 'system', 'content': SYSTEM_PROMPT}, {'role': 'user', 'content': user_msg}]

r = requests.post(f'{BASE}/v1/chat/completions', headers={**_hdr(), 'Content-Type': 'application/json'},
    json={'model': 'sarvam-105b', 'messages': messages, 'temperature': 0.1, 'max_tokens': 6000}, timeout=120)

print(json.dumps(r.json(), ensure_ascii=False, indent=2))
