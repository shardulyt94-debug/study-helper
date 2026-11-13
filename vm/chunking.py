"""
Har jagah ka ek hi chunking function (read_file, fetch_page, tool output, ...).

Rules:
- Limit CHARACTERS mein (words mein nahi: Hinglish/Devanagari ke tokens alag hote hain).
- CHUNK_CHARS ka 90% effective limit: file thodi si bhi limit ke neeche ho toh POORI jati hai.
- Badi file ho toh blank-line / page-break pe kaatte hain, nahi mile toh line pe,
  line hi limit se badi ho toh hard-split.
- Har chunk pe label "[part 2/5, lines 120-240]" aur end mein agle part ka hint.
- Server stateless: LLM part number bhejta hai.
"""
from __future__ import annotations

from dataclasses import dataclass

CHUNK_CHARS = 12000
MARGIN = 0.90


@dataclass
class Chunk:
    text: str
    first_line: int
    last_line: int


def effective_limit(max_chars: int = CHUNK_CHARS) -> int:
    return max(1, int(max_chars * MARGIN))


def _is_boundary(piece_text: str) -> bool:
    return piece_text.strip() == "" or "\f" in piece_text


def _best_break(cur: list, limit: int) -> int:
    """cur ke kitne pieces rakhne hain. Paragraph/page boundary jo kam se kam aadhe limit pe ho."""
    total = 0
    sizes = []
    for _, t in cur:
        total += len(t)
        sizes.append(total)
    for i in range(len(cur), 0, -1):
        if sizes[i - 1] >= limit * 0.5 and _is_boundary(cur[i - 1][1]):
            return i
    return len(cur)


def _make(pieces: list) -> Chunk:
    return Chunk("".join(t for _, t in pieces), pieces[0][0], pieces[-1][0])


def split_text(text: str, max_chars: int = CHUNK_CHARS) -> list[Chunk]:
    if not text:
        return []
    limit = effective_limit(max_chars)

    pieces = []  # (original line number, text)
    for lineno, line in enumerate(text.splitlines(keepends=True), 1):
        if len(line) <= limit:
            pieces.append((lineno, line))
        else:
            for k in range(0, len(line), limit):
                pieces.append((lineno, line[k:k + limit]))

    chunks: list[Chunk] = []
    cur: list = []
    size = 0
    for piece in pieces:
        while cur and size + len(piece[1]) > limit:
            keep = _best_break(cur, limit)
            chunks.append(_make(cur[:keep]))
            cur = cur[keep:]
            size = sum(len(t) for _, t in cur)
        cur.append(piece)
        size += len(piece[1])
    if cur:
        chunks.append(_make(cur))
    return chunks


def render_part(chunks: list[Chunk], part: int = 1) -> str:
    n = len(chunks)
    if n == 0:
        return "(khali)"
    if n == 1:
        return chunks[0].text            # poori file, koi label nahi
    try:
        part = int(part)
    except (TypeError, ValueError):
        part = 1
    if not 1 <= part <= n:
        return f"[part={part} nahi hai. Total {n} parts hain, 1 se {n} ke beech maang.]"
    c = chunks[part - 1]
    body = c.text if c.text.endswith("\n") else c.text + "\n"
    head = f"[part {part}/{n}, lines {c.first_line}-{c.last_line}]\n"
    tail = f"[aage padhne ke liye part={part + 1} bhej]" if part < n else "[ye aakhri part hai]"
    return head + body + tail


def get_part(text: str, part: int = 1, max_chars: int = CHUNK_CHARS) -> tuple[str, int]:
    """(rendered text, total parts)."""
    chunks = split_text(text, max_chars)
    return render_part(chunks, part), len(chunks)


def shorten_head_tail(text: str, max_chars: int, saved_path: str = "") -> str:
    """Bahut bada output: shuru + end dikhao, beech kaato."""
    if len(text) <= max_chars:
        return text
    half = max_chars // 2
    where = f" Poora yahan hai: {saved_path}" if saved_path else ""
    return text[:half] + f"\n...[beech ka hissa kaata gaya.{where}]...\n" + text[-half:]
