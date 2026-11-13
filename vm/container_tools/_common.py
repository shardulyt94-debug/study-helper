"""Shared helpers for /tools scripts (inspect_document, render_pages, contact_sheet).

Container mein ye scripts aise chalti hain:  python /tools/<script>.py <args>
Output ki pehli line hamesha  STATUS: ok | partial | error
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRATCH = Path(os.environ.get("TOOLS_SCRATCH", "/workspace/scratch"))
CONVERT_DIR = SCRATCH / "_converted"
SOFFICE_TIMEOUT = int(os.environ.get("SOFFICE_TIMEOUT", "100"))

OFFICE_SUFFIXES = {".docx", ".dotx", ".doc", ".rtf", ".odt",
                   ".pptx", ".potx", ".ppt", ".odp",
                   ".xlsx", ".xls", ".ods"}
SLIDE_SUFFIXES = {".pptx", ".potx", ".ppt", ".odp"}

# view_image ek step mein itne bytes se zyada nahi le sakta (vision.py MAX_STEP_BYTES)
STEP_BYTES_HINT = 2_000_000


class ToolError(Exception):
    """Aisi galti jo user/model ko seedha batani hai (traceback nahi)."""


def import_pymupdf():
    try:
        import pymupdf
        return pymupdf
    except ImportError:
        import fitz  # purana naam
        return fitz


def open_as_pdf(src):
    """PDF path wapas deta hai. docx/pptx/xlsx ho toh LibreOffice se convert karta hai.

    Returns (pdf_path, note). note = None agar input pehle se PDF tha.
    Converted file: /workspace/scratch/_converted/<poora-naam>.pdf (t.docx -> t.docx.pdf,
    taaki t.docx aur t.pptx ek doosre ko overwrite na karein).
    """
    p = Path(src)
    if not p.exists():
        raise ToolError(f"file not found: {src}")
    suffix = p.suffix.lower()
    if suffix == ".pdf":
        return p, None
    if suffix not in OFFICE_SUFFIXES:
        raise ToolError(f"unsupported file type '{suffix or 'none'}' (use pdf/docx/pptx/xlsx)")

    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise ToolError("LibreOffice (soffice) not found in container")

    CONVERT_DIR.mkdir(parents=True, exist_ok=True)
    final = CONVERT_DIR / f"{p.name}.pdf"
    with tempfile.TemporaryDirectory(prefix="lo_out_") as tmp:
        cmd = [soffice, "-env:UserInstallation=file:///tmp/lo_profile",
               "--headless", "--convert-to", "pdf", "--outdir", tmp, str(p)]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=SOFFICE_TIMEOUT)
        except subprocess.TimeoutExpired:
            raise ToolError(f"LibreOffice convert timed out after {SOFFICE_TIMEOUT}s")
        out = Path(tmp) / (p.stem + ".pdf")
        if not out.exists():
            tail = ((r.stderr or "") + (r.stdout or "")).strip()[-300:]
            raise ToolError(f"LibreOffice convert failed: {tail}")
        shutil.move(str(out), str(final))
    note = (f"converted by LibreOffice -> {final} "
            "(LibreOffice render, real Word/PowerPoint may differ slightly in fonts/spacing)")
    return final, note


def parse_pages(spec, n_pages):
    """'1,3-5' / 'all' / 'last' / None -> 0-based page indexes (sorted, unique)."""
    if spec is None or str(spec).strip().lower() in ("", "all"):
        return list(range(n_pages))
    spec = str(spec).strip().lower()
    if spec == "last":
        return [n_pages - 1]
    out = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if "-" in part:
                a, b = part.split("-", 1)
                a, b = int(a), int(b)
                if a > b:
                    a, b = b, a
                rng = range(a, b + 1)
            else:
                rng = [int(part)]
        except ValueError:
            raise ToolError(f"bad --pages value '{part}' (example: 1,3-5)")
        for k in rng:
            if k < 1 or k > n_pages:
                raise ToolError(f"page {k} does not exist (document has {n_pages} pages)")
            out.add(k - 1)
    if not out:
        raise ToolError("no pages selected")
    return sorted(out)


def diagram_pages(doc):
    """Andaza: kaun se pages mein image ya curve-wale drawings hain (diagram ho sakte hain).
    Thresholds andaze hain, verify nahi hue. Table ki seedhi lines ko ginta nahi.
    """
    found = []
    for i, page in enumerate(doc):
        try:
            has_img = len(page.get_image_info()) > 0
            curves = 0
            for d in page.get_drawings():
                for it in d.get("items", []):
                    if it[0] == "c":
                        curves += 1
            if has_img or curves > 5:
                found.append(i + 1)
        except Exception:
            continue
    return found


def find_font(size=14):
    from PIL import ImageFont
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"):
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def pixmap_to_pil(pix):
    from PIL import Image
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def fail(msg, code=2):
    print("STATUS: error")
    print(f"ERROR: {msg}")
    sys.exit(code)
