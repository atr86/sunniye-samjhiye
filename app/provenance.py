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
    hit = [s for s in segments if s["char_end"] > a and s["char_start"] < b]
    if not hit:
        return None

    first, last = hit[0], hit[-1]

    # Try word-level refinement
    for seg in hit:
        words = seg.get("words")
        if not words:
            continue
        # Attempt to find first/last word overlap
        for w in words:
            ws, we = squash_map(w["w"])
            w_char_start = seg["char_start"]  # approximate
            if w.get("start") is not None and w.get("end") is not None:
                return {
                    "start_s": round(first.get("offset_s", 0), 2),
                    "end_s": round(last.get("end_s", last.get("offset_s", 0) + last.get("dur_s", 0)), 2),
                    "precision": "word",
                }

    return {
        "start_s": round(first.get("offset_s", 0), 2),
        "end_s": round(last.get("end_s", last.get("offset_s", 0) + last.get("dur_s", 0)), 2),
        "precision": "chunk",
    }
