# Installation and quickstart

[Usage guide](README.md)

## Install a wheel

Choose a wheel matching your operating system and CPU architecture. The native
extension supports CPython 3.9 and later through Python's stable ABI. Installing
a built wheel does not require Rust.

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install /path/to/layerfs-wheel.whl
python3 -c 'from layerfs import Store; print(Store)'
python3 -m layerfs --version
```

Replace `/path/to/layerfs-wheel.whl` with the actual wheel filename. To add it to
an existing uv application, run `uv add /path/to/layerfs-wheel.whl`, then run your
application with `uv run python app.py`.

## Install from this checkout

Building from source requires Rust/Cargo compatible with the pinned upstream
dependencies and a C/C++ toolchain. Initialize the submodule first:

```sh
git submodule update --init --recursive
uv sync
uv run python3 -c 'from layerfs import Store; print(Store)'
uv run layerfs --help
```

Without uv, activate a virtual environment and use `python3 -m pip install .`.
Use `python3 -m pip install -e .` for editable development. `uv build` produces
wheels and a source archive in `dist/`; source archives already contain the
required upstream code.

Use these PEP 517 build commands to include both the extension and native
commands. Direct `maturin build` or `maturin develop` bypasses the package's
binary bundling step.

## Create, update, and reopen

Run this on Linux with the current directory on ext4, XFS, or Btrfs. Save it as
`app.py` and run `python3 app.py` (or `uv run python app.py`):

```python
from pathlib import Path

from layerfs import Store

store_path = Path("app-store")

# Run creation once. The destination must not already exist.
with Store.create(store_path) as store:
    store.write("/hello.txt", "Hello from Python!\n")
    store.edit("/hello.txt", "Python", "LayerFS")
    assert store.read_text("/hello.txt") == "Hello from LayerFS!\n"

# A later application run can open the same Store.
with Store.open(store_path) as store:
    print(store.read_text("/hello.txt"))
```

On subsequent runs, use `Store(store_path)` or `Store.open(store_path)` without
calling `create` again. `create` refuses existing destinations, including empty
directories. The destination's parent directory must already exist.

`app-store` is a directory on the host containing the SQLite Store and its
private metadata. `/hello.txt` is a path **inside LayerFS**, not a file created at
the host's `/hello.txt`. File paths passed to Store operations must be absolute
within the Store, starting with `/`.

Every successful mutation commits to `work` by default; `close()` releases the
handle rather than acting as a transaction commit. Use a context manager to
close it even when an operation raises an exception.

## Import existing files

```python
from layerfs import Store

with Store.create(
    "./imported-store",
    source="./existing-files",
    project="my-app",
    timeout=120.0,
) as store:
    print(store.list("/"))
```

The source must be an existing directory. Import includes ignored files and
creates a snapshot; it does not keep the source directory synchronized. Place
the Store outside the source directory. `project` defaults to `"default"`, and
`timeout` defaults to 60 seconds and must be finite and positive.

If initialization fails after creating output, it leaves that output in place
and includes its path in `LayerFSError.detail`. Inspect it before choosing a
new destination. Keep `store.sqlite`, `manifest.bin`, and `project` together when
handling a closed Store directory; the SQLite file alone is insufficient to
reopen through this API.

Continue with the [Python API](python-api.md) for batches and branches.
