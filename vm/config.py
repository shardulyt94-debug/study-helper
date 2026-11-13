"""
Ek jagah saari settings: .env, paths, host <-> container path mapping, session id.

Rule: baaki files `import config` karke `config.X` use karein (from config import X nahi),
taaki tests mein values badli ja sakein.
"""
from __future__ import annotations

import os
import posixpath
import re
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent          # D:\classroom-test\vm
PROJECT_ROOT = HERE.parent                      # D:\classroom-test


def load_env(path: Path) -> None:
    """.env padho. Shell mein pehle se set variables ko override nahi karta."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env(HERE / ".env")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


# ---------- API / model ----------
CONTAINER = _env("CONTAINER_NAME", "study-agent-box")
BASE_URL = _env("AICREDITS_BASE_URL").rstrip("/")
API_KEY = _env("AICREDITS_API_KEY")
TAVILY_KEY = _env("TAVILY_API_KEY")
# NOTE: Sonnet 5.5 ka exact aicredits string verify nahi hua. .env mein AGENT_MODEL set kar.
MODEL = _env("AGENT_MODEL", "anthropic/claude-haiku-5.5")
MAX_TOKENS = _env_int("AGENT_MAX_TOKENS", 16000)
MAX_STEPS = _env_int("AGENT_MAX_STEPS", 120)

# ---------- Limits ----------
DEFAULT_TIMEOUT = 120                 # run_command default (seconds)
MAX_TIMEOUT = 900
OUTPUT_CAP_BYTES = 100 * 1024 * 1024  # container command output ka hard cap
MODEL_VIEW_CHARS = 12000              # tool output model ko itna hi
READ_MAX_BYTES = 20 * 1024 * 1024     # read_file ek file se itna hi padhega
TRANSCRIBE_TIMEOUT = _env_int("TRANSCRIBE_TIMEOUT", 480)   # ~8 min, model load bhi isme
SYNC_TIMEOUT = _env_int("SYNC_TIMEOUT", 600)
SYNC_MIN_INTERVAL_MIN = _env_int("SYNC_MIN_INTERVAL_MIN", 30)

# ---------- Host paths ----------
WORKSPACE_HOST = Path(_env("WORKSPACE_HOST", str(PROJECT_ROOT / "workspace")))
CLASSROOM_HOST = Path(_env("CLASSROOM_HOST", str(PROJECT_ROOT / "classroom")))
LOG_DIR = WORKSPACE_HOST / "logs"
BIG_OUT_DIR = LOG_DIR / "outputs"
CACHE_DIR = WORKSPACE_HOST / "cache"
UPLOADS_HOST = WORKSPACE_HOST / "uploads"
MEMORY_DIR = HERE / "memory"          # profile.md, lessons.md: container ko nahi dikhte
CONSTITUTION_DIR = HERE / "constitution"
CONSTITUTION_PATH = CONSTITUTION_DIR / "CONSTITUTION.md"

# ---------- Host-side tools ke settings (.env mein) ----------
FFMPEG = _env("FFMPEG", "ffmpeg")                         # host pe chahiye (verify nahi kiya)
TRANSCRIBE_PYTHON = _env("TRANSCRIBE_PYTHON")             # model folder ke env ka python.exe
TRANSCRIBE_SCRIPT = _env("TRANSCRIBE_SCRIPT")             # .../transcribe_lecture.py
SYNC_PYTHON = _env("SYNC_PYTHON", sys.executable)         # google libs wala python
SYNC_SCRIPT = _env("SYNC_SCRIPT", str(PROJECT_ROOT / "sync.py"))
SYNC_CWD = _env("SYNC_CWD", str(PROJECT_ROOT))            # token.json, classroom/ yahin se relative

# ---------- Container paths ----------
CONTAINER_WORKSPACE = "/workspace"
CONTAINER_CLASSROOM = "/classroom"


# ---------- Host <-> container path mapping ----------
class PathError(ValueError):
    pass


def _mappings():
    return [(CONTAINER_WORKSPACE, Path(WORKSPACE_HOST)), (CONTAINER_CLASSROOM, Path(CLASSROOM_HOST))]


def to_host(container_path: str) -> Path:
    """'/workspace/uploads/a.png' -> host ka asli path. '..' se bahar nikalna reject."""
    p = str(container_path).replace("\\", "/").strip()
    if not p:
        raise PathError("path khali hai")
    if not p.startswith("/"):
        p = CONTAINER_WORKSPACE + "/" + p          # container ka cwd /workspace hai
    p = posixpath.normpath(p)
    for root, host in _mappings():
        if p == root or p.startswith(root + "/"):
            rel = p[len(root):].lstrip("/")
            return host / rel if rel else host
    raise PathError(f"{container_path!r} /workspace ya /classroom ke andar nahi hai")


def to_container(host_path) -> str:
    hp = Path(os.path.abspath(host_path))
    for root, host in _mappings():
        try:
            rel = hp.relative_to(Path(os.path.abspath(host)))
        except ValueError:
            continue
        rel_posix = rel.as_posix()
        return root if rel_posix == "." else f"{root}/{rel_posix}"
    raise PathError(f"{host_path} workspace/classroom ke andar nahi hai")


# ---------- Session ----------
_session = {"id": "default"}


def _clean_id(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_.-]", "_", s).replace("..", "_").lstrip(".")
    return s[:60] or "default"


def new_session_id() -> str:
    sid = datetime.now().strftime("%Y%m%d-%H%M%S")
    _session["id"] = sid
    return sid


def set_session_id(sid: str) -> None:
    _session["id"] = _clean_id(sid)


def session_id() -> str:
    return _session["id"]


def scratch_dir_container(sid: str | None = None) -> str:
    return f"{CONTAINER_WORKSPACE}/scratch/{_clean_id(sid or session_id())}"


def scratch_dir_host(sid: str | None = None) -> Path:
    return to_host(scratch_dir_container(sid))
