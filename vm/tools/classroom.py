"""
Classroom tools (host side): sync_classroom (sync.py chalana, min-interval ke saath) aur list_materials.
AI ko tokens nahi milte: sync host pe chalta hai.

sync.py abhi purane form mein hai. Ye tool unhi ke saath chal jata hai, par do cheezein sync.py mein badalni hain
(A8): (1) token expire par browser kholne ki jagah exit code 3, (2) classroom/index.json banana.
index.json ke bina list_materials folders scan karta hai (kam jankari: sirf path + modified date).
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

import config
from .registry import error, ok, params, register, ToolResult

EXIT_RELOGIN = 3         # sync.py ko token expire par yahi code dena hai (pending change)
MAX_ROWS = 80


def _state_path() -> Path:
    return config.CACHE_DIR / "sync_last.json"


def _read_last_sync() -> float:
    try:
        return float(json.loads(_state_path().read_text(encoding="utf-8")).get("ts", 0))
    except (OSError, ValueError):
        return 0.0


def _write_last_sync(ts: float) -> None:
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _state_path().write_text(json.dumps({"ts": ts}), encoding="utf-8")


def filter_sync_output(text: str, keep: int = 60) -> str:
    """'pehle se hai' wali lines hata do (sirf naya/update dikhao)."""
    lines = [l for l in text.splitlines() if l.strip() and "pehle se hai" not in l]
    if len(lines) > keep:
        lines = [f"...({len(lines) - keep} purani lines hatayi)"] + lines[-keep:]
    return "\n".join(lines)


@register(
    "sync_classroom",
    "Google Classroom se naya material/assignments le aao (sync.py chalta hai). Har session mein ek baar kaafi hai: "
    "pichle sync ke 30 min ke andar dobara chalane par skip ho jata hai (force=true se zabardasti).",
    params({"force": {"type": "boolean"}}),
    milestone="Classroom sync ho raha hai...",
)
def sync_classroom(force: bool = False) -> ToolResult:
    age_min = (time.time() - _read_last_sync()) / 60
    if not force and age_min < config.SYNC_MIN_INTERVAL_MIN:
        return ok(f"SKIP: {age_min:.0f} min pehle hi sync hua tha (min interval {config.SYNC_MIN_INTERVAL_MIN} min). "
                  "Material list ke liye list_materials chala.", skipped=True)
    script = Path(config.SYNC_SCRIPT)
    if not script.exists():
        return error(f"sync.py nahi mili: {script}")

    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", "SYNC_NON_INTERACTIVE": "1"}
    t0 = time.time()
    try:
        r = subprocess.run([config.SYNC_PYTHON, "-u", str(script), "--non-interactive"], cwd=config.SYNC_CWD,
                           capture_output=True, env=env, timeout=config.SYNC_TIMEOUT)
    except subprocess.TimeoutExpired:
        return error(f"sync {config.SYNC_TIMEOUT}s mein khatam nahi hua, kill kiya. Shayad token expire hai aur "
                     "login ke liye browser khula hai: Shardul ko bol ki terminal mein `python sync.py` khud chalaye.")
    secs = round(time.time() - t0, 1)
    out = (r.stdout + r.stderr).decode("utf-8", errors="replace")

    if r.returncode == EXIT_RELOGIN:
        return error("Google token expire ho gaya. Shardul ko bol ki terminal mein `python sync.py` khud chalaye (browser login).")
    if r.returncode != 0:
        return error(f"sync fail (exit {r.returncode}):\n{filter_sync_output(out, 25)}", exit_code=r.returncode)
    _write_last_sync(time.time())
    return ok(f"sync complete ({secs}s). Naya/update:\n{filter_sync_output(out) or '(kuch naya nahi)'}", seconds=secs)


# ---------- list_materials ----------
def parse_index(raw: str) -> list[dict]:
    """index.json: list of {course, title, posted, path, kind}; path classroom/ ke relative ya /classroom/... ho sakta hai."""
    data = json.loads(raw)
    rows = data.get("items", data) if isinstance(data, dict) else data
    out = []
    for x in rows:
        if not isinstance(x, dict) or not x.get("path"):
            continue
        path = str(x["path"]).replace("\\", "/")
        if not path.startswith(config.CONTAINER_CLASSROOM + "/"):
            path = f"{config.CONTAINER_CLASSROOM}/{path.lstrip('/')}"
        out.append({"course": x.get("course", ""), "title": x.get("title", ""),
                    "posted": x.get("posted", ""), "kind": x.get("kind", ""), "path": path})
    return out


def scan_folders() -> list[dict]:
    """index.json na ho toh: classroom/<course>/{materials,assignments}/... ki files."""
    root = Path(config.CLASSROOM_HOST)
    rows = []
    if not root.exists():
        return rows
    for p in root.rglob("*"):
        if not p.is_file() or p.name in {"STATUS.md", "index.json"}:
            continue
        rel = p.relative_to(root)
        if len(rel.parts) < 3:
            continue
        kind = {"materials": "material", "assignments": "assignment"}.get(rel.parts[1], "")
        rows.append({"course": rel.parts[0], "title": p.name, "kind": kind,
                     "posted": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d"),
                     "path": f"{config.CONTAINER_CLASSROOM}/{rel.as_posix()}"})
    return rows


def filter_rows(rows: list[dict], query: str = "", course: str = "") -> list[dict]:
    words = query.lower().split()
    out = []
    for r in rows:
        hay = " ".join(str(v) for v in r.values()).lower()
        if course and course.lower() not in r["course"].lower():
            continue
        if all(w in hay for w in words):
            out.append(r)
    return sorted(out, key=lambda r: r.get("posted", ""), reverse=True)


@register(
    "list_materials",
    "Classroom ke material/assignment files ki list (course, title, date, exact path). query se topic dhoondh "
    "(jaise 'pointers' ya 'unit 3'), course se subject filter. Path /classroom/... hota hai; padhne ke liye read_file / view_image.",
    params({"query": {"type": "string"}, "course": {"type": "string"}}),
)
def list_materials(query: str = "", course: str = "") -> ToolResult:
    index = Path(config.CLASSROOM_HOST) / "index.json"
    source = "scan"
    try:
        if index.exists():
            rows, source = parse_index(index.read_text(encoding="utf-8")), "index.json"
        else:
            rows = scan_folders()
    except (OSError, ValueError) as e:
        return error(f"index.json padh nahi paya: {e}")
    rows = filter_rows(rows, query, course)
    if not rows:
        return ok("kuch nahi mila. query chhoti/alag karke dekh, ya course badal.", n=0)
    shown = rows[:MAX_ROWS]
    lines = [f"{r['posted']} | {r['course']} | {r['kind']} | {r['title']} | {r['path']}" for r in shown]
    note = f"\n(+{len(rows) - MAX_ROWS} aur hain, query narrow kar)" if len(rows) > MAX_ROWS else ""
    src = "" if source == "index.json" else "(index.json nahi hai: sirf folder scan, post ka title nahi milta)\n"
    return ok(src + "\n".join(lines) + note, n=len(rows), source=source)
