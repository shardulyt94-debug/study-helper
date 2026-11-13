"""Docker/GPU/internet ke bina chalne wale hisse: parser, edit script, sniffing, memory, index."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

import config
import events
from tools import classroom, container, memory, transcribe, web


# ---- transcribe ----
def test_parse_progress():
    p = transcribe.parse_progress("  chunk 12/40 | 4.5/45.2 min | ETA 00:03:10")
    assert p == {"chunk": 12, "chunks": 40, "done_min": 4.5, "total_min": 45.2, "eta_sec": 190}
    assert transcribe.parse_progress("Model ready on cuda") is None


def test_split_stream_handles_carriage_returns():
    buf = "Model load\n  chunk 1/3 | 0.1/1.0 min | ETA 00:00:05\r  chunk 2/3 | 0.5/1.0 min | ETA 00:00:02\r  chunk 3/"
    lines, rest = transcribe.split_stream(buf)
    assert len(lines) == 3 and rest.strip() == "chunk 3/"
    assert transcribe.parse_progress(lines[2])["chunk"] == 2
    lines, rest = transcribe.split_stream("done\r\n")
    assert lines == ["done"] and rest == ""


def test_summarize_transcript():
    t = "[00:00:01] namaste\n[00:10:05] arrays\n[chunk skip hua: GPU memory kam padi]\n"
    assert transcribe.summarize_transcript(t) == {"lines": 3, "last_timestamp": "00:10:05", "skipped": 1}


def test_file_hash_is_stable():
    with tempfile.TemporaryDirectory() as d:
        a, b = Path(d) / "a", Path(d) / "b"
        a.write_bytes(b"same"); b.write_bytes(b"same")
        assert transcribe.file_hash(a) == transcribe.file_hash(b) and len(transcribe.file_hash(a)) == 16


# ---- edit_file script (container ke python3 jaisi) ----
def _edit(path, old, new, all_=False):
    req = json.dumps({"path": str(path), "old": old, "new": new, "all": all_})
    r = subprocess.run([sys.executable, "-c", container.EDIT_SCRIPT], input=req.encode(), capture_output=True)
    return r.returncode, r.stdout.decode()


def test_edit_script():
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "n.md"
        f.write_bytes("एक\r\ntwo\r\ntwo\r\n".encode("utf-8"))
        assert _edit(f, "एक", "ONE")[0] == 0 and f.read_bytes().startswith(b"ONE\r\n")   # CRLF bacha
        assert _edit(f, "two", "2")[0] == 3                                            # 2 jagah: mana
        assert _edit(f, "two", "2", True)[0] == 0 and f.read_text().count("2") == 2
        assert _edit(f, "missing", "x")[0] == 2
        assert _edit(Path(d) / "nope", "a", "b")[0] == 4
        assert _edit(f, "", "b")[0] == 6


# ---- read_file chunking (docker_exec nakli) ----
def test_read_file_uses_chunks_and_binary_check():
    big = ("hello world line\n" * 2000).encode()
    with mock.patch.object(container, "docker_exec", return_value=(big, 0, False, False)):
        r = container.read_file("/workspace/x.txt", part=2)
        assert r.text.startswith("STATUS: ok\n[part 2/") and r.meta["total_parts"] > 1
    with mock.patch.object(container, "docker_exec", return_value=(b"PK\x00\x03", 0, False, False)):
        assert container.read_file("/workspace/x.zip").text.startswith("STATUS: error")
    with mock.patch.object(container, "docker_exec", return_value=(b"No such file", 1, False, False)):
        assert container.read_file("/nope").text.startswith("STATUS: error")


def test_run_command_status_and_big_output_saved():
    with tempfile.TemporaryDirectory() as d:
        with mock.patch.object(config, "BIG_OUT_DIR", Path(d)), \
             mock.patch.object(container, "docker_exec", return_value=(b"x" * 50000, 0, False, False)):
            r = container.run_command("echo hi")
            assert r.text.startswith("STATUS: ok") and "outputs/" in r.text
            assert len(list(Path(d).iterdir())) == 1 and r.meta["output_file"]
        with mock.patch.object(container, "docker_exec", return_value=(b"boom", 2, False, False)):
            r = container.run_command("false")
            assert r.text.startswith("STATUS: error") and r.meta["exit_code"] == 2


# ---- web ----
def test_sniff_image():
    assert web.sniff_image(b"\x89PNG\r\n\x1a\n....") == ".png"
    assert web.sniff_image(b"\xff\xd8\xff\xe0..") == ".jpg"
    assert web.sniff_image(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == ".webp"
    assert web.sniff_image(b"<svg xmlns=...") is None
    assert web.sniff_image(b"<html>") is None


def test_private_hosts_blocked():
    assert web.is_public_host("127.0.0.1") is False
    assert web.is_public_host("192.168.1.10") is False
    assert web.is_public_host("169.254.169.254") is False
    assert web.is_public_host("localhost") is False


def test_html_to_text():
    title, text = web.html_to_text("<html><head><title>T</title><style>x{}</style></head>"
                                   "<body><h1>Hi</h1><script>bad()</script><p>a  b</p></body></html>")
    assert title == "T" and "bad" not in text and "x{}" not in text and "Hi" in text and "a b" in text


# ---- memory ----
def test_memory_append_dedupe_and_read():
    with tempfile.TemporaryDirectory() as d:
        with mock.patch.object(config, "MEMORY_DIR", Path(d)):
            assert memory.append_memory("lessons.md", "analogy\npasand hai").endswith("analogy pasand hai")
            assert memory.append_memory("lessons.md", "analogy pasand hai") == ""        # duplicate
            assert "analogy pasand hai" in memory.read_memory_text()
            with mock.patch.object(events, "confirm", return_value=False), mock.patch.object(events, "log_event"):
                from tools.registry import run_tool
                r = run_tool("propose_memory_update", '{"file": "lessons.md", "text": "nayi baat"}')
                assert r.startswith("STATUS: denied")
                assert "nayi baat" not in memory.read_memory_text()             # mana kiya toh likha nahi
            with mock.patch.object(events, "confirm", return_value=True), mock.patch.object(events, "log_event"):
                assert run_tool("propose_memory_update", '{"file": "lessons.md", "text": "nayi baat"}').startswith("STATUS: ok")
                assert "nayi baat" in memory.read_memory_text()
                assert run_tool("propose_memory_update", '{"file": "../x.md", "text": "a"}').startswith("STATUS: error")


# ---- classroom ----
def test_filter_sync_output_hides_unchanged():
    out = classroom.filter_sync_output("== OOP -> OOP\n    pehle se hai : a.pdf\n    naya/update : b.pdf\n")
    assert "a.pdf" not in out and "b.pdf" in out


def test_scan_and_filter_materials():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "OOP" / "materials").mkdir(parents=True)
        (root / "OOP" / "materials" / "Pointers Unit3.pdf").write_bytes(b"x")
        (root / "OOP" / "STATUS.md").write_text("x")
        (root / "FDS" / "assignments" / "Lab1").mkdir(parents=True)
        (root / "FDS" / "assignments" / "Lab1" / "details.md").write_text("x")
        with mock.patch.object(config, "CLASSROOM_HOST", root):
            rows = classroom.scan_folders()
            assert len(rows) == 2
            hit = classroom.filter_rows(rows, "pointers")
            assert len(hit) == 1 and hit[0]["path"] == "/classroom/OOP/materials/Pointers Unit3.pdf"
            assert classroom.list_materials(query="zzz").text.startswith("STATUS: ok")
            (root / "index.json").write_text(json.dumps([{"course": "OOP", "title": "Pointers", "posted": "2026-11-01",
                                                          "path": "OOP/materials/Pointers Unit3.pdf", "kind": "material"}]))
            assert "index.json" in classroom.list_materials(query="pointers").meta["source"]


def test_sync_skips_within_min_interval():
    with tempfile.TemporaryDirectory() as d:
        with mock.patch.object(config, "CACHE_DIR", Path(d)):
            import time
            classroom._write_last_sync(time.time())
            assert "SKIP" in classroom.sync_classroom().text
