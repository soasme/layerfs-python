from __future__ import annotations

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
from layerfs import LayerFSError, Store


@pytest.fixture
def store(tmp_path):
    if sys.platform != "linux":
        pytest.skip("upstream Store requires Linux")
    with Store.create(tmp_path / "store") as opened:
        yield opened


@pytest.mark.skipif(sys.platform == "linux", reason="non-Linux refusal")
def test_unsupported_platform_does_not_create_output(tmp_path):
    path = tmp_path / "store"
    with pytest.raises(LayerFSError) as error:
        Store.create(path)
    assert error.value.code == "Unsupported"
    assert not path.exists()


def test_write_edit_and_reopen(store):
    store.write("/hello.txt", "hello world\n")
    assert store.read_text("/hello.txt") == "hello world\n"
    store.edit("/hello.txt", "world", "Python")
    store.close()
    assert store.closed
    store.close()
    with pytest.raises(LayerFSError) as error:
        store.read_text("/hello.txt")
    assert error.value.code == "Closed"
    with Store.open(store.path) as reopened:
        assert reopened.read_text("/hello.txt") == "hello Python\n"
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from layerfs import Store; "
            "s = Store(sys.argv[1]); "
            "assert s.read_text('/hello.txt') == 'hello Python\\n'; s.close()",
            str(store.path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert child.returncode == 0, child.stderr


def test_import_source_and_no_overwrite(store, tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "seed.txt").write_text("seed")
    with Store.create(
        tmp_path / "imported", source=source, project="my-app"
    ) as imported:
        assert imported.read_text("/seed.txt") == "seed"
    store.write("/keep", "preserved")
    with pytest.raises(LayerFSError) as error:
        Store.create(store.path)
    assert error.value.code == "Exists"
    assert store.read_text("/keep") == "preserved"


def test_branches_and_publish(store):
    store.write("/hello", "original")
    store.fork("draft")
    store.write("/hello", "draft", branch="draft")
    assert store.read_text("/hello") == "original"
    assert store.read_text("/hello", ref="draft") == "draft"
    store.publish("draft")
    assert store.read_text("/hello", ref="main") == "draft"
    assert store.branches()
    assert store.commits("draft")


def test_atomic_batch_rolls_back(store):
    store.apply(
        [
            {"op": "write", "path": "/one", "content": "one"},
            {"op": "write", "path": "/two", "bytes": b"two"},
        ]
    )
    assert store.read_text("/one") == "one"
    assert store.read_text("/two") == "two"
    with pytest.raises(LayerFSError):
        store.apply(
            [
                {"op": "write", "path": "/one", "content": "changed"},
                {"op": "edit", "path": "/missing", "oldText": "a", "newText": "b"},
            ]
        )
    assert store.read_text("/one") == "one"


def test_directory_operations(store):
    store.mkdir("/folder")
    store.write("/folder/original", "value")
    store.copy("/folder/original", "/folder/copied")
    store.move("/folder/copied", "/moved")
    assert store.read_text("/moved") == "value"
    assert store.stat("/moved")
    assert store.list("/folder")
    store.remove("/moved")
    with pytest.raises(LayerFSError):
        store.read_text("/moved")


def test_binary_and_truncation(store):
    store.write("/binary", b"\x00\xff")
    assert store.stat("/binary")
    with pytest.raises(LayerFSError) as error:
        store.read_text("/binary")
    assert error.value.code == "Binary"
    store.write("/long", "line\n" * 2100)
    result = store.read("/long")
    assert result["truncated"]
    assert result["nextLine"] is not None
    assert store.read("/long", start_line=result["nextLine"])["text"]
    with pytest.raises(LayerFSError) as error:
        store.read_text("/long")
    assert error.value.code == "Truncated"
    assert error.value.detail["truncated"]


def test_shared_handles_and_threads(store):
    second = Store.open(store.path)
    store.write("/shared", "value")
    store.close()
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: second.read_text("/shared"), range(16)))
        assert results == ["value"] * 16
    finally:
        second.close()


def test_error_and_argument_boundary(store):
    with pytest.raises(LayerFSError) as error:
        store.call("not.a.method")
    assert error.value.code
    assert error.value.message
    assert hasattr(error.value, "detail")
    with pytest.raises(TypeError):
        store.write("/wrong", object())
    with pytest.raises(TypeError):
        store.call("fs.write", unsupported=object())


@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork unavailable")
def test_inherited_handle_refuses_without_hanging(store):
    # Exercise a real child without running Python threads in the parent test.
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            "import os, sys; from layerfs import Store, LayerFSError\n"
            "s = Store(sys.argv[1])\n"
            "pid = os.fork()\n"
            "if pid == 0:\n"
            "    try:\n"
            "        Store(sys.argv[1])\n"
            "    except LayerFSError as e:\n"
            "        os._exit(0 if e.code == 'ForkedProcess' else 2)\n"
            "    os._exit(3)\n"
            "_, status = os.waitpid(pid, 0)\n"
            "s.close()\n"
            "sys.exit(os.waitstatus_to_exitcode(status))\n",
            str(store.path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert child.returncode == 0, child.stderr
