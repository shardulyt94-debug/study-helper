"""
Lecture transcription (host side). transcribe_lecture.py ko subprocess se chalata hai.

Kya karta hai: hash cache check -> (zarurat ho toh) ffmpeg se wav -> script chalao (python -u) ->
progress (\\r wali line bhi) parse karke milestone -> timeout pe partial transcript bachao -> result.
Ek GPU job ek samay pe (lock).
"""
from __future__ import annotations

import codecs
import collections
import hashlib
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

import config
import events
from .registry import error, ok, params, partial, register, ToolResult

PROGRESS_RE = re.compile(
    r"chunk\s+(\d+)\s*/\s*(\d+)\s*\|\s*([\d.]+)\s*/\s*([\d.]+)\s*min\s*\|\s*ETA\s+(\d+):(\d{2}):(\d{2})")
TS_RE = re.compile(r"^\[(\d{2}:\d{2}:\d{2})\]")
SKIP_MARK = "[chunk skip hua"
_gpu_lock = threading.Lock()


# ---------- pure helpers (tests inpe hain) ----------
def parse_progress(line: str) -> dict | None:
    m = PROGRESS_RE.search(line)
    if not m:
        return None
    i, n, done, total, h, mi, s = m.groups()
    return {"chunk": int(i), "chunks": int(n), "done_min": float(done), "total_min": float(total),
            "eta_sec": int(h) * 3600 + int(mi) * 60 + int(s)}


def split_stream(buffer: str) -> tuple[list[str], str]:
    """Script progress '\\r' se print karta hai. \\r aur \\n dono pe todo.
    Returns (poori lines, adhoora bacha hua hissa)."""
    parts = re.split(r"[\r\n]+", buffer)
    return [p for p in parts[:-1] if p.strip()], parts[-1]


def summarize_transcript(text: str) -> dict:
    lines = [l for l in text.splitlines() if l.strip()]
    last = None
    for l in reversed(lines):
        m = TS_RE.match(l)
        if m:
            last = m.group(1)
            break
    return {"lines": len(lines), "last_timestamp": last, "skipped": text.count(SKIP_MARK)}


def file_hash(path: Path, n: int = 16) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()[:n]


# ---------- ffmpeg ----------
def ensure_wav(src: Path, dst: Path) -> Path:
    """.wav ho toh waise hi. Baaki (m4a/aac/mp3/mp4...) ko 16k mono wav banao."""
    if src.suffix.lower() == ".wav":
        return src
    ffmpeg = shutil.which(config.FFMPEG)
    if not ffmpeg:
        raise RuntimeError(f"ffmpeg host pe nahi mila (FFMPEG={config.FFMPEG!r}). Install kar ya .env mein FFMPEG ka path de.")
    dst.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", str(dst)],
                       capture_output=True, timeout=900)
    if r.returncode != 0 or not dst.exists():
        raise RuntimeError("ffmpeg convert fail: " + r.stderr.decode("utf-8", "replace")[-400:])
    return dst


# ---------- tool ----------
@register(
    "transcribe_lecture",
    "Lecture recording ko text mein badlo (host pe GPU model). audio_path container ka path hota hai, "
    "jaise /workspace/uploads/lecture.m4a. 40-45 min ke lecture mein kuch minute lagte hain. "
    "Transcript scratch mein save hota hai aur uska path milta hai; padhne ke liye read_file(path, part=N). "
    "lang: 'mr' = Marathi+English lecture (default), 'hi' = Hinglish. "
    "Transcript mein sound-alike galtiyan ho sakti hain: Classroom material se confirm kar, warna [unclear].",
    params({"audio_path": {"type": "string"}, "lang": {"type": "string", "enum": ["mr", "hi"]}}, ["audio_path"]),
)
def transcribe_lecture(audio_path: str, lang: str = "mr") -> ToolResult:
    if not re.fullmatch(r"[a-z]{2,3}", lang):
        return error(f"lang galat: {lang!r}")
    if not config.TRANSCRIBE_PYTHON or not config.TRANSCRIBE_SCRIPT:
        return error(".env mein TRANSCRIBE_PYTHON aur TRANSCRIBE_SCRIPT set nahi hain.")
    for label, p in (("TRANSCRIBE_PYTHON", config.TRANSCRIBE_PYTHON), ("TRANSCRIBE_SCRIPT", config.TRANSCRIBE_SCRIPT)):
        if not Path(p).exists():
            return error(f"{label} ka path nahi mila: {p}")
    try:
        src = config.to_host(audio_path)
    except config.PathError as e:
        return error(str(e))
    if not src.is_file():
        return error(f"audio file nahi mili: {audio_path}")

    if not _gpu_lock.acquire(blocking=False):
        return error("doosra transcription already chal raha hai (ek GPU job ek samay pe). Wait kar.")
    try:
        return _run(src, lang, audio_path)
    finally:
        _gpu_lock.release()


def _run(src: Path, lang: str, audio_path: str) -> ToolResult:
    out_dir = config.scratch_dir_host()
    out_dir.mkdir(parents=True, exist_ok=True)

    digest = file_hash(src)
    cache_dir = config.CACHE_DIR / "transcripts"
    cached = cache_dir / f"{digest}_{lang}.txt"
    if cached.exists():
        dest = out_dir / f"{src.stem}_{lang}_cached.txt"
        shutil.copyfile(cached, dest)
        info = summarize_transcript(dest.read_text(encoding="utf-8", errors="replace"))
        return ok(f"CACHE HIT: ye audio pehle transcribe ho chuka hai.\ntranscript: {config.to_container(dest)}\n"
                  f"lines: {info['lines']}, aakhri timestamp: {info['last_timestamp']}", **info, cached=True)

    try:
        if src.suffix.lower() != ".wav":
            events.milestone("Audio convert ho raha hai (ffmpeg)...")
        wav = ensure_wav(src, out_dir / f"{src.stem}_{digest}.wav")
    except Exception as e:
        return error(str(e))

    cmd = [config.TRANSCRIBE_PYTHON, "-u", config.TRANSCRIBE_SCRIPT, str(wav), "--lang", lang, "--out-dir", str(out_dir)]
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
    events.milestone("Transcription shuru (model load mein 30-60 sec lagte hain)...")
    t0 = time.time()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
    timed_out = {"v": False}

    def killer():
        timed_out["v"] = True
        proc.kill()

    timer = threading.Timer(config.TRANSCRIBE_TIMEOUT, killer)
    timer.start()

    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    buf, tail = "", collections.deque(maxlen=25)
    out_file: str | None = None
    last_pct, last_emit = -1, 0.0
    while True:
        data = proc.stdout.read1(4096)
        if not data:
            break
        buf += decoder.decode(data)
        lines, buf = split_stream(buf)
        for line in lines:
            prog = parse_progress(line)
            if prog:
                pct = int(prog["done_min"] / prog["total_min"] * 100) if prog["total_min"] else 0
                if pct >= last_pct + 10 or time.time() - last_emit > 45:
                    events.milestone(f"Transcript ban raha hai: {prog['done_min']:.0f}/{prog['total_min']:.0f} min "
                                     f"(chunk {prog['chunk']}/{prog['chunks']}), ETA {prog['eta_sec'] // 60} min")
                    last_pct, last_emit = pct, time.time()
                continue
            if line.startswith("Output:"):
                out_file = line.split("Output:", 1)[1].strip()
            tail.append(line)
    proc.wait()
    timer.cancel()
    secs = round(time.time() - t0, 1)

    transcript = Path(out_file) if out_file and Path(out_file).exists() else None
    if transcript is None:
        found = sorted(out_dir.glob(f"{wav.stem}_{lang}_*.txt"))
        transcript = found[-1] if found else None
    text = transcript.read_text(encoding="utf-8", errors="replace") if transcript else ""

    if not text.strip():
        why = "TIMEOUT" if timed_out["v"] else f"exit {proc.returncode}"
        return error(f"transcript nahi bana ({why}). Script ka aakhri output:\n" + "\n".join(tail), seconds=secs)

    info = summarize_transcript(text)
    cpath = config.to_container(transcript)
    base = f"transcript: {cpath}\nlines: {info['lines']}, aakhri timestamp: {info['last_timestamp']}, {secs}s"
    if info["skipped"]:
        base += f"\nDHYAN: {info['skipped']} chunk skip hue (GPU memory kam padi), transcript mein '{SKIP_MARK}' dhundh."
    if timed_out["v"] or proc.returncode != 0:
        why = f"{config.TRANSCRIBE_TIMEOUT}s ka timeout" if timed_out["v"] else f"script exit {proc.returncode}"
        return partial(f"ADHOORA transcript ({why}). Sirf {info['last_timestamp']} tak ka hissa mila.\n{base}\n"
                       "Shardul ko batana ki transcript poora nahi hai.", **info, seconds=secs)

    cache_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(transcript, cached)        # sirf poora transcript cache hota hai
    return ok(base, **info, seconds=secs)
