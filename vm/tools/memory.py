"""
Long-term memory (abhi simple): memory/profile.md aur memory/lessons.md host pe.
Container ko ye files nahi dikhti (warna LLM confirmation bypass kar dega).
LLM sirf propose_memory_update bol sakta hai; likhta controller hai, user ke haan ke baad.
"""
from __future__ import annotations

import re
from datetime import date

import config
from .registry import denied, error, ok, params, register, ToolResult  # noqa: F401

ALLOWED_FILES = ("profile.md", "lessons.md")
MAX_LEN = 300


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def read_memory_text() -> str:
    """session.py pehle message banate waqt yeh use karega."""
    parts = []
    for name in ALLOWED_FILES:
        p = config.MEMORY_DIR / name
        if p.exists():
            body = p.read_text(encoding="utf-8").strip()
            if body:
                parts.append(f"## {name}\n{body}")
    return "\n\n".join(parts)


def append_memory(file: str, text: str) -> str:
    """Seedha likhta hai. Confirmation registry ne pehle hi le li hoti hai. Returns line."""
    config.MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    path = config.MEMORY_DIR / file
    line = f"- ({date.today().isoformat()}) {_clean(text)}"
    existing = path.read_text(encoding="utf-8") if path.exists() else f"# {file}\n"
    if _clean(text) in existing:
        return ""            # pehle se hai
    if not existing.endswith("\n"):
        existing += "\n"
    path.write_text(existing + line + "\n", encoding="utf-8")
    return line


def _confirm_text(args: dict) -> str:
    return (f"Memory mein save karun?\n    file: {args.get('file')}\n"
            f"    line: {_clean(str(args.get('text', '')))}")


@register(
    "propose_memory_update",
    "Shardul ne kuch yaad rakhne layak bola ho (padhne ka tareeka, pasand, galti jo repeat nahi honi chahiye) "
    "toh yahan propose kar. Ye seedha save nahi hota: Shardul ko exact line dikhegi, haan bole tab hi save. "
    "file: 'profile.md' (Shardul ke baare mein) ya 'lessons.md' (kaam ke tareeke ki seekh). "
    "text: ek chhoti line.",
    params({"file": {"type": "string", "enum": list(ALLOWED_FILES)}, "text": {"type": "string"}},
           ["file", "text"]),
    requires_confirmation=True,
    confirm_text=_confirm_text,
)
def propose_memory_update(file: str, text: str) -> ToolResult:
    if file not in ALLOWED_FILES:
        return error(f"file sirf {', '.join(ALLOWED_FILES)} mein se ho sakti hai")
    clean = _clean(text)
    if not clean:
        return error("text khali hai")
    if len(clean) > MAX_LEN:
        return error(f"line {MAX_LEN} characters se chhoti rakh (abhi {len(clean)})")
    line = append_memory(file, clean)
    if not line:
        return ok("ye line pehle se memory mein thi", file=file)
    return ok(f"save ho gaya: {file}", file=file)
