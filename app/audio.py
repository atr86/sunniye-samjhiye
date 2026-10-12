"""Audio conversion and chunking via ffmpeg."""
import contextlib
import os
import pathlib
import shutil
import subprocess
import sys
import wave


def get_ffmpeg_cmd() -> str:
    """Find ffmpeg binary reliably on PATH, venv Scripts, or imageio-ffmpeg."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    venv_ffmpeg = os.path.join(os.path.dirname(sys.executable), "ffmpeg.exe")
    if os.path.exists(venv_ffmpeg):
        return venv_ffmpeg
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def to_chunks(src: str, out_dir: str, seg_s: int = 25) -> tuple[str, list[dict]]:
    """Convert audio to 16kHz mono WAV and split into chunks.

    Returns (wav_path, list_of_chunk_info_dicts).
    """
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    wav = out.parent / "audio.wav"
    ffmpeg = get_ffmpeg_cmd()

    # Convert to 16kHz mono PCM
    subprocess.run(
        [ffmpeg, "-y", "-i", src, "-ar", "16000", "-ac", "1",
         "-c:a", "pcm_s16le", str(wav)],
        check=True, capture_output=True,
    )

    # Segment
    subprocess.run(
        [ffmpeg, "-y", "-i", str(wav), "-f", "segment",
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
