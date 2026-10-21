from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import layerfs
import pytest
from layerfs import __main__ as launcher
from layerfs import _find_layerfs as finder


@pytest.fixture
def isolated_paths(monkeypatch, tmp_path):
    """Keep discovery tests independent of any real installed daemon."""
    monkeypatch.setattr(finder.sysconfig, "get_config_var", lambda name: "")
    monkeypatch.setattr(
        finder.sysconfig,
        "get_path",
        lambda name, **kwargs: str(tmp_path / "scripts"),
    )
    monkeypatch.setattr(finder, "__file__", str(tmp_path / "src/layerfs/__init__.py"))
    return tmp_path


def executable(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(0o755)
    return str(path.resolve())


def test_find_scripts_install(isolated_paths):
    expected = executable(isolated_paths / "scripts/layerfs-daemon")
    assert layerfs.find_layerfs_bin() == expected


@pytest.mark.parametrize(
    ("package", "binary"),
    [
        ("target/layerfs", "target/bin/layerfs-daemon"),
        ("prefix/lib/python3.12/site-packages/layerfs", "prefix/bin/layerfs-daemon"),
        ("prefix/lib64/python3.12/site-packages/layerfs", "prefix/bin/layerfs-daemon"),
    ],
)
def test_package_install_takes_precedence(isolated_paths, monkeypatch, package, binary):
    executable(isolated_paths / "scripts/layerfs-daemon")
    expected = executable(isolated_paths / binary)
    monkeypatch.setattr(
        finder, "__file__", str(isolated_paths / package / "__init__.py")
    )
    assert layerfs.find_layerfs_bin() == expected


def test_missing_binary_is_actionable(isolated_paths):
    with pytest.raises(layerfs.LayerFSNotFound, match="Install a built wheel"):
        layerfs.find_layerfs_bin()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX executable permissions")
def test_non_executable_is_not_selected(isolated_paths):
    path = Path(executable(isolated_paths / "scripts/layerfs-daemon"))
    path.chmod(0o644)
    with pytest.raises(layerfs.LayerFSNotFound):
        layerfs.find_layerfs_bin()


def test_launcher_preserves_arguments(monkeypatch):
    calls = []
    monkeypatch.setattr(launcher.sys, "platform", "linux")
    monkeypatch.setattr(launcher.sys, "argv", ["layerfs", "--config", "/a path/config"])
    monkeypatch.setattr(launcher, "find_layerfs_bin", lambda: "/env/bin/layerfs-daemon")
    monkeypatch.setattr(launcher.os, "execv", lambda *args: calls.append(args))
    launcher.main()
    assert calls == [
        (
            "/env/bin/layerfs-daemon",
            ["/env/bin/layerfs-daemon", "--config", "/a path/config"],
        )
    ]


def test_installed_module_matches_binary():
    """Exercise the real wheel without starting a daemon or opening a Store."""
    binary = layerfs.find_layerfs_bin()
    direct = subprocess.run([binary], capture_output=True, timeout=10)
    module = subprocess.run(
        [sys.executable, "-m", "layerfs"], capture_output=True, timeout=10
    )
    assert direct.returncode == 1
    assert b"usage: layerfs-daemon --config <protected-file>" in direct.stderr
    assert (module.returncode, module.stdout, module.stderr) == (
        direct.returncode,
        direct.stdout,
        direct.stderr,
    )
