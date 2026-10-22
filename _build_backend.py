"""Maturin extension build plus the upstream-compatible native daemon commands.

Maturin's PyO3 mode builds only the extension, even when bin targets are selected.
Keep binary compilation in Cargo and add its outputs as ordinary wheel scripts.
WheelFile regenerates RECORD hashes and preserves the executable permissions.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import maturin
from wheel.wheelfile import WheelFile


def __getattr__(name):
    return getattr(maturin, name)


def _bundle(wheel_directory: str, filename: str) -> str:
    env = os.environ.copy()
    # manylinux images contain several Pythons; use this build's interpreter
    # for the bin compilation too, as Maturin does for the extension.
    env.setdefault("PYO3_PYTHON", sys.executable)
    # The commands do not embed Python. As in Maturin's extension build, avoid
    # linking libpython (manylinux deliberately omits its static library).
    env["PYO3_BUILD_EXTENSION_MODULE"] = "1"
    if platform.system() == "Darwin":
        env.setdefault(
            "MACOSX_DEPLOYMENT_TARGET",
            "11.0" if platform.machine() == "arm64" else "10.12",
        )
    built = subprocess.run(
        [
            "cargo",
            "build",
            "--manifest-path",
            "rust/Cargo.toml",
            "--locked",
            "--release",
            "--bins",
            "--message-format=json",
        ],
        check=False,
        capture_output=False,
        stdout=subprocess.PIPE,
        text=True,
        env=env,
    )
    binaries = {}
    for line in built.stdout.splitlines():
        artifact = json.loads(line)
        if artifact.get("reason") == "compiler-message":
            rendered = artifact["message"].get("rendered")
            if rendered:
                sys.stderr.write(rendered)
        if artifact.get("reason") == "compiler-artifact" and artifact.get("executable"):
            name = artifact["target"]["name"]
            if name in {"layerfs", "layerfs-daemon"}:
                binaries[name] = Path(artifact["executable"])
    built.check_returncode()
    if set(binaries) != {"layerfs", "layerfs-daemon"}:
        raise RuntimeError("Cargo did not produce both LayerFS commands")

    path = Path(wheel_directory) / filename
    with tempfile.TemporaryDirectory(dir=path.parent) as temporary:
        replacement = Path(temporary) / filename
        with zipfile.ZipFile(path) as source, WheelFile(replacement, "w") as target:
            metadata = next(
                n for n in source.namelist() if n.endswith(".dist-info/WHEEL")
            )
            scripts = metadata.removesuffix(".dist-info/WHEEL") + ".data/scripts/"
            for entry in source.infolist():
                if not entry.filename.endswith(".dist-info/RECORD"):
                    target.writestr(entry, source.read(entry))
            for name, binary in binaries.items():
                target.write(binary, scripts + name)
        os.replace(replacement, path)
    return filename


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    return _bundle(
        wheel_directory,
        maturin.build_wheel(wheel_directory, config_settings, metadata_directory),
    )


def build_editable(wheel_directory, config_settings=None, metadata_directory=None):
    return _bundle(
        wheel_directory,
        maturin.build_editable(wheel_directory, config_settings, metadata_directory),
    )
