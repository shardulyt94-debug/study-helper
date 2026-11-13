import chunking
from chunking import CHUNK_CHARS, effective_limit, render_part, split_text

LIMIT = effective_limit()


def test_short_text_is_one_whole_chunk():
    text = "line 1\nline 2\n"
    chunks = split_text(text)
    assert len(chunks) == 1 and chunks[0].text == text
    assert render_part(chunks) == text            # koi label nahi


def test_file_just_under_limit_goes_whole():
    text = ("x" * 99 + "\n") * (LIMIT // 100)
    assert len(text) <= LIMIT
    assert len(split_text(text)) == 1


def test_chunks_cover_everything_and_respect_limit():
    text = "".join(f"line number {i} " + "w" * 40 + "\n" for i in range(2000))
    chunks = split_text(text)
    assert len(chunks) > 1
    assert "".join(c.text for c in chunks) == text
    assert all(len(c.text) <= LIMIT for c in chunks)


def test_line_numbers_are_contiguous():
    text = "".join(f"l{i}\n" for i in range(5000))
    chunks = split_text(text, max_chars=2000)
    assert chunks[0].first_line == 1
    for a, b in zip(chunks, chunks[1:]):
        assert b.first_line == a.last_line + 1
    assert chunks[-1].last_line == 5000


def test_prefers_paragraph_boundary():
    para = ("a" * 50 + "\n") * 40 + "\n"           # ek paragraph ~2041 chars
    text = para * 20
    chunks = split_text(text, max_chars=10000)
    assert all(c.text.endswith("\n\n") for c in chunks[:-1])


def test_single_huge_line_is_hard_split():
    text = "z" * (LIMIT * 3 + 5)
    chunks = split_text(text)
    assert "".join(c.text for c in chunks) == text
    assert all(len(c.text) <= LIMIT for c in chunks)
    assert len(chunks) == 4


def test_devanagari_counted_in_characters():
    text = ("मराठी वाक्य " * 20 + "\n") * 200
    chunks = split_text(text)
    assert all(len(c.text) <= LIMIT for c in chunks)
    assert "".join(c.text for c in chunks) == text


def test_render_part_labels_and_hints():
    text = "".join(f"l{i}\n" for i in range(5000))
    chunks = split_text(text, max_chars=2000)
    n = len(chunks)
    first = render_part(chunks, 1)
    assert first.startswith(f"[part 1/{n}, lines 1-") and "part=2" in first
    assert "aakhri part" in render_part(chunks, n)
    assert "nahi hai" in render_part(chunks, n + 1)
    assert render_part(chunks, "abc").startswith("[part 1/")      # galat input -> part 1


def test_empty_text():
    assert split_text("") == []
    assert render_part([]) == "(khali)"


def test_shorten_head_tail():
    s = "a" * 100 + "b" * 100
    assert chunking.shorten_head_tail(s, 1000) == s
    out = chunking.shorten_head_tail(s, 60, "/workspace/logs/outputs/x.txt")
    assert out.startswith("a" * 30) and out.endswith("b" * 30) and "x.txt" in out
