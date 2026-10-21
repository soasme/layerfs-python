# LayerFS for Python

Build and install the [LayerFS](https://github.com/Ephemeral-AI-Lab/layerfs)
Rust daemon as a Python package. This repository follows
[Ruff's packaging model](https://github.com/astral-sh/ruff/blob/main/pyproject.toml):
Maturin's `bin` bindings compile the upstream Rust executable and include it
alongside a small Python module in a platform-specific wheel.

The upstream source is pinned by the Git submodule at `upstream/layerfs`.
The Rust entry point calls `layerfs_daemon::application::main()` directly.
Builds use that source and this repository's Cargo lockfile, derived from the
upstream lockfile; no executable is downloaded at installation time. The package
version comes from `rust/Cargo.toml` and tracks the packaged upstream release.

## Usage

After installing a built wheel, these launch the same daemon:

```sh
layerfs-daemon --config /absolute/path/to/protected-config
python -m layerfs --config /absolute/path/to/protected-config
```

The executable is also available to Python callers:

```python
import subprocess
from layerfs import find_layerfs_bin

subprocess.run(
    [find_layerfs_bin(), "--config", "/absolute/path/to/protected-config"],
    check=True,
)
```

This package distributes the daemon; it does not provide Python bindings for
upstream's filesystem, project, branch, or Workspace APIs. It does not create
a Store, provision containers, or generate daemon credentials. See the
[upstream SDK guide](https://github.com/Ephemeral-AI-Lab/layerfs/blob/main/sdk/js/README.md)
for deployment requirements. The daemon expects a protected configuration file;
running it without arguments prints its usage and exits with status 1.

Running a filesystem daemon requires Linux, FUSE, and the permissions and Store
configuration required by upstream. A wheel can compile on macOS, but this does
not make upstream's Linux Store and FUSE operations available on macOS. Windows
is not a supported build or runtime target.

## Build from source

Requires Python 3.10+, Rust/Cargo compatible with the pinned upstream dependencies,
a C/C++ build toolchain, and upstream's native library requirements.

```sh
git submodule update --init --recursive
python -m venv .venv
. .venv/bin/activate
python -m pip install 'maturin>=1.15,<2' pytest
maturin build --release --out dist
python -m pip install dist/*.whl
python -m pytest
```

For an editable development installation use `maturin develop`. PEP 517 tools
also work: `python -m pip install .` or `uv build`. Initialize the submodule
before building from a Git checkout. Published source archives contain the
required upstream sources and do not need Git or a submodule checkout.

The root `.cargo/config.toml` mirrors upstream's required ARM cryptography and
SQLite settings because Cargo discovers config from its working directory.
If setting `RUSTFLAGS` externally, preserve those ARM flags on aarch64.

## Update upstream

```sh
git -C upstream/layerfs fetch origin
git -C upstream/layerfs checkout <reviewed-tag-or-commit>
git -C upstream/layerfs submodule update --init --recursive
git diff --submodule=log
```

Review the upstream Cargo manifest, lockfile and `.cargo/config.toml` for changes.
Update `rust/Cargo.toml` and `rust/Cargo.lock` when changing upstream dependencies.
The packaging crate's Cargo patch must continue to point at upstream's vendored
FUSE crate. Maturin 1.15+ is required to package dependencies from the separate
upstream Cargo workspace.
Then rebuild the wheel and source archive and run the installed-package tests
before committing the new submodule pointer. The upstream checkout remains
unmodified by this package.

## License

MIT. The upstream license is included with the distributions.
