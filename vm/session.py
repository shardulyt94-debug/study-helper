"""
Session: ek chat ka poora haal. Messages memory mein bhi, disk pe bhi (messages.jsonl).

Yahin ye bhi hai:
  - system prompt banana (constitution + mode ka playbook)
  - user ka message banana (prompt + profile.md + lessons.md + photos + audio path)
  - photos ko API ke layak banana (EXIF rotation, resize)

Disk pe log: workspace/sessions/<id>/messages.jsonl  (images ki jagah "[image omitted]" likha jata hai)
"""
from __future__ import annotations

import base64
import copy
import io
import json
import shutil
import time
from datetime import datetime
from pathlib import Path

import config

try:  # Pillow host pe ho toh photos chhoti/seedhi kar paate hain (pip install pillow)
    from PIL import Image, ImageOps
except ImportError:  # pragma: no cover
    Image = ImageOps = None

IMG_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".webp": "image/webp", ".gif": "image/gif"}
AUDIO_EXT = {".mp3", ".m4a", ".wav", ".aac", ".ogg", ".opus", ".flac", ".mp4", ".mkv", ".webm", ".mov"}
RESIZE_SIDE = 2000            # lambi side isse badi ho toh chhoti (haath ke likhe notes padhne layak)
KEEP_RAW_BYTES = 1_500_000    # chhoti png/webp/gif seedhi bhej do
MAX_RAW_BYTES = 3_500_000     # Pillow na ho toh isse badi photo reject
MAX_SEND_BYTES = 4_000_000    # resize ke baad bhi isse badi ho toh reject


# ---------------------------------------------------------------- images
def image_to_part(src: Path) -> tuple[dict | None, str]:
    """Image file -> API ka image_url part. Fail hone par (None, wajah)."""
    src = Path(src)
    ext = src.suffix.lower()
    if ext not in IMG_MIME:
        return None, f"{src.name}: {ext or 'bina extension'} support nahi (png/jpg/webp/gif hi). HEIC ho toh JPG mein convert kar."
    if not src.exists():
        return None, f"{src} nahi mili"

    size = src.stat().st_size
    mime = IMG_MIME[ext]
    data: bytes | None = None

    if Image is not None:
        try:
            im = ImageOps.exif_transpose(Image.open(src))   # phone photo ki rotation theek
            small_enough = max(im.size) <= RESIZE_SIDE
            if ext in {".png", ".webp", ".gif"} and size <= KEEP_RAW_BYTES and small_enough:
                data = src.read_bytes()
            else:
                im.thumbnail((RESIZE_SIDE, RESIZE_SIDE))
                buf = io.BytesIO()
                im.convert("RGB").save(buf, "JPEG", quality=88)
                data, mime = buf.getvalue(), "image/jpeg"
        except Exception as e:  # noqa: BLE001
            data = None
            print(f"  [warning] {src.name}: Pillow se process nahi hui ({e}), seedhi bhejne ki koshish")

    if data is None:
        if size > MAX_RAW_BYTES:
            return None, (f"{src.name} badi hai ({size // 1024} KB) aur host pe Pillow nahi hai. "
                          "`pip install pillow` kar, phir dobara try kar.")
        data = src.read_bytes()

    if len(data) > MAX_SEND_BYTES:
        return None, f"{src.name} resize ke baad bhi badi hai ({len(data) // 1024} KB)"

    b64 = base64.b64encode(data).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}, ""


def _loggable(msg: dict) -> dict:
    """Disk pe log karne ke liye base64 images hata do."""
    m = copy.deepcopy(msg)
    if isinstance(m.get("content"), list):
        m["content"] = [{"type": "text", "text": "[image omitted from log]"} if p.get("type") == "image_url" else p
                        for p in m["content"]]
    return m


# ---------------------------------------------------------------- prompts
def _read_optional(path: Path, empty: str) -> str:
    try:
        text = path.read_text(encoding="utf-8").strip()
        return text or empty
    except OSError:
        return empty


def build_system_prompt(mode: str) -> str:
    text = config.CONSTITUTION_PATH.read_text(encoding="utf-8")
    playbook = config.CONSTITUTION_DIR / "playbooks" / f"{mode}.md"
    if playbook.exists():
        text += f"\n\n---\n# Playbook: {mode}\n\n" + playbook.read_text(encoding="utf-8")
    return text


class Session:
    def __init__(self, sid: str, mode: str, messages: list[dict] | None = None):
        self.id = sid
        self.mode = mode
        self.dir = config.WORKSPACE_HOST / "sessions" / sid
        self.log_path = self.dir / "messages.jsonl"
        self.upload_dir = config.UPLOADS_HOST / sid
        self.started = time.time()
        self.messages: list[dict] = messages or []
        self.inspects: list[tuple[float, str]] = []     # (kab, args) har kamyab inspect_document call
        self.dir.mkdir(parents=True, exist_ok=True)
        config.scratch_dir_host(sid).mkdir(parents=True, exist_ok=True)

    # ---- bananaa / wapas laana
    @classmethod
    def new(cls, mode: str) -> "Session":
        sid = config.new_session_id()
        s = cls(sid, mode)
        s._write({"event": "session_start", "mode": mode, "model": config.MODEL})
        s.add({"role": "system", "content": build_system_prompt(mode)})
        return s

    @classmethod
    def load(cls, sid: str) -> "Session":
        config.set_session_id(sid)
        sid = config.session_id()
        path = config.WORKSPACE_HOST / "sessions" / sid / "messages.jsonl"
        if not path.exists():
            raise FileNotFoundError(f"session nahi mila: {path}")
        mode, msgs = "notes", []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("event") == "session_start":
                mode = rec.get("mode", mode)
            elif "message" in rec:
                msgs.append(rec["message"])
        return cls(sid, mode, msgs)

    # ---- messages
    def add(self, msg: dict) -> None:
        self.messages.append(msg)
        self._write({"message": _loggable(msg)})

    def log_note(self, event: str, **data) -> None:
        self._write({"event": event, **data})

    def _write(self, rec: dict) -> None:
        rec = {"ts": datetime.now().isoformat(timespec="seconds"), **rec}
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def has_user_message(self) -> bool:
        return any(m.get("role") == "user" for m in self.messages)

    # ---- inspect_document ka hisaab (controller rule ke liye)
    def note_inspect(self, args_text: str) -> None:
        self.inspects.append((time.time(), args_text))

    def inspected_after(self, file: Path) -> bool:
        mtime = file.stat().st_mtime
        return any(t >= mtime and file.stem in a for t, a in self.inspects)

    # ---- files ko container ke raste pe laana
    def _into_workspace(self, src: Path) -> Path:
        """File pehle se workspace/classroom mein hai toh wahin, warna uploads/<session>/ mein copy."""
        try:
            config.to_container(src)
            return src
        except config.PathError:
            pass
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        dest = self.upload_dir / src.name
        if dest.exists() and dest.stat().st_size != src.stat().st_size:
            dest = self.upload_dir / f"{src.stem}_{int(time.time())}{src.suffix}"
        if not dest.exists():
            shutil.copy2(src, dest)
        return dest


def _clean_user_path(p: str) -> Path:
    return Path(p.strip().strip('"').strip("'")).expanduser()


def build_user_message(session: Session, text: str, photos: list[str], audios: list[str],
                       first: bool) -> tuple[dict, list[str]]:
    """User ka message. first=True ho toh profile/lessons/samay bhi jodta hai. Returns (message, warnings)."""
    warnings: list[str] = []
    head: list[str] = []

    if first:
        now = datetime.now().strftime("%A, %d %b %Y, %H:%M")
        head.append(f"[controller info] Abhi ka samay: {now}. Mode: {session.mode}. Session id: {session.id}. "
                    f"Scratch folder: {config.scratch_dir_container(session.id)}")
        head.append("<profile.md>\n" + _read_optional(config.MEMORY_DIR / "profile.md", "(abhi khali)") + "\n</profile.md>")
        head.append("<lessons.md>\n" + _read_optional(config.MEMORY_DIR / "lessons.md", "(abhi khali)") + "\n</lessons.md>")

    audio_lines: list[str] = []
    for a in audios:
        src = _clean_user_path(a)
        if not src.exists():
            warnings.append(f"audio nahi mili: {src}")
        elif src.suffix.lower() not in AUDIO_EXT:
            warnings.append(f"{src.name}: ye audio/video file nahi lagti, phir bhi path de diya")
            audio_lines.append(config.to_container(session._into_workspace(src)))
        else:
            audio_lines.append(config.to_container(session._into_workspace(src)))
    if audio_lines:
        head.append("Lecture recording (container path): " + ", ".join(audio_lines))

    image_parts: list[dict] = []
    photo_lines: list[str] = []
    for p in photos:
        src = _clean_user_path(p)
        part, why = image_to_part(src)
        if part is None:
            warnings.append(why)
            continue
        cpath = config.to_container(session._into_workspace(src))
        photo_lines.append(cpath)
        image_parts.append({"type": "text", "text": f"[photo: {cpath}]"})
        image_parts.append(part)
    if photo_lines:
        head.append(f"{len(photo_lines)} photo(s) neeche attached hain. Originals container mein: " + ", ".join(photo_lines))

    body = "\n\n".join(head + ["--- Shardul ka message ---\n" + text]) if head else text
    if not image_parts:
        return {"role": "user", "content": body}, warnings
    return {"role": "user", "content": [{"type": "text", "text": body}] + image_parts}, warnings