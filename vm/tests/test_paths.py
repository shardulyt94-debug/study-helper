import tempfile
from pathlib import Path

import config


def _patched(fn):
    def wrapper():
        with tempfile.TemporaryDirectory() as d:
            old = (config.WORKSPACE_HOST, config.CLASSROOM_HOST)
            config.WORKSPACE_HOST, config.CLASSROOM_HOST = Path(d) / "workspace", Path(d) / "classroom"
            try:
                fn()
            finally:
                config.WORKSPACE_HOST, config.CLASSROOM_HOST = old
    wrapper.__name__ = fn.__name__
    return wrapper


@_patched
def test_to_host_and_back():
    p = config.to_host("/workspace/uploads/a.m4a")
    assert p == config.WORKSPACE_HOST / "uploads" / "a.m4a"
    assert config.to_container(p) == "/workspace/uploads/a.m4a"
    assert config.to_container(config.to_host("/classroom/OOP/x.pdf")) == "/classroom/OOP/x.pdf"
    assert config.to_container(config.WORKSPACE_HOST) == "/workspace"


@_patched
def test_relative_path_means_workspace():
    assert config.to_host("scratch/a.txt") == config.WORKSPACE_HOST / "scratch" / "a.txt"


@_patched
def test_escape_is_rejected():
    for bad in ["/etc/passwd", "/workspace/../etc/passwd", "/workspacex/a", "", "/classroom/../workspace/../../x"]:
        try:
            config.to_host(bad)
        except config.PathError:
            continue
        raise AssertionError(f"{bad!r} reject hona chahiye tha")


@_patched
def test_host_path_outside_is_rejected():
    try:
        config.to_container(Path("/somewhere/else.txt"))
    except config.PathError:
        return
    raise AssertionError("reject hona chahiye tha")


def test_session_scratch_dir_is_sanitized():
    config.set_session_id("../../evil id")
    assert ".." not in config.scratch_dir_container() and " " not in config.scratch_dir_container()
    config.set_session_id("default")
