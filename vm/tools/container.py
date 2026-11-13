"""
Container ke andar kaam: run_command, read_file (chunked), write_file, append_file, edit_file.
Sab `docker exec` se. Yahi `docker_exec` baaki tools (vision) bhi use karte hain.
"""
from __future__ import annotations

import json
import subprocess
import threading
import time
from datetime import datetime

import chunking
import config
from .registry import error, ok, params, register, ToolResult


# ---------- docker exec ----------
def docker_exec(args, stdin_data: bytes | None = None, timeout: int = config.DEFAULT_TIMEOUT):
    """Returns (output_bytes, returncode, hard_killed, capped)."""
    full = ["docker", "exec", "-i", "-w", config.CONTAINER_WORKSPACE, config.CONTAINER] + list(args)
    proc = subprocess.Popen(full, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    killed = {"v": False}

    def killer():  # safety net: andar ka `timeout` pehle kaam karta hai
        killed["v"] = True
        proc.kill()

    timer = threading.Timer(timeout + 15, killer)
    timer.start()
    try:
        if stdin_data:
            proc.stdin.write(stdin_data)
        proc.stdin.close()
    except OSError:
        pass

    chunks, total, capped = [], 0, False
    while True:
        data = proc.stdout.read1(65536)
        if not data:
            break
        if total + len(data) > config.OUTPUT_CAP_BYTES:
            chunks.append(data[: config.OUTPUT_CAP_BYTES - total])
            capped = True
            proc.kill()
            break
        chunks.append(data)
        total += len(data)
    proc.wait()
    timer.cancel()
    return b"".join(chunks), proc.returncode, killed["v"], capped


# ---------- run_command ----------
@register(
    "run_command",
    "Container ke andar bash command chalao (working dir /workspace). Internet aur sudo available hai. "
    "Lamba kaam ho toh background mein chala (nohup ... &) aur log se check kar.",
    params({"command": {"type": "string"},
            "timeout_seconds": {"type": "integer", "description": "default 120, max 900"}},
           ["command"]),
)
def run_command(command: str, timeout_seconds: int = config.DEFAULT_TIMEOUT) -> ToolResult:
    timeout = max(1, min(int(timeout_seconds), config.MAX_TIMEOUT))
    t0 = time.time()
    out, code, hard_killed, capped = docker_exec(
        ["timeout", "-k", "5", str(timeout), "bash", "-lc", command], timeout=timeout)
    dur = round(time.time() - t0, 1)
    text = out.decode("utf-8", errors="replace")

    saved = ""
    if len(text) > config.MODEL_VIEW_CHARS:
        config.BIG_OUT_DIR.mkdir(parents=True, exist_ok=True)
        fname = datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".txt"
        (config.BIG_OUT_DIR / fname).write_bytes(out)
        saved = f"/workspace/logs/outputs/{fname}"

    flags = []
    if code == 124:
        flags.append(f"TIMEOUT: {timeout}s mein khatam nahi hua, kill kiya gaya")
    if hard_killed:
        flags.append("HARD-KILLED by controller")
    if capped:
        flags.append(f"OUTPUT CAP: {config.OUTPUT_CAP_BYTES // (1024 * 1024)} MB se bada tha, kaat diya gaya")
    if code == 137:
        flags.append("exit 137: process kill hua (shayad RAM limit 10 GB cross hui)")

    header = f"[exit code: {code}, {dur}s]" + "".join(f"\n[{f}]" for f in flags)
    body = header + "\n" + chunking.shorten_head_tail(text, config.MODEL_VIEW_CHARS, saved)
    meta = {"command": command, "exit_code": code, "output_bytes": len(out),
            "flags": flags, "output_file": saved}
    return ok(body, **meta) if code == 0 else error(body, **meta)


# ---------- read_file ----------
@register(
    "read_file",
    "Container ki text file padho (absolute path, jaise /classroom/...). Chhoti file poori aati hai. "
    "Badi file parts mein aati hai; end mein likha hota hai kaunsa part=N agla hai.",
    params({"path": {"type": "string"},
            "part": {"type": "integer", "description": "badi file ka part number, default 1"}},
           ["path"]),
)
def read_file(path: str, part: int = 1) -> ToolResult:
    out, code, _, _ = docker_exec(["head", "-c", str(config.READ_MAX_BYTES), path], timeout=60)
    if code != 0:
        return error(out.decode("utf-8", errors="replace"), path=path, exit_code=code)
    if b"\x00" in out[:8192]:
        return error("ye binary file lag rahi hai (text nahi). PDF/image ke liye alag tool use kar "
                     "(pdftotext via run_command, ya view_image).", path=path)
    text = out.decode("utf-8", errors="replace")
    rendered, total = chunking.get_part(text, part)
    if len(out) >= config.READ_MAX_BYTES:
        rendered += f"\n[file {config.READ_MAX_BYTES // (1024 * 1024)} MB pe kaat di gayi thi]"
    return ok(rendered, path=path, part=part, total_parts=total)


# ---------- write / append ----------
_WRITE = 'mkdir -p "$(dirname "$1")" && cat > "$1"'
_APPEND = 'mkdir -p "$(dirname "$1")" && cat >> "$1"'


def _put(script: str, path: str, content: str) -> tuple[int, str]:
    out, code, _, _ = docker_exec(["bash", "-c", script, "_", path],
                                  stdin_data=content.encode("utf-8"), timeout=30)
    return code, out.decode("utf-8", errors="replace")


@register(
    "write_file",
    "Container mein file likho (poori file overwrite hoti hai, folder apne aap banta hai). "
    "Badi file ek call mein mat bhej: pehle write_file se shuruaat, phir append_file se sections.",
    params({"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]),
)
def write_file(path: str, content: str) -> ToolResult:
    code, msg = _put(_WRITE, path, content)
    n = len(content.encode("utf-8"))
    if code != 0:
        return error(msg, path=path, exit_code=code)
    return ok(f"{len(content)} chars likhe gaye -> {path}", path=path, bytes=n)


@register(
    "append_file",
    "File ke end mein text jodo (file na ho toh ban jati hai). Section-by-section likhne ke liye. "
    "Sections ke beech khali line (\\n\\n) khud daal.",
    params({"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]),
)
def append_file(path: str, content: str) -> ToolResult:
    code, msg = _put(_APPEND, path, content)
    n = len(content.encode("utf-8"))
    if code != 0:
        return error(msg, path=path, exit_code=code)
    return ok(f"{len(content)} chars jode gaye -> {path}", path=path, bytes=n)


# ---------- edit_file ----------
# Ye script container ke andar python3 mein chalti hai. Messages jaanbujh ke ASCII hain.
EDIT_SCRIPT = r'''
import json, sys
req = json.load(sys.stdin)
p, old, new, allr = req["path"], req["old"], req["new"], req.get("all", False)
if old == "":
    print("old_text khali nahi ho sakta"); sys.exit(6)
try:
    with open(p, encoding="utf-8", newline="") as f:
        s = f.read()
except FileNotFoundError:
    print("file nahi mili: " + p); sys.exit(4)
except UnicodeDecodeError:
    print("file utf-8 text nahi hai"); sys.exit(5)
n = s.count(old)
if n == 0:
    print("old_text file mein nahi mila. read_file se dekh ke exact text (spaces/newlines samet) de."); sys.exit(2)
if n > 1 and not allr:
    print("old_text %d jagah mila. Aas-paas ka text jod ke unique bana, ya replace_all=true de." % n); sys.exit(3)
with open(p, "w", encoding="utf-8", newline="") as f:
    f.write(s.replace(old, new))
print("OK %d jagah badla" % n)
'''


@register(
    "edit_file",
    "File mein text replace karo. old_text file mein exactly ek jagah hona chahiye "
    "(ya replace_all=true). Chhote badlav ke liye poori file dobara likhne se behtar.",
    params({"path": {"type": "string"}, "old_text": {"type": "string"},
            "new_text": {"type": "string"}, "replace_all": {"type": "boolean"}},
           ["path", "old_text", "new_text"]),
)
def edit_file(path: str, old_text: str, new_text: str, replace_all: bool = False) -> ToolResult:
    req = json.dumps({"path": path, "old": old_text, "new": new_text, "all": replace_all})
    out, code, _, _ = docker_exec(["python3", "-c", EDIT_SCRIPT], stdin_data=req.encode("utf-8"), timeout=30)
    msg = out.decode("utf-8", errors="replace").strip()
    if code != 0:
        return error(msg, path=path, exit_code=code)
    return ok(f"{msg} -> {path}", path=path)
