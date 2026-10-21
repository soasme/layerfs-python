# LayerFS for Python

Use the [LayerFS](https://github.com/Ephemeral-AI-Lab/layerfs) Rust engine directly
inside a Python application, or run its bundled daemon for FUSE deployments.
Python 3.9+ is supported. Store operations require **Linux on ext4, XFS, or Btrfs**;
the upstream engine refuses other platforms and filesystems.

## In-process usage

Install a built wheel with `pip install /path/to/layerfs-*.whl`. Applications
using the following API need no daemon, socket, container, FUSE mount, or root
privileges. Native calls release the Python GIL.

```python
from layerfs import Store

with Store.create("./app-store") as store:
    store.write("/hello.txt", "Hello from Python!\n")
    print(store.read_text("/hello.txt"))
    store.edit("/hello.txt", "Python", "LayerFS")

# Reopen the same directory in a later application run.
with Store("./app-store") as store:
    print(store.read_text("/hello.txt"))
```

`Store.create(path, source="./existing-tree", project="my-app")` imports a
directory, including ignored files. Omit `source` for an empty tree. The parent
directory must exist, and the destination must be new and outside the source.
Initialization has a configurable `timeout` in seconds (default 60). Failed
initialization retains any created output; the error's `detail["path"]` identifies
it. Store directories contain `store.sqlite` and private authority metadata;
keep those files together.

Each mutation creates a Commit on the `work` branch by default. Batch related
changes into one atomic Commit with `apply`:

```python
with Store("./app-store") as store:
    store.apply([
        {"op": "write", "path": "/one.txt", "content": "one"},
        {"op": "write", "path": "/two.txt", "content": "two"},
    ])
    store.fork("draft")
    store.write("/one.txt", "revised", branch="draft")
    print(store.read_text("/one.txt", ref="draft"))
    store.publish("draft")  # Advance the published main history explicitly.
```

`mkdir`, `list`, `stat`, `copy`, `move`, `remove`, `branches`, and `commits` provide
the corresponding operations. `write` accepts strings or bytes. `read` returns
upstream's text window and metadata; binary reads raise `LayerFSError` with code
`Binary`. Text replies are limited to 2,000 lines / 48 KiB: inspect `truncated`,
`lineTruncated`, and `nextLine`, and use `start_line` / `end_line` to select a
window. `read_text` raises `Truncated` instead of silently returning partial data.
For consistent paging while writers are active, use an immutable Commit as `ref`.

Operation results retain upstream's dictionary fields and camelCase names.
`store.call("fs.grep", ...)` exposes other methods in the upstream public Store
API. Errors retain their structured information:

```python
from layerfs import LayerFSError

with Store("./app-store") as store:
    try:
        store.read_text("/missing.txt")
    except LayerFSError as error:
        print(error.code, error.message, error.detail)
```

Use a context manager or call `close()`. Multiple handles for the same canonical
directory share an engine within the process; closing one leaves the others
usable. Threads may share a handle. Handles cannot cross `fork`; use spawned
processes and open a Store there. Coordinate ownership between processes and
daemon deployments; the Python handle registry only coordinates this process.

Upstream currently exposes the **Disposable** SQLite profile (`WAL`,
`synchronous=OFF`). Successful writes survive a normal close/reopen, but this
profile does not guarantee durability after power loss or an OS crash.

## Daemon and FUSE

The existing native commands remain available:

```sh
layerfs --config /absolute/path/to/protected-config
layerfs-daemon --config /absolute/path/to/protected-config
python3 -m layerfs --config /absolute/path/to/protected-config
```

`layerfs` and `python3 -m layerfs` show help with no arguments and support `--help`
and `--version`. `layerfs-daemon` retains upstream's exact CLI. The daemon requires
the protected configuration, credentials, permissions, and FUSE environment
described in the [upstream SDK guide](https://github.com/Ephemeral-AI-Lab/layerfs/blob/main/sdk/js/README.md).
`Store.create` is for direct application use and does not configure a daemon
deployment. `layerfs.find_layerfs_bin()` locates the installed command.

A macOS wheel supports import and CLI help, but actual Store/FUSE operations
still require Linux. Windows is not supported.

## Build from source

The upstream source is pinned as a Git submodule at `upstream/layerfs`. Builds
compile that source; they do not download a prebuilt LayerFS executable.
Following [Ruff's Rust/Python packaging approach](https://github.com/astral-sh/ruff/blob/main/pyproject.toml),
Maturin packages the native code alongside a small Python module. This package
uses PyO3's Python 3.9 stable ABI for the in-process extension. A small PEP 517
backend also compiles and bundles the two native commands into the same wheel.

Requires Rust/Cargo compatible with the pinned dependencies, a C/C++ build
toolchain, and Python 3.9+. For local development:

```sh
git submodule update --init --recursive
uv sync
uv run layerfs
uv run python3 -m layerfs
uv run python3 -c 'from layerfs import Store; print(Store)'
```

To build distributable wheels and a self-contained source archive:

```sh
uv build
# Or: python3 -m pip install build && python3 -m build
```

Use the PEP 517 build (`uv build`, `python -m build`, or `pip install .`) so the
extension and daemon binaries are all included. For editable installations use
`uv sync` or `pip install -e .`. Direct `maturin build/develop` only builds the
extension and bypasses the binary bundling step. Source archives include the
required upstream code and need no submodule checkout.

An unactivated system `python3` does not use `.venv`. Activate it before running
`python3 -m layerfs`, or install the wheel into that interpreter. For Apple's
system Python, use `python3 -m pip install --user /path/to/the-built-wheel.whl`.

For checks after installation:

```sh
uv pip install pytest ruff
uv run --no-sync pytest -q
uv run --no-sync ruff check python tests _build_backend.py
cargo fmt --manifest-path rust/Cargo.toml --check
```

Run the Store integration tests on a supported Linux filesystem. macOS tests
exercise import, the platform refusal, and both command entry points. CI builds
the wheel from the source archive to verify that all required code is included.

The root `.cargo/config.toml` mirrors upstream's ARM cryptography and SQLite
settings. If setting `RUSTFLAGS` externally, preserve those ARM flags on aarch64.
The package version comes from `rust/Cargo.toml`.

## Update upstream

```sh
git -C upstream/layerfs fetch origin
git -C upstream/layerfs checkout <reviewed-tag-or-commit>
git -C upstream/layerfs submodule update --init --recursive
git diff --submodule=log
```

Review the upstream API, Cargo manifest, lockfile, and `.cargo/config.toml`.
Update `rust/Cargo.toml` and `rust/Cargo.lock` as needed. The packaging crate's
Cargo patch must continue to point at upstream's vendored FUSE crate. Rebuild
the wheel and source archive and run installed-package tests before committing
the submodule update. The upstream checkout remains unmodified by this package.

## License

MIT. The upstream license is included with the distributions.
