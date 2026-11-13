"""
Document check tools: inspect_document, render_pages, contact_sheet.
Asli kaam container ke /tools/*.py scripts karti hain; yahan sirf unhe chalana aur
unki pehli line (STATUS: ok|partial|error) ko registry ke result mein badalna hai.

(Naam `inspect.py` nahi rakha: Python ka apna `inspect` module hai, takrayega.)
"""
from __future__ import annotations

from .container import docker_exec
from .registry import error, ok, params, partial, register, ToolResult

SCRIPT_TIMEOUT = 150   # LibreOffice convert (max ~100s) + checks


def _run_script(script: str, args: list, **meta) -> ToolResult:
    cmd = ["timeout", "-k", "5", str(SCRIPT_TIMEOUT), "python", f"/tools/{script}"] + [str(a) for a in args]
    out, code, hard_killed, _ = docker_exec(cmd, timeout=SCRIPT_TIMEOUT)
    text = out.decode("utf-8", errors="replace").strip()
    meta = {"script": script, "exit_code": code, **meta}

    if code == 124 or hard_killed:
        return error(f"{script} {SCRIPT_TIMEOUT}s mein khatam nahi hua, kill kiya gaya", **meta)

    first, _, rest = text.partition("\n")
    first, rest = first.strip(), rest.strip()
    if first == "STATUS: ok":
        return ok(rest, **meta)
    if first == "STATUS: partial":
        return partial(rest, **meta)
    if first == "STATUS: error":
        return error(rest, **meta)
    # script chali hi nahi / crash / docker ki galti
    return error(f"{script} se expected output nahi aaya (exit {code}):\n{text[-1500:]}", **meta)


@register(
    "inspect_document",
    "Document ka text-based layout check (PDF, docx, pptx, xlsx; path container ka, jaise "
    "/workspace/output/...). docx/pptx/xlsx pehle LibreOffice se PDF banti hai. Check: page ke bahar "
    "text, overlap, khali page, akeli heading, kati table, bahut chhota font. "
    "Result: STATUS: ok = koi issue nahi; partial = issues mile (page number + text ke saath) YA koi "
    "check skip hua; error = check hi nahi ho paya. Diagram ke ANDAR ki galtiyan ye nahi pakadta, "
    "uske liye render_pages / contact_sheet + view_image. DIAGRAM_PAGES line andaza hai.",
    params({"path": {"type": "string", "description": "document ka container path"}}, ["path"]),
    milestone="Document check kar raha hu: {path}",
)
def inspect_document(path: str) -> ToolResult:
    return _run_script("inspect_document.py", [path], path=path)


@register(
    "render_pages",
    "Document ke pages ko images (JPEG) mein badalo, phir view_image se dekh. Result mein har page ki "
    "image ka path aur size hota hai. Ek step mein bahut saare pages view_image mat kar (bytes limit): "
    "result ki WARNING line follow kar. Pages ka format: '1,3-5'. Default: sabhi pages (max 30).",
    params({"path": {"type": "string", "description": "document ka container path"},
            "pages": {"type": "string", "description": "jaise '1,3-5' ya 'last', default sabhi"},
            "dpi": {"type": "integer", "description": "default 110, 50-250"}}, ["path"]),
    milestone="Pages render kar raha hu: {path}",
)
def render_pages(path: str, pages: str = "", dpi: int = 0) -> ToolResult:
    args = [path]
    if pages:
        args += ["--pages", pages]
    if dpi:
        args += ["--dpi", int(dpi)]
    return _run_script("render_pages.py", args, path=path)


@register(
    "contact_sheet",
    "Document ke saare pages ke chhote thumbnails ek hi image mein (grid), sirf LAYOUT dekhne ke liye "
    "(khali jagah, bhare pages, diagram kahan hai). Text isme padhne layak nahi. Result mein sheet image "
    "ka path aata hai, use view_image se dekh.",
    params({"path": {"type": "string", "description": "document ka container path"},
            "pages": {"type": "string", "description": "jaise '1,3-5', default sabhi"},
            "cols": {"type": "integer", "description": "columns, default 4"}}, ["path"]),
    milestone="Contact sheet bana raha hu: {path}",
)
def contact_sheet(path: str, pages: str = "", cols: int = 0) -> ToolResult:
    args = [path]
    if pages:
        args += ["--pages", pages]
    if cols:
        args += ["--cols", int(cols)]
    return _run_script("contact_sheet.py", args, path=path)
