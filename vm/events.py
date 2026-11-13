"""
Controller se user tak baat karne ka ek hi raasta.
Abhi CLI (print/input). Frontend aane par sirf set_handlers() se badlega.
Logging bhi yahin: workspace/logs/commands.jsonl.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime

import config

_print_lock = threading.Lock()
_handlers = {"milestone": None, "info": None, "confirm": None}


def set_handlers(milestone=None, info=None, confirm=None) -> None:
    _handlers["milestone"] = milestone
    _handlers["info"] = info
    _handlers["confirm"] = confirm


def info(text: str) -> None:
    if _handlers["info"]:
        return _handlers["info"](text)
    with _print_lock:
        print(text, flush=True)


def milestone(text: str) -> None:
    """Chhota progress message ("Transcript le raha hu...")."""
    if _handlers["milestone"]:
        return _handlers["milestone"](text)
    with _print_lock:
        print(f"  >> {text}", flush=True)


def confirm(question: str) -> bool:
    """User se haan/na. Input band ho jaye (EOF) toh na maana jata hai."""
    if _handlers["confirm"]:
        return bool(_handlers["confirm"](question))
    with _print_lock:
        print(f"\n  [permission chahiye] {question}", flush=True)
    while True:
        try:
            ans = input("  haan / na : ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        if ans in {"h", "haan", "ha", "y", "yes"}:
            return True
        if ans in {"n", "na", "nahi", "no"}:
            return False


def log_event(event: dict) -> None:
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    event = {"ts": datetime.now().isoformat(timespec="seconds"), **event}
    with open(config.LOG_DIR / "commands.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
