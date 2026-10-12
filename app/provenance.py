"""Provenance: canonicalisation, substring matching, and time mapping."""
import unicodedata


def canon(t: str) -> str:
    """NFC-normalise text."""
    return unicodedata.normalize("NFC", t)


_SKIP = {"\u200b", "\ufeff"}  # skip ZWSP and BOM; keep ZWJ/ZWNJ for Indic scripts


def squash_map(t: str) -> tuple[str, list[int]]:
    """Return (squashed_lowercase_text, index_map_back_to_original)."""
    chars, idx = [], []
    for i, ch in enumerate(t):
        if ch.isspace() or ch in _SKIP:
            continue
        chars.append(ch.lower())
        idx.append(i)
    return "".join(chars), idx


def find_span(quote: str, text: str) -> tuple[int, int] | None:
    """Find the character span of `quote` inside `text` using fuzzy whitespace matching.

    Returns (char_start, char_end) in the canonical text, or None.
    """
    q, _ = squash_map(canon(quote))
    s, idx = squash_map(text)
    if not q:
        return None
    k = s.find(q)
    if k < 0:
        return None
    return idx[k], idx[k + len(q) - 1] + 1  # char_start, char_end


def to_time(span: tuple[int, int], segments: list[dict]) -> dict | None:
    """Map a character span to audio timestamps using segment boundaries.

    Segments must have char_start, char_end, offset_s, end_s, and optionally words.
    Returns {start_s, end_s, precision} or None.
    """
    a, b = span
    hit = [s for s in segments if s.get("char_end", 0) > a and s.get("char_start", 0) < b]
    if not hit:
        return None

    first, last = hit[0], hit[-1]
    chunk_start = round(float(first.get("offset_s", 0.0)), 2)
    chunk_end = round(float(last.get("end_s", last.get("offset_s", 0.0) + last.get("dur_s", 0.0))), 2)

    # Word-level refinement if words exist in hit segments
    all_words = []
    for s in hit:
        ws = s.get("words")
        if ws and isinstance(ws, list):
            all_words.extend(ws)

    valid_words = [
        w for w in all_words
        if w.get("start") is not None and w.get("end") is not None
    ]

    if valid_words:
        return {
            "start_s": round(float(valid_words[0]["start"]), 2),
            "end_s": round(float(valid_words[-1]["end"]), 2),
            "precision": "word",
        }

    return {
        "start_s": chunk_start,
        "end_s": chunk_end,
        "precision": "chunk",
    }
