"""
view_image: koi bhi image ya PDF ka ek page LLM ko dikhao.
PDF page render container ke andar (pdftoppm, Dockerfile mein poppler-utils hai).
Bade images container mein Pillow se chhote kiye jate hain (Pillow baked nahi hai: Dockerfile mein jodna hai).
Tool result mein image nahi ja sakti, isliye queue_image: agent_loop turant ek user message mein jodta hai.
"""
from __future__ import annotations

import posixpath
import re
from pathlib import Path

import config
from .container import docker_exec
from .registry import error, ok, params, queue_image, queued_bytes, register, ToolResult

IMG_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
SMALL_ENOUGH = 1_500_000        # isse chhoti image waise hi bhej do
MAX_SEND = 4_000_000            # base64 ke baad bhi API limit ke andar rahe
PDF_DPI = 110
MAX_STEP_BYTES = 2_000_000      # ek step mein itni images; zyada hui toh model ko ek ek karke dekhne ko bolo

_RENDER = 'mkdir -p "$(dirname "$2")" && pdftoppm -png -r "$3" -f "$4" -l "$4" -singlefile "$1" "$2"'
_SHRINK = (
    "import sys\n"
    "from PIL import Image\n"
    "im = Image.open(sys.argv[1]); im.thumbnail((1600, 1600))\n"
    "im.convert('RGB').save(sys.argv[2], 'JPEG', quality=85)\n"
)


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", s)[:50] or "img"


@register(
    "view_image",
    "Image ya PDF ka ek page khud dekho. path container ka hota hai (/classroom/..., /workspace/...). "
    "PDF ke liye page number do (1 se shuru). Image tere agle message mein dikhegi. "
    "Slides ke diagrams, photos wale notes, aur apne bane diagrams/pages dekhne ke liye.",
    params({"path": {"type": "string"}, "page": {"type": "integer", "description": "sirf PDF ke liye, default 1"}},
           ["path"]),
    milestone="Image dekh raha hu: {path}",
)
def view_image(path: str, page: int = 1) -> ToolResult:
    ext = posixpath.splitext(path)[1].lower()
    view_dir = f"{config.scratch_dir_container()}/_view"
    stem = _slug(posixpath.splitext(posixpath.basename(path))[0])
    caption = path

    if ext == ".pdf":
        page = max(1, int(page))
        prefix = f"{view_dir}/{stem}_p{page}"
        out, code, _, _ = docker_exec(["bash", "-c", _RENDER, "_", path, prefix, str(PDF_DPI), str(page)], timeout=90)
        if code != 0:
            return error("PDF page render fail (page number shayad zyada hai):\n" + out.decode("utf-8", "replace")[-400:], path=path)
        shown = f"{prefix}.png"
        caption = f"{path} page {page}"
    elif ext in IMG_EXT:
        shown = path
    else:
        return error(f"{ext or 'bina extension'} support nahi: sirf PDF aur png/jpg/webp/gif", path=path)

    try:
        host = config.to_host(shown)
    except config.PathError as e:
        return error(str(e), path=path)
    if not host.exists():
        return error(f"file nahi mili: {path}", path=path)

    if host.stat().st_size > SMALL_ENOUGH and ext != ".pdf":
        small = f"{view_dir}/{stem}_small.jpg"
        out, code, _, _ = docker_exec(["bash", "-c", 'mkdir -p "$(dirname "$2")" && python3 -c "$3" "$1" "$2"', "_", shown, small, _SHRINK], timeout=60)
        if code != 0:
            return error("image badi hai aur chhoti nahi kar paya (container mein Pillow chahiye: "
                         "`pip install --user pillow`):\n" + out.decode("utf-8", "replace")[-300:], path=path)
        host = config.to_host(small)

    size = host.stat().st_size
    if size > MAX_SEND:
        return error(f"image bhejne ke liye bahut badi hai ({size // 1024} KB)", path=path)
    
    if queued_bytes() > 0 and queued_bytes() + size > MAX_STEP_BYTES:
        return error("Is step mein itni images pehle hi aa chuki hain. Pehle jo images abhi dikhengi unhe padh ke "
                     "unka text scratch file mein likh de (append_file), phir ye page dobara maang.", path=path)

    queue_image(host, caption)
    return ok(f"image attached: {caption} ({size // 1024} KB). Wo agle message mein dikhegi.", path=path, kb=size // 1024)
