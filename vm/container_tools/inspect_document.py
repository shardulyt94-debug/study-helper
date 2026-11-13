#!/usr/bin/env python3
"""inspect_document.py - document ka TEXT-based layout check.

Use:  python /tools/inspect_document.py <file.pdf|docx|pptx|xlsx> [--max-issues 40]

docx/pptx/xlsx pehle LibreOffice se PDF banti hai, phir wahi checks.
Output ki pehli line:
  STATUS: ok       -> sab checks chale, koi issue nahi
  STATUS: partial  -> issues mile, YA koi check skip hua (neeche ISSUES / SKIPPED dekho)
  STATUS: error    -> inspect hi nahi ho paya
Diagram ke ANDAR ki galtiyan (label line pe chadha) ye nahi pakadta: uske liye render_pages / contact_sheet.

Saare thresholds andaze hain, golden test ke baad tune honge.
"""
import argparse
import re
import sys
import traceback
from collections import Counter
from pathlib import Path

import _common as C

pymupdf = C.import_pymupdf()

# ---- thresholds (andaze) ----
EDGE_OUT = 2          # pt: page ke bahar nikla
EDGE_NEAR = 10        # pt: kinare ke bahut paas
OVERLAP_FRAC = 0.30   # chhoti line ka itna hissa doosre block se dabe to overlap
MIN_FONT = 6.5        # pt se chhota text
HEADING_RATIO = 1.15  # body font ka itna guna bada = heading
FOOTER_BAND = 0.92    # page height ka itna neeche = footer/page number
HEADER_BAND = 0.06    # itna upar = header
EMPTY_CHARS = 20      # itne se kam characters = khali page
THIN_LAST_CHARS = 40  # akhri page pe itne se kam = lagbhag khali
TABLE_BOTTOM = 0.88   # table page ke itna neeche tak = neeche tak gayi
TABLE_TOP = 0.12      # agle page pe table itna upar = continue hui
MAX_TABLE_PAGES = 60  # pdfplumber slow hai, isse zyada pages pe table check skip
MAX_LINES_OVERLAP = 500


def snip(text, n=55):
    t = re.sub(r"\s+", " ", text or "").strip()
    return t if len(t) <= n else t[: n - 1] + "…"


def inter_area(a, b):
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return w * h if (w > 0 and h > 0) else 0.0


def area(r):
    return max(0.0, r[2] - r[0]) * max(0.0, r[3] - r[1])


def extract_blocks(page):
    """Page ke text blocks: har block mein lines (text, bbox, size, bold)."""
    blocks = []
    # MEDIABOX_CLIP jaanbujh ke nahi: warna page ke bahar ka text hat jaata hai aur overflow dikhta hi nahi
    flags = pymupdf.TEXT_PRESERVE_LIGATURES | pymupdf.TEXT_PRESERVE_WHITESPACE
    for b in page.get_text("dict", flags=flags).get("blocks", []):
        if b.get("type") != 0:
            continue
        lines = []
        for ln in b.get("lines", []):
            spans = [s for s in ln.get("spans", []) if s.get("text", "").strip()]
            if not spans:
                continue
            text = "".join(s["text"] for s in spans).strip()
            lines.append({
                "text": text,
                "bbox": tuple(ln["bbox"]),
                "size": max(s["size"] for s in spans),
                "minsize": min(s["size"] for s in spans),
                "bold": all((s.get("flags", 0) & 16) or ("bold" in s.get("font", "").lower())
                            for s in spans),
            })
        if lines:
            blocks.append({
                "bbox": tuple(b["bbox"]),
                "lines": lines,
                "text": " ".join(l["text"] for l in lines),
            })
    return blocks


def body_font_size(all_pages_blocks):
    """Sabse zyada characters wala font size = body text."""
    c = Counter()
    for blocks in all_pages_blocks:
        for b in blocks:
            for l in b["lines"]:
                c[round(l["size"], 1)] += len(l["text"])
    return c.most_common(1)[0][0] if c else 0.0


def is_heading(block, body):
    if not body:
        return False
    first = block["lines"][0]
    chars = len(block["text"])
    if chars > 120:
        return False
    if first["size"] >= body * HEADING_RATIO:
        return True
    if all(l["bold"] for l in block["lines"]) and len(block["lines"]) <= 2 and first["size"] >= body * 0.95:
        return True
    return False


def check_page(pno, page, blocks, body, flow, is_last):
    """Ek page ke issues: list of (page_no, tag, message)."""
    issues = []
    w, h = page.rect.width, page.rect.height

    # --- khali / patla page ---
    chars = sum(len(b["text"]) for b in blocks)
    try:
        has_img = len(page.get_image_info()) > 0
        has_draw = len(page.get_drawings()) > 0
    except Exception:
        has_img = has_draw = True  # pata nahi chala, galat flag mat karo
    if chars < EMPTY_CHARS and not has_img and not has_draw:
        issues.append((pno, "empty", f"page is blank (only {chars} text chars, no image/drawing)"))
    elif flow and is_last and chars < THIN_LAST_CHARS and not has_img:
        issues.append((pno, "thin-last-page",
                       f"last page has almost nothing ({chars} chars): \"{snip(' '.join(b['text'] for b in blocks))}\""))

    # --- overflow: text page ke bahar / kinare pe ---
    for b in blocks:
        x0, y0, x1, y1 = b["bbox"]
        if x0 < -EDGE_OUT or y0 < -EDGE_OUT or x1 > w + EDGE_OUT or y1 > h + EDGE_OUT:
            issues.append((pno, "overflow", f"text goes outside the page: \"{snip(b['text'])}\""))
        elif x0 < EDGE_NEAR or x1 > w - EDGE_NEAR:
            issues.append((pno, "edge", f"text within {EDGE_NEAR}pt of page edge (may be clipped): \"{snip(b['text'])}\""))

    # --- image page ke bahar ---
    try:
        for im in page.get_image_info():
            x0, y0, x1, y1 = im["bbox"]
            if x0 < -EDGE_OUT or y0 < -EDGE_OUT or x1 > w + EDGE_OUT or y1 > h + EDGE_OUT:
                issues.append((pno, "image-overflow", "an image extends beyond the page (cut off)"))
    except Exception:
        pass

    # --- chhota font ---
    small = [l for b in blocks for l in b["lines"] if l["minsize"] < MIN_FONT]
    if small:
        issues.append((pno, "small-font",
                       f"{len(small)} line(s) with font < {MIN_FONT}pt, e.g. \"{snip(small[0]['text'])}\""))

    # --- overlap: alag blocks ki lines ek doosre pe ---
    nlines = sum(len(b["lines"]) for b in blocks)
    if nlines <= MAX_LINES_OVERLAP:
        for b in blocks:  # ek hi block ke andar overlap (threshold sakht: tight line spacing normal hai)
            ls = b["lines"]
            for i in range(len(ls)):
                for j in range(i + 1, len(ls)):
                    ia = inter_area(ls[i]["bbox"], ls[j]["bbox"])
                    m = min(area(ls[i]["bbox"]), area(ls[j]["bbox"]))
                    if m > 0 and ia / m > 0.5:
                        issues.append((pno, "overlap",
                                       f"text overlaps: \"{snip(ls[i]['text'], 40)}\" <-> \"{snip(ls[j]['text'], 40)}\""))
        for i in range(len(blocks)):
            for j in range(i + 1, len(blocks)):
                if inter_area(blocks[i]["bbox"], blocks[j]["bbox"]) == 0:
                    continue
                hit = None
                for li in blocks[i]["lines"]:
                    for lj in blocks[j]["lines"]:
                        ia = inter_area(li["bbox"], lj["bbox"])
                        m = min(area(li["bbox"]), area(lj["bbox"]))
                        if m > 0 and ia / m > OVERLAP_FRAC:
                            hit = (li, lj)
                            break
                    if hit:
                        break
                if hit:
                    issues.append((pno, "overlap",
                                   f"text overlaps: \"{snip(hit[0]['text'], 40)}\" <-> \"{snip(hit[1]['text'], 40)}\""))

    # --- akeli heading (page ke aakhir mein, neeche kuch nahi) ---
    if flow and blocks:
        content = [b for b in blocks if HEADER_BAND * h < b["bbox"][1] and b["bbox"][3] < FOOTER_BAND * h]
        if content:
            last = max(content, key=lambda b: b["bbox"][3])
            below_img = False
            try:
                below_img = any(im["bbox"][3] > last["bbox"][3] + 2 for im in page.get_image_info())
            except Exception:
                pass
            if is_heading(last, body) and not below_img:
                issues.append((pno, "lone-heading",
                               f"heading is the last thing on the page (content continues on next page): \"{snip(last['text'])}\""))
    return issues


def check_tables(pdf_path, n_pages, flow):
    """pdfplumber se: table kinare se katti hai / do pages mein tooti hai."""
    import pdfplumber
    issues = []
    per_page = []  # (w, h, [bbox...])
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            tabs = []
            try:
                tabs = [t.bbox for t in page.find_tables()]  # (x0, top, x1, bottom)
            except Exception:
                pass
            per_page.append((page.width, page.height, tabs))
    for i, (w, h, tabs) in enumerate(per_page):
        for (x0, top, x1, bottom) in tabs:
            if x0 < 5 or x1 > w - 5:
                issues.append((i + 1, "table-cut",
                               "table touches/extends past the page edge (columns may be cut)"))
        if flow and i + 1 < len(per_page):
            nw, nh, ntabs = per_page[i + 1]
            ends_low = any(b[3] > TABLE_BOTTOM * h for b in tabs)
            starts_high = any(b[1] < TABLE_TOP * nh for b in ntabs)
            if ends_low and starts_high:
                issues.append((i + 1, "table-split", f"table runs to page bottom and continues on page {i + 2}"))
    return issues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--max-issues", type=int, default=40)
    args = ap.parse_args()

    pdf_path, note = C.open_as_pdf(args.path)
    doc = pymupdf.open(str(pdf_path))
    if doc.needs_pass:
        raise C.ToolError("PDF is password protected")
    n = len(doc)
    if n == 0:
        raise C.ToolError("document has 0 pages")

    flow = Path(args.path).suffix.lower() not in C.SLIDE_SUFFIXES  # slides ko page-flow checks nahi lagte
    all_blocks = [extract_blocks(doc[i]) for i in range(n)]
    body = body_font_size(all_blocks)

    issues = []
    for i in range(n):
        issues += check_page(i + 1, doc[i], all_blocks[i], body, flow, i == n - 1)

    skipped = []
    if n > MAX_TABLE_PAGES:
        skipped.append(f"table check skipped (document has {n} pages, limit {MAX_TABLE_PAGES})")
    else:
        try:
            issues += check_tables(pdf_path, n, flow)
        except ImportError:
            skipped.append("table check skipped (pdfplumber not installed)")
        except Exception as e:
            skipped.append(f"table check failed: {type(e).__name__}: {e}")

    issues.sort(key=lambda x: x[0])
    status = "ok" if (not issues and not skipped) else "partial"

    print(f"STATUS: {status}")
    print(f"FILE: {args.path}")
    if note:
        print(f"CONVERTED: {note}")
    print(f"CHECKED: {n} pages, body font ~{body:.1f}pt, mode={'document' if flow else 'slides'}")
    print(f"ISSUES: {len(issues)}")
    for pno, tag, msg in issues[: args.max_issues]:
        print(f"p{pno} [{tag}] {msg}")
    if len(issues) > args.max_issues:
        print(f"... +{len(issues) - args.max_issues} more issues not shown")
    for s in skipped:
        print(f"SKIPPED: {s}")
    dp = C.diagram_pages(doc)
    if dp:
        print("DIAGRAM_PAGES (guess): " + ", ".join(map(str, dp)))
    print("NOT CHECKED: errors inside diagrams (label on a line, crowded drawing). "
          "Look at those pages with render_pages / contact_sheet.")


if __name__ == "__main__":
    try:
        main()
    except C.ToolError as e:
        C.fail(str(e))
    except SystemExit:
        raise
    except Exception as e:
        tb = traceback.format_exc().strip().splitlines()[-1]
        C.fail(f"inspect crashed: {type(e).__name__}: {e} ({tb})")