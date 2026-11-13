"""
Tool registry: har tool ki schema + function + confirmation rule EK jagah.
(Pehle TOOLS aur TOOL_FUNCS alag lists the, drift hota.)

Result ka ek jaisa format: pehli line hamesha
    STATUS: ok | error | partial | denied
phir details. Isse constitution mein failure-handling ek baar likhni padti hai.
"""
from __future__ import annotations

import base64
import inspect
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import chunking
import events

FINAL_CAP_CHARS = 15000   # koi bhi tool result isse bada model ko nahi jayega


# ---------- Result helpers ----------
@dataclass
class ToolResult:
    text: str
    meta: dict = field(default_factory=dict)


def _result(status: str, text: str, meta: dict) -> ToolResult:
    return ToolResult(f"STATUS: {status}\n{text}".rstrip(), {"status": status, **meta})


def ok(text: str = "", **meta) -> ToolResult:
    return _result("ok", text, meta)


def error(text: str, **meta) -> ToolResult:
    return _result("error", text, meta)


def partial(text: str, **meta) -> ToolResult:
    return _result("partial", text, meta)


def denied(text: str, **meta) -> ToolResult:
    return _result("denied", text, meta)


# ---------- Registry ----------
@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    func: Callable
    requires_confirmation: bool = False
    confirm_text: Callable[[dict], str] | None = None
    milestone: str | None = None        # jaise "Web pe dhoondh raha hu: {query}"


REGISTRY: dict[str, Tool] = {}


def params(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": properties, "required": required or []}


def register(name: str, description: str, parameters: dict, *,
             requires_confirmation: bool = False,
             confirm_text: Callable[[dict], str] | None = None,
             milestone: str | None = None):
    def deco(func):
        REGISTRY[name] = Tool(name, description, parameters, func,
                              requires_confirmation, confirm_text, milestone)
        return func
    return deco


def schemas() -> list[dict]:
    """Chat-completions format mein tools ki list."""
    return [{"type": "function",
             "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
            for t in REGISTRY.values()]


# ---------- Image queue ----------
# Tool result mein image nahi ja sakti (chat/completions format). Tool image queue mein daalta hai,
# agent_loop tool results ke turant baad `drain_image_message()` se ek user message banata hai.
_pending_images: list[tuple[Path, str]] = []

_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".webp": "image/webp", ".gif": "image/gif"}


def queue_image(host_path: Path, caption: str = "") -> None:
    _pending_images.append((Path(host_path), caption))
    
    
def queued_bytes() -> int:
    """Is step mein abhi tak queue mein kitne bytes ki images hain."""
    return sum(p.stat().st_size for p, _ in _pending_images)


def drain_image_message() -> dict | None:
    if not _pending_images:
        return None
    parts: list[dict] = []
    while _pending_images:
        path, caption = _pending_images.pop(0)
        mime = _MIME.get(path.suffix.lower(), "image/png")
        b64 = base64.b64encode(path.read_bytes()).decode("ascii")
        parts.append({"type": "text", "text": f"[image: {caption or path.name}]"})
        parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
    return {"role": "user", "content": parts}


# ---------- Run ----------
def _preview_args(args: dict) -> dict:
    out = {}
    for k, v in args.items():
        out[k] = v[:200] + "..." if isinstance(v, str) and len(v) > 200 else v
    return out


def _format_milestone(template: str, args: dict) -> str:
    try:
        return template.format(**{k: str(v)[:80] for k, v in args.items()})
    except (KeyError, IndexError, ValueError):
        return template


def run_tool(name: str, arguments: str | dict | None) -> str:
    """Model ka tool call chalao. Hamesha string wapas (crash nahi)."""
    t0 = time.time()
    tool = REGISTRY.get(name)
    args: dict[str, Any] = {}
    res: ToolResult

    if tool is None:
        res = error(f"unknown tool {name!r}. Available: {', '.join(REGISTRY)}")
    else:
        try:
            parsed = arguments if isinstance(arguments, dict) else json.loads(arguments or "{}")
            if not isinstance(parsed, dict):
                raise ValueError("arguments object hona chahiye")
            args = parsed
        except (json.JSONDecodeError, ValueError) as e:
            res = error(f"arguments valid JSON nahi the ({e}). Dobara sahi JSON bhej. "
                        "Agar content bahut bada tha toh use chhote parts mein bhej (append_file).")
        else:
            res = _call(tool, args)

    text = res.text
    if len(text) > FINAL_CAP_CHARS:
        text = chunking.shorten_head_tail(text, FINAL_CAP_CHARS)
    events.log_event({"tool": name, "args": _preview_args(args),
                      "seconds": round(time.time() - t0, 1),
                      "status": res.meta.get("status"), **{k: v for k, v in res.meta.items() if k != "status"}})
    return text


def _call(tool: Tool, args: dict) -> ToolResult:
    try:
        inspect.signature(tool.func).bind(**args)
    except TypeError as e:
        sig = ", ".join(inspect.signature(tool.func).parameters)
        return error(f"arguments galat: {e}. {tool.name} ke parameters: {sig}")

    if tool.requires_confirmation:
        question = tool.confirm_text(args) if tool.confirm_text else f"{tool.name} chalane doon? {args}"
        if not events.confirm(question):
            return denied("User ne mana kar diya. Wahi cheez dobara mat pooch; kaam aage badha.")

    if tool.milestone:
        events.milestone(_format_milestone(tool.milestone, args))

    try:
        out = tool.func(**args)
    except Exception as e:  # tool ka crash model ko dikhao, controller girne mat do
        return error(f"tool crash: {type(e).__name__}: {e}", crashed=True)

    if isinstance(out, ToolResult):
        return out
    out = str(out)
    return ToolResult(out if out.startswith("STATUS:") else f"STATUS: ok\n{out}", {"status": "ok"})
