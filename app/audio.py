"""Audio conversion and chunking via ffmpeg."""
import contextlib
import pathlib
import subprocess
import wave


def to_chunks(src: str, out_dir: str, seg_s: int = 25) -> tuple[str, list[dict]]:
    """Convert audio to 16kHz mono WAV and split into chunks.

    Returns (wav_path, list_of_chunk_info_dicts).
    """
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    wav = out.parent / "audio.wav"

    # Convert to 16kHz mono PCM
    subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-ar", "16000", "-ac", "1",
         "-c:a", "pcm_s16le", str(wav)],
        check=True, capture_output=True,
    )

    # Segment
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(wav), "-f", "segment",
         "-segment_time", str(seg_s), "-c", "copy",
         str(out / "chunk_%03d.wav")],
        check=True, capture_output=True,
    )

    chunks = sorted(out.glob("chunk_*.wav"))
    result = []
    offset = 0.0
    for i, p in enumerate(chunks):
        with contextlib.closing(wave.open(str(p))) as w:
            dur = w.getnframes() / w.getframerate()
        result.append({
            "idx": i,
            "path": str(p),
            "offset_s": round(offset, 3),
            "dur_s": round(dur, 3),
        })
        offset += dur
    return str(wav), result
