from unittest import mock

import events
from tools import registry
from tools.registry import ToolResult, error, ok, params, register, run_tool


def _setup():
    @register("t_add", "add", params({"a": {"type": "integer"}, "b": {"type": "integer"}}, ["a", "b"]))
    def add(a: int, b: int):
        return ok(str(a + b), a=a)

    @register("t_boom", "crash", params({}))
    def boom():
        raise RuntimeError("bam")

    @register("t_plain", "plain str", params({}))
    def plain():
        return "hello"

    @register("t_secret", "needs confirm", params({"x": {"type": "string"}}, ["x"]),
              requires_confirmation=True, confirm_text=lambda a: f"save {a['x']}?")
    def secret(x: str):
        return ok("saved " + x)


def _run(*a):
    with mock.patch.object(events, "log_event"):
        return run_tool(*a)


def test_all_cases():
    _setup()
    assert _run("t_add", '{"a": 2, "b": 3}') == "STATUS: ok\n5"
    assert _run("t_add", {"a": 1, "b": 1}).endswith("2")
    assert _run("t_plain", "") == "STATUS: ok\nhello"

    r = _run("t_add", "{bad json")
    assert r.startswith("STATUS: error") and "JSON" in r
    assert _run("t_add", "[1]").startswith("STATUS: error")

    r = _run("t_add", '{"a": 1}')
    assert r.startswith("STATUS: error") and "parameters" in r

    r = _run("nope", "{}")
    assert r.startswith("STATUS: error") and "unknown tool" in r

    r = _run("t_boom", "{}")
    assert r.startswith("STATUS: error") and "bam" in r


def test_confirmation_gate():
    _setup()
    with mock.patch.object(events, "confirm", return_value=False) as c:
        r = _run("t_secret", '{"x": "A"}')
        assert r.startswith("STATUS: denied")
        assert "save A?" in c.call_args[0][0]
    with mock.patch.object(events, "confirm", return_value=True):
        assert _run("t_secret", '{"x": "A"}') == "STATUS: ok\nsaved A"


def test_big_result_is_capped():
    @register("t_big", "big", params({}))
    def big():
        return ok("x" * 100000)
    assert len(_run("t_big", "{}")) < registry.FINAL_CAP_CHARS + 200


def test_schemas_format():
    _setup()
    s = [x for x in registry.schemas() if x["function"]["name"] == "t_add"][0]
    assert s["type"] == "function" and s["function"]["parameters"]["required"] == ["a", "b"]


def test_image_queue():
    import tempfile
    from pathlib import Path
    assert registry.drain_image_message() is None
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "a.png"
        p.write_bytes(b"\x89PNG\r\n\x1a\nxx")
        registry.queue_image(p, "cap")
        msg = registry.drain_image_message()
    assert msg["role"] == "user"
    assert msg["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert registry.drain_image_message() is None
