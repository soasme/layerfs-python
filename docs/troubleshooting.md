# Troubleshooting

[Usage guide](README.md)

## Python cannot import layerfs

Install into the interpreter that runs your application. `uv sync` installs
into the project's `.venv`; an unactivated system `python3` uses a different
environment.

```sh
uv run python3 -c 'import sys, layerfs; print(sys.executable, layerfs.__file__)'
```

Use `uv run python3 -m layerfs`, or activate `.venv` before using `python3`.
For another interpreter, install the matching wheel with that interpreter's
`python3 -m pip install /path/to/the-wheel.whl`. Copying the Python source alone
is insufficient because the package requires its compiled extension.

## The command is missing

If Python imports the package but your shell cannot find `layerfs`, use
`python3 -m layerfs --help` from the installed environment. Check that the
environment's executable directory is on `PATH`.

If `find_layerfs_bin()` raises `LayerFSNotFound`, reinstall a complete wheel or
rebuild with `uv sync` / `pip install .`. Direct `maturin develop` only builds
the extension and does not bundle the daemon commands.

## Store creation raises Unsupported

Upstream requires Linux and checks the backing filesystem. Supported types are
ext4, XFS, and Btrfs. macOS, tmpfs, and overlayfs are unsupported even if the
package can be installed. In a container, choose a Store location whose backing
filesystem passes this check; merely using a Linux container is insufficient.
Do not infer Store support from a successful `--help` or `--version` invocation.

## Common API refusals

Inspect `LayerFSError.code`, `.message`, and `.detail`:

| Code | Meaning and next step |
| --- | --- |
| `Exists` | `create` found an existing destination. Reopen a valid Store with `Store(path)` or choose a new destination. |
| `NoSuchPath` | The internal path does not exist at the selected `ref`. Check the path and branch. |
| `Binary` | A text read encountered binary content. The current Python API has no binary read method. |
| `Truncated` | `read_text` could not return the complete text. Use `read` and inspect its paging and clipping fields. |
| `Closed` | This handle has been closed. Open another handle. |
| `ForkedProcess` | Store state was inherited across `fork`. Use a fresh spawned process. |
| `Conflict` | A concurrent update overlapped the mutation. Inspect the refusal and reconcile before submitting a new operation. |
| `InvalidStore` | Store metadata is invalid or incomplete. Check the directory and preserve its files for inspection. |

Other upstream refusal codes are passed through. Python argument conversion can
also raise ordinary `TypeError`, `ValueError`, or `OverflowError` exceptions.

If creation fails after producing output, the error's `detail["path"]` names
the retained directory. Calling `create` on that directory again will not repair
or overwrite it. Inspect the original error before proceeding.

## Updates do not appear where expected

Writes go to `work` by default. `main` changes only when you call `publish`.
Use the same branch for writing and reading:

```python
store.write("/note.txt", "draft", branch="draft")
print(store.read_text("/note.txt", ref="draft"))
```

Create `draft` with `store.fork("draft")` first. Internal paths such as
`/note.txt` live in the Store and do not create files at the corresponding host
paths. Use `apply` when several mutations must succeed together.

See [read limits and pagination](python-api.md#read-limits-and-pagination) when
only part of a file is returned by `read`.
