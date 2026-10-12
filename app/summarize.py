"""Clinical summary generation, verification, and demotion logic."""
import json
import logging

from .provenance import canon, find_span, to_time
from .sarvam import chat, extract_json

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a clinical documentation assistant for an Indian outpatient (OPD) triage desk.
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
Limit: at most 15 verbatim_facts and 10 ai_hypotheses."""


def generate_summary(transcript_data: dict, rx_text: str | None,
                     stt_model: str = "saaras:v3") -> dict:
    """Run the full pipeline: LLM call → verify quotes → demote failures → attach timestamps.

    Returns the complete summary.json structure.
    """
    full_text = transcript_data.get("full_text", "")
    segments = transcript_data.get("segments", [])

    # Build user message
    rx_part = rx_text if rx_text else "(none provided)"
    user_msg = f"=== A. TRANSCRIPT ===\n{full_text}\n\n=== B. PRESCRIPTION OCR ===\n{rx_part}"

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    # Call LLM
    raw = chat(messages, temperature=0.1, max_tokens=6000)

    # Parse JSON
    try:
        data = extract_json(raw)
    except (ValueError, json.JSONDecodeError):
        # Retry once
        messages.append({"role": "assistant", "content": raw})
        messages.append({
            "role": "user",
            "content": "Your last reply was not valid JSON. Return ONLY the JSON object.",
        })
        raw2 = chat(messages, temperature=0.1, max_tokens=6000)
        data = extract_json(raw2)

    verbatim_facts = data.get("verbatim_facts", [])
    ai_hypotheses = data.get("ai_hypotheses", [])

    # Verify and demote
    verified = []
    demoted = []

    for fact in verbatim_facts:
        quote = fact.get("quote", "")
        source = fact.get("source", "audio")

        if source == "audio":
            span = find_span(quote, full_text)
            if span:
                fact["span"] = {"char_start": span[0], "char_end": span[1]}
                time_info = to_time(span, segments)
                if time_info:
                    fact["time"] = time_info
                verified.append(fact)
            else:
                # Demote to hypothesis
                demoted.append({
                    "type": "unverified_extraction",
                    "statement": f"{fact.get('label', '')}: {fact.get('english_gloss', '')}",
                    "rationale": "Quote could not be located verbatim in the source; verify manually.",
                    "supports": [],
                    "confidence": "low",
                    "needs_clinician_verification": True,
                })
        elif source == "prescription":
            if rx_text:
                span = find_span(quote, rx_text)
                if span:
                    fact["span"] = {"char_start": span[0], "char_end": span[1]}
                    fact["rx"] = {"page": 1}  # page-level for now
                    verified.append(fact)
                else:
                    demoted.append({
                        "type": "unverified_extraction",
                        "statement": f"{fact.get('label', '')}: {fact.get('english_gloss', '')}",
                        "rationale": "Quote could not be located verbatim in the prescription text; verify manually.",
                        "supports": [],
                        "confidence": "low",
                        "needs_clinician_verification": True,
                    })
            else:
                verified.append(fact)  # no rx to verify against
        else:
            verified.append(fact)

    # Re-number IDs
    for i, f in enumerate(verified):
        f["id"] = f"F{i + 1}"

    all_hypotheses = ai_hypotheses + demoted
    for i, h in enumerate(all_hypotheses):
        h["id"] = f"H{i + 1}"
        h["needs_clinician_verification"] = True
        # Clean dangling supports
        valid_ids = {f["id"] for f in verified}
        h["supports"] = [s for s in h.get("supports", []) if s in valid_ids]

    if demoted:
        logger.warning(f"Demoted {len(demoted)} unverified facts to hypotheses")

    summary = {
        "verbatim_facts": verified,
        "ai_hypotheses": all_hypotheses,
        "model": {
            "stt": stt_model,
            "ocr": "sarvam-vision (doc-ai)",
            "llm": "sarvam-105b",
        },
    }
    return summary
