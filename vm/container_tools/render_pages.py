#!/usr/bin/env python3
"""render_pages.py - PDF (ya docx/pptx/xlsx) ke pages ko images (JPEG) mein badalta hai.

Use:  python /tools/render_pages.py <file> [--pages 1,3-5] [--dpi 110] [--quality 82]
                                    [--out-dir DIR] [--max-pages 30]
Output files: <out-dir>/p001.jpg, p002.jpg ... (1-based page number)
Default out-dir: /workspace/scratch/render/<file-naam>/
Phir view_image se dekho. NOTE: ek step mein bahut saari images mat dekho (bytes limit).
"""
import argparse
import re
import shutil
import sys
import traceback
from pathlib import Path

import _common as C

pymupdf = C.import_pymupdf()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--pages", default=None)
    ap.add_argument("--dpi", type=int, default=110)
    ap.add_argument("--quality", type=int, default=82)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--max-pages", type=int, default=30)
    args = ap.parse_args()

    if not (50 <= args.dpi <= 250):
        raise C.ToolError("--dpi must be between 50 and 250")

    pdf_path, note = C.open_as_pdf(args.path)
    doc = pymupdf.open(str(pdf_path))
    if doc.needs_pass:
        raise C.ToolError("PDF is password protected")
    n = len(doc)
    if n == 0:
        raise C.ToolError("document has 0 pages")

    idx = C.parse_pages(args.pages, n)
    capped = len(idx) > args.max_pages
    idx = idx[: args.max_pages]

    safe = re.sub(r"[^\w.\-]+", "_", Path(args.path).name)
    out_dir = Path(args.out_dir) if args.out_dir else C.SCRATCH / "render" / safe
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("p[0-9][0-9][0-9].jpg"):  # purane pages hatao, confusion na ho
        old.unlink()

    files = []
    total = 0
    for i in idx:
        pix = doc[i].get_pixmap(dpi=args.dpi, alpha=False)
        img = C.pixmap_to_pil(pix)
        out = out_dir / f"p{i + 1:03d}.jpg"
        img.save(out, "JPEG", quality=args.quality, optimize=True)
        size = out.stat().st_size
        total += size
        files.append((i + 1, out, size, img.size))

    print("STATUS: partial" if capped else "STATUS: ok")
    print(f"FILE: {args.path}")
    if note:
        print(f"CONVERTED: {note}")
    print(f"RENDERED: {len(files)} of {n} pages at {args.dpi} dpi, total {total // 1024} KB")
    if capped:
        print(f"NOTE: only first {args.max_pages} selected pages rendered; use --pages for the rest")
    for pno, out, size, (w, h) in files:
        print(f"p{pno}: {out} ({size // 1024} KB, {w}x{h})")
    if total > C.STEP_BYTES_HINT * 0.9:
        per = max(1, int(len(files) * (C.STEP_BYTES_HINT * 0.8) / total))
        print(f"WARNING: total is close to the per-step image limit. "
              f"View at most ~{per} of these pages per step.")


if __name__ == "__main__":
    try:
        main()
    except C.ToolError as e:
        C.fail(str(e))
    except SystemExit:
        raise
    except Exception as e:
        tb = traceback.format_exc().strip().splitlines()[-1]
        C.fail(f"render crashed: {type(e).__name__}: {e} ({tb})")
