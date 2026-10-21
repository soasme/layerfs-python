from os import PathLike
from typing import Any

class LayerFSError(RuntimeError):
    code: str
    message: str
    detail: Any

class NativeStore:
    @staticmethod
    def open(path: str | PathLike[str]) -> NativeStore: ...
    @staticmethod
    def create(
        path: str | PathLike[str],
        source: str | PathLike[str] | None = None,
        project: str = "default",
        timeout: float = 60.0,
    ) -> NativeStore: ...
    @property
    def closed(self) -> bool: ...
    def close(self) -> None: ...
    def call(self, method: str, args: dict[str, Any]) -> dict[str, Any]: ...
