"""Synchronous, in-process file and branch operations over the upstream engine."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Union

from ._native import LayerFSError, NativeStore

PathLike = Union[str, os.PathLike[str]]
Result = dict[str, Any]


class Store:
    """One handle to a local LayerFS Store; use as a context manager.

    Store paths name directories containing store.sqlite and private metadata.
    Calls execute in Rust in this Python process with the GIL released. Linux
    with ext4, xfs or btrfs is required; no daemon, Docker or FUSE is involved.
    Writes commit immediately to the ``work`` branch by default. ``main`` is
    the published history, updated explicitly with :meth:`publish`.
    """

    def __init__(self, path: PathLike):
        self.path = Path(path).absolute()
        self._handle = NativeStore.open(self.path)

    @classmethod
    def open(cls, path: PathLike) -> Store:
        """Reopen an existing Store, including from a fresh process."""
        return cls(path)

    @classmethod
    def create(
        cls,
        path: PathLike,
        *,
        source: PathLike | None = None,
        project: str = "default",
        timeout: float = 60.0,
    ) -> Store:
        """Create a new Store from a directory, or an empty tree.

        The parent must exist; an existing destination is never overwritten.
        The source is imported completely, including ignored files. A failure
        after creation retains its output; its exception's detail names the path.
        Upstream uses its Disposable profile (WAL, synchronous=OFF).
        """
        store = cls.__new__(cls)
        store.path = Path(path).absolute()
        store._handle = NativeStore.create(
            store.path,
            None if source is None else Path(source).absolute(),
            project,
            timeout,
        )
        return store

    @property
    def closed(self) -> bool:
        return self._handle.closed

    def close(self) -> None:
        """Release this handle; the last handle closes the shared Store."""
        self._handle.close()

    def __enter__(self) -> Store:
        if self.closed:
            # Use the native boundary for the same structured Closed error.
            self._handle.call("project.list_branches", {})
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def call(self, method: str, **arguments: Any) -> Result:
        """Run one upstream public Store method, returning its exact result.

        Arguments and result fields use upstream's camelCase names. This is
        also an escape hatch for methods without a convenience wrapper here.
        Unsupported methods raise LayerFSError; operations are never retried.
        """
        return self._handle.call(method, arguments)

    def read(
        self,
        path: str,
        *,
        ref: str = "work",
        start_line: int = 1,
        end_line: int | None = None,
    ) -> Result:
        """Read a text window with truncation flags and nextLine.

        Upstream caps each reply at 2,000 lines / 48 KiB; inspect ``truncated``
        and ``lineTruncated``. Binary content is refused as ``Binary``.
        """
        return self.call(
            "fs.read", path=path, branch=ref, startLine=start_line, endLine=end_line
        )

    def read_text(self, path: str, *, ref: str = "work") -> str:
        """Read a small text file, refusing to silently return truncated data."""
        result = self.read(path, ref=ref)
        if result["truncated"]:
            error = LayerFSError("Truncated: use read() to inspect or page the text")
            error.code = "Truncated"
            error.message = "use read() to inspect or page the text"
            error.detail = result
            raise error
        return result["text"]

    def write(
        self,
        path: str,
        content: str | bytes,
        *,
        branch: str = "work",
        message: str | None = None,
    ) -> Result:
        """Write text or bytes and publish one Commit to the selected branch."""
        if not isinstance(content, (str, bytes)):
            raise TypeError("content must be str or bytes")
        body = {"bytes" if isinstance(content, bytes) else "content": content}
        return self.call("fs.write", path=path, branch=branch, message=message, **body)

    def edit(
        self,
        path: str,
        old_text: str,
        new_text: str,
        *,
        branch: str = "work",
        message: str | None = None,
    ) -> Result:
        """Replace exactly one matching text occurrence in one Commit."""
        return self.call(
            "fs.edit",
            path=path,
            oldText=old_text,
            newText=new_text,
            branch=branch,
            message=message,
        )

    def apply(
        self,
        changes: list[Result],
        *,
        branch: str = "work",
        message: str | None = None,
    ) -> Result:
        """Commit a batch of write/edit/mkdir/rm/cp/mv changes atomically."""
        return self.call("fs.apply", changes=changes, branch=branch, message=message)

    def stat(self, path: str, *, ref: str = "work") -> Result:
        return self.call("fs.stat", path=path, branch=ref)

    def list(
        self,
        path: str = "/",
        *,
        ref: str = "work",
        page_size: int = 50,
        page_pos: int = 0,
    ) -> Result:
        return self.call(
            "fs.list", path=path, branch=ref, pageSize=page_size, pagePos=page_pos
        )

    def mkdir(
        self, path: str, *, branch: str = "work", message: str | None = None
    ) -> Result:
        return self.call("fs.mkdir", path=path, branch=branch, message=message)

    def remove(
        self, path: str, *, branch: str = "work", message: str | None = None
    ) -> Result:
        return self.call("fs.rm", path=path, branch=branch, message=message)

    def copy(
        self,
        source: str,
        destination: str,
        *,
        branch: str = "work",
        message: str | None = None,
    ) -> Result:
        return self.call(
            "fs.cp",
            **{"from": source, "to": destination, "branch": branch, "message": message},
        )

    def move(
        self,
        source: str,
        destination: str,
        *,
        branch: str = "work",
        message: str | None = None,
    ) -> Result:
        return self.call(
            "fs.mv",
            **{"from": source, "to": destination, "branch": branch, "message": message},
        )

    def fork(self, name: str, *, from_ref: str = "work") -> Result:
        return self.call("branch.fork", **{"name": name, "from": from_ref})

    def publish(self, branch: str = "work", *, commit: str | None = None) -> Result:
        """Publish a branch's state to main."""
        return self.call("branch.publish", branch=branch, commit=commit)

    def branches(self, *, page_size: int = 50, page_pos: int = 0) -> Result:
        return self.call("project.list_branches", pageSize=page_size, pagePos=page_pos)

    def commits(
        self, branch: str = "work", *, page_size: int = 50, page_pos: int = 0
    ) -> Result:
        return self.call(
            "branch.list_commits", branch=branch, pageSize=page_size, pagePos=page_pos
        )
