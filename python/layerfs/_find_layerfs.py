"""Locate Maturin's installed executable, following Ruff's packaging model."""

from __future__ import annotations

import os
import sys
import sysconfig
from pathlib import Path


class LayerFSNotFound(FileNotFoundError):
    """The Python package's compiled daemon could not be found."""


def find_layerfs_bin() -> str:
    """Return the installed ``layerfs`` executable's absolute path.

    Supports virtual environments, user installs, and pip's ``--prefix`` and
    ``--target`` layouts. Does not select an unrelated executable from PATH.
    """
    name = "layerfs" + (sysconfig.get_config_var("EXE") or "")
    package = Path(__file__).resolve().parent
    scripts = "Scripts" if sys.platform == "win32" else "bin"
    candidates = [Path(sysconfig.get_path("scripts"))]

    # Prefer the executable shipped beside this package for --target installs.
    candidates.insert(0, package.parent / "bin")
    # <prefix>/lib/pythonX.Y/site-packages/layerfs, including lib64 layouts.
    if (
        package.parent.name == "site-packages"
        and package.parent.parent.name.startswith("python")
        and package.parent.parent.parent.name in {"lib", "lib64"}
    ):
        candidates.insert(0, package.parents[3] / scripts)
    elif (
        package.parent.name.lower() == "site-packages"
        and package.parent.parent.name.lower() == "lib"
    ):
        candidates.insert(0, package.parents[2] / scripts)

    candidates.extend(
        [
            Path(sysconfig.get_path("scripts", vars={"base": sys.base_prefix})),
            Path(sysconfig.get_path("scripts", scheme=_user_scheme())),
        ]
    )
    paths = list(dict.fromkeys(directory / name for directory in candidates))
    for path in paths:
        if path.is_file() and os.access(path, os.X_OK):
            return str(path.resolve())
    locations = "\n".join(f"  {path}" for path in paths)
    raise LayerFSNotFound(
        "The compiled layerfs executable is missing. "
        "Install a built wheel or build the package with Maturin.\n"
        f"Searched:\n{locations}"
    )


def _user_scheme() -> str:
    if sys.version_info >= (3, 10):
        return sysconfig.get_preferred_scheme("user")
    if os.name == "nt":
        return "nt_user"
    if sys.platform == "darwin" and getattr(sys, "_framework", ""):
        return "osx_framework_user"
    return "posix_user"
