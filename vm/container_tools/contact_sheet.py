#!/usr/bin/env python3
"""contact_sheet.py - kai pages ke chhote thumbnails ek hi image mein (grid).

Use:  python /tools/contact_sheet.py <file> [--pages all] [--cols 4] [--thumb 320]
                                     [--per-sheet 12] [--max-sheets 3] [--out-dir DIR]
Maqsad: poore document ka LAYOUT ek nazar mein (khali jagah, bhare pages, diagram kahan hai).
Text padhne ke liye nahi, uske liye render_pages.
Output: <out-dir>/sheet_01.jpg ...  Default out-dir: /workspace/scratch/sheets/<file-naam>/
"""
import argparse
import math
import re
import traceback
from pathlib import Path

import _common as C

pymupdf = C.import_pymupdf()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--pages", default=None)
    ap.add_argument("--cols", type=int, default=4)
    ap.add_argument("--thumb", type=int, default=320, help="thumbnail width in px")
    ap.add_argument("--per-sheet", type=int, default=12)
    ap.add_argument("--max-sheets", type=int, default=3)
    ap.add_argument("--quality", type=int, default=80)
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    from PIL import Image, ImageDraw

    if not (1 <= args.cols <= 8):
        raise C.ToolError("--cols must be between 1 and 8")
    if not (120 <= args.thumb <= 600):
        raise C.ToolError("--thumb must be between 120 and 600")

    pdf_path, note = C.open_as_pdf(args.path)
    doc = pymupdf.open(str(pdf_path))
    if doc.needs_pass:
        raise C.ToolError("PDF is password protected")
    n = len(doc)
    if n == 0:
        raise C.ToolError("document has 0 pages")

    idx = C.parse_pages(args.pages, n)
    dpages = set(C.diagram_pages(doc))

    cap = args.per_sheet * args.max_sheets
    capped = len(idx) > cap
    idx = idx[:cap]

    safe = re.sub(r"[^\w.\-]+", "_", Path(args.path).name)
    out_dir = Path(args.out_dir) if args.out_dir else C.SCRATCH / "sheets" / safe
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("sheet_[0-9][0-9].jpg"):
        old.unlink()

    font = C.find_font(16)
    pad, label_h = 8, 24
    results = []
    for s in range(math.ceil(len(idx) / args.per_sheet)):
        chunk = idx[s * args.per_sheet:(s + 1) * args.per_sheet]
        thumbs = []
        for i in chunk:
            page = doc[i]
            scale = args.thumb / page.rect.width
            pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
            thumbs.append((i + 1, C.pixmap_to_pil(pix)))
        cell_w = args.thumb + 2 * pad
        cell_h = max(t.size[1] for _, t in thumbs) + label_h + 2 * pad
        cols = min(args.cols, len(thumbs))
        rows = math.ceil(len(thumbs) / cols)
        sheet = Image.new("RGB", (cols * cell_w, rows * cell_h), (235, 235, 235))
        draw = ImageDraw.Draw(sheet)
        for k, (pno, im) in enumerate(thumbs):
            cx, cy = (k % cols) * cell_w, (k // cols) * cell_h
            tag = f"p{pno}" + ("  [diagram?]" if pno in dpages else "")
            draw.text((cx + pad, cy + pad), tag, fill=(0, 0, 0), font=font)
            ix, iy = cx + pad, cy + pad + label_h
            sheet.paste(im, (ix, iy))
            draw.rectangle([ix - 1, iy - 1, ix + im.size[0], iy + im.size[1]], outline=(120, 120, 120))
        out = out_dir / f"sheet_{s + 1:02d}.jpg"
        sheet.save(out, "JPEG", quality=args.quality, optimize=True)
        results.append((out, [p for p, _ in thumbs], out.stat().st_size, sheet.size))

    print("STATUS: partial" if capped else "STATUS: ok")
    print(f"FILE: {args.path}")
    if note:
        print(f"CONVERTED: {note}")
    print(f"SHEETS: {len(results)} (pages shown: {len(idx)} of {n})")
    if capped:
        print(f"NOTE: only first {cap} pages shown; use --pages for the rest")
    if dpages:
        print("DIAGRAM_PAGES (guess): " + ", ".join(map(str, sorted(dpages))))
    for out, pages, size, (w, h) in results:
        print(f"{out} (pages {pages[0]}-{pages[-1]}, {size // 1024} KB, {w}x{h})")
    print("NOTE: thumbnails are for LAYOUT only (empty space, crowding, where diagrams are). "
          "Text is too small to read; use render_pages for that.")


if __name__ == "__main__":
    try:
        main()
    except C.ToolError as e:
        C.fail(str(e))
    except SystemExit:
        raise
    except Exception as e:
        tb = traceback.format_exc().strip().splitlines()[-1]
        C.fail(f"contact_sheet crashed: {type(e).__name__}: {e} ({tb})")
