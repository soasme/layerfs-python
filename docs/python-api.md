# Python API

[Usage guide](README.md) · [Installation](getting-started.md)

```python
from layerfs import LayerFSError, Store
```

Examples below use an open `store`, obtained with
`with Store("./app-store") as store:`. Create it first using the
[quickstart](getting-started.md). Calls run synchronously in the native Rust
engine, releasing the Python GIL while the engine works.

## Files and directories

```python
store.mkdir("/notes")
result = store.write("/notes/todo.txt", "Buy milk\n", message="Add a note")
print(result["kind"])  # Committed, or UpToDate when nothing changed.

print(store.read_text("/notes/todo.txt"))
store.edit("/notes/todo.txt", "milk", "coffee")
store.copy("/notes/todo.txt", "/notes/copy.txt")
store.move("/notes/copy.txt", "/notes/archive.txt")

info = store.stat("/notes/archive.txt")
print(info["type"], info["size"])
for entry in store.list("/notes")["items"]:
    print(entry["name"], entry["type"])

store.remove("/notes/archive.txt")
```

`write` replaces a file's content or creates the file. It accepts `str` or
`bytes`; strings become UTF-8. `edit` requires exactly one occurrence of the old
text. File mutations accept `branch="work"` and an optional `message`.
No-op mutations can return `UpToDate` instead of creating a new Commit.

```python
store.write("/payload.bin", b"\x00\xff")
```

Binary writes are supported, but this package's read methods return text.
Reading binary content raises `LayerFSError` with code `Binary`; there is no
`read_bytes()` method.

## Atomic batches

Use `apply` to commit several changes together. If one change fails, the batch
does not partially update the branch:

```python
store.apply(
    [
        {"op": "mkdir", "path": "/batch"},
        {"op": "write", "path": "/batch/one.txt", "content": "one"},
        {"op": "write", "path": "/batch/two.txt", "bytes": b"two"},
        {"op": "edit", "path": "/batch/one.txt", "oldText": "one", "newText": "1"},
    ],
    message="Add related files",
)
```

Batch dictionaries use upstream field names:

| `op` | Required fields |
| --- | --- |
| `write` | `path` and exactly one of `content` (str) or `bytes` (bytes) |
| `edit` | `path`, `oldText`, `newText` |
| `mkdir`, `rm` | `path` |
| `cp`, `mv` | `from`, `to` |

The batch's `branch` and `message` belong on `apply(...)`, not on individual
changes. Separate method calls are separate transactions; wrapping several
calls in a Store context manager does not make them atomic.

## Branches and published history

Writes default to `work`. Reads default to `ref="work"`; a read's `ref` can also
be a branch name, `"main"`, or a full immutable Commit or Layer identity.
`main` is published history and cannot be mutated with file operations.

```python
store.write("/version.txt", "original")
store.fork("draft", from_ref="work")
store.write("/version.txt", "revised", branch="draft")

assert store.read_text("/version.txt", ref="work") == "original"
assert store.read_text("/version.txt", ref="draft") == "revised"

store.publish("draft")
assert store.read_text("/version.txt", ref="main") == "revised"

print(store.branches()["items"])
print(store.commits("draft")["items"])
```

`publish(branch="work", commit=None)` publishes a branch head, or the specified
Commit, to `main`. Publishing uses the selected state; it is not a request to
merge all changes currently on `main`. `commits` lists newest first.

## Read limits and pagination

`read_text(path, ref="work")` returns a string only when the reply is complete.
It raises `Truncated` if upstream clipped it. `read` returns a dictionary with
`text`, `size`, `snapshot`, `root`, `startLine`, `endLine`, `truncated`,
`lineTruncated`, and `nextLine`:

```python
window = store.read("/notes/todo.txt", start_line=1, end_line=100)
print(window["text"])
print(window["truncated"], window["nextLine"])
```

Line numbers start at 1 and `end_line` is inclusive. Each reply is limited to
2,000 lines / 48 KiB. `lineTruncated=True` means at least one line was clipped;
line-based paging cannot recover the missing part of that line.

For consistent paging, capture an immutable Commit identity. This example
creates a new file, captures its Commit, and reads it in windows:

```python
written = store.write("/long.txt", "line\n" * 2100)
commit = written["commit"]["id"]  # This example performs a new write.
start = 1
parts = []
while True:
    page = store.read("/long.txt", ref=commit, start_line=start)
    if page["lineTruncated"]:
        raise ValueError("A line exceeds the text reply limit")
    parts.append(page["text"])
    if page["nextLine"] is None:
        break
    start = page["nextLine"]
text = "".join(parts)
assert text == "line\n" * 2100
```

For an existing branch, obtain Commit identities through `commits`. An
`UpToDate` write result does not contain a new `commit` object. The short
`snapshot` label in read results is descriptive; use the full identity as `ref`.

`list`, `branches`, and `commits` accept `page_size=50` and `page_pos=0`.
Follow `nextPagePos` until it is `None`:

```python
position = 0
while True:
    page = store.list("/", page_size=20, page_pos=position)
    for entry in page["items"]:
        print(entry["path"])
    if page["nextPagePos"] is None:
        break
    position = page["nextPagePos"]
```

Directory reads can also use an immutable `ref` while paging. Branch and Commit
listings may change between calls if other threads write concurrently.

## Other upstream operations

`call(method, **arguments)` forwards a public Store API call to the same native
engine. Arguments and result dictionaries retain upstream's camelCase names.
The Store supplies its own project identity:

```python
matches = store.call(
    "fs.grep",
    branch="work",
    path="/",
    pattern="coffee",
    pageSize=20,
    pagePos=0,
)
print(matches["items"])
```

Arguments support `None`, booleans, signed 64-bit integers, strings, bytes,
lists, tuples, and string-keyed dictionaries, with at most 16 nesting levels.
Unsupported methods raise `LayerFSError`. This entry point exposes the upstream
public Store API, not arbitrary daemon or FUSE operations.

## Errors and lifetime

```python
try:
    store.read_text("/missing.txt")
except LayerFSError as error:
    if error.code == "NoSuchPath":
        print("File is missing:", error.detail)
    else:
        raise
```

`LayerFSError` subclasses `RuntimeError` and carries `code`, `message`, and
`detail`. Invalid Python argument types can raise `TypeError`, `ValueError`, or
`OverflowError` before an engine call. Operations are not automatically retried;
inspect a refusal before deciding what your application should do next.

| Method or property | Behavior |
| --- | --- |
| `Store.create(path, source=None, project="default", timeout=60.0)` | Create a new Store; options are keyword-only. |
| `Store(path)` / `Store.open(path)` | Open an existing Store. |
| `store.path` | Absolute path to the Store directory on the host. |
| `store.closed` | Whether this handle has been closed. |
| `store.close()` | Release this handle; repeated calls are harmless. |

Prefer `with Store(...) as store:`. Closing the last handle closes the shared
engine. Other handles to the same canonical directory remain usable when one
handle closes. Methods on a closed handle raise `Closed`.

Threads may share a handle; calls release the GIL. Concurrent mutations can
still produce a `Conflict` refusal when changes overlap. A handle cannot cross
`fork`, and a child that inherits an initialized binding must use a fresh
spawned process for Store operations. For multiprocessing, use the `spawn`
start method and open the Store inside the worker. Coordinate ownership across
processes and daemon deployments yourself: the handle registry is local to a
single process.

Stores use SQLite's Disposable profile (`WAL`, `synchronous=OFF`). Normal
close/reopen is supported, but power-loss and OS-crash durability are not
guaranteed.
