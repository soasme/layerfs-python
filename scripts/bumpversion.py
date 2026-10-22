#!/usr/bin/env python3
"""Preview a release in a temporary clone; pass -y to commit, tag, and push."""

from __future__ import annotations

import argparse
import re
import subprocess
import tempfile
from pathlib import Path

VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
MANIFEST_VERSION = re.compile(r'(?ms)^\[package\]\n(?:(?!^\[).)*?^version = "([^"]+)"$')
LOCK_VERSION = re.compile(
    r'(?m)^\[\[package\]\]\nname = "layerfs-python"\nversion = "([^"]+)"$'
)
RELEASE_FILES = ("CHANGELOG.md", "rust/Cargo.toml", "rust/Cargo.lock")


def run(*args: str, cwd: Path) -> str:
    return subprocess.run(
        args, cwd=cwd, check=True, text=True, capture_output=True
    ).stdout.strip()


def run_checked(*args: str, cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True)


def version_match(path: Path, pattern: re.Pattern[str]) -> re.Match[str]:
    matches = list(pattern.finditer(path.read_text(encoding="utf-8")))
    if len(matches) != 1 or not VERSION.fullmatch(matches[0].group(1)):
        raise RuntimeError(f"Expected one major.minor.patch package version in {path}")
    return matches[0]


def current_version(root: Path) -> str:
    version = version_match(root / "rust/Cargo.toml", MANIFEST_VERSION).group(1)
    locked = version_match(root / "rust/Cargo.lock", LOCK_VERSION).group(1)
    if locked != version:
        raise RuntimeError("rust/Cargo.toml and rust/Cargo.lock versions disagree")
    return version


def bumped_version(version: str, part: str) -> str:
    if not VERSION.fullmatch(version):
        raise ValueError(f"Invalid release version: {version}")
    major, minor, patch = map(int, version.split("."))
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    if part == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise ValueError(f"Unknown version component: {part}")


def release_entries(root: Path) -> list[str]:
    history = run("git", "log", "--format=%H%x00%s", cwd=root).splitlines()
    entries = []
    for line in history:
        _, subject = line.split("\0", 1)
        if subject.startswith("chore(release): "):
            break
        entries.append(f"- {subject.rstrip('.')}")
    if not entries:
        raise RuntimeError("No changes since the previous release")
    return entries


def prepare_release(root: Path, part: str) -> str:
    version = bumped_version(current_version(root), part)
    if run("git", "tag", "--list", f"v{version}", cwd=root):
        raise RuntimeError(f"Tag v{version} already exists")
    entries = release_entries(root)
    changelog = root / "CHANGELOG.md"
    previous = changelog.read_text(encoding="utf-8")
    header = "# Changelog\n\n"
    if not previous.startswith(header) or f"## {version}\n" in previous:
        raise RuntimeError("Unexpected changelog header or duplicate release version")
    for filename, pattern in (
        ("rust/Cargo.toml", MANIFEST_VERSION),
        ("rust/Cargo.lock", LOCK_VERSION),
    ):
        path = root / filename
        text = path.read_text(encoding="utf-8")
        match = version_match(path, pattern)
        path.write_text(
            text[: match.start(1)] + version + text[match.end(1) :], encoding="utf-8"
        )
    changelog.write_text(
        header
        + f"## {version}\n\n"
        + "\n".join(entries)
        + "\n\n"
        + previous[len(header) :],
        encoding="utf-8",
    )
    return version


def verify_release(root: Path) -> None:
    run_checked(
        "cargo", "fmt", "--manifest-path", "rust/Cargo.toml", "--check", cwd=root
    )
    for command in ("check", "format"):
        run_checked(
            "uv",
            "tool",
            "run",
            "ruff",
            command,
            *(["--check"] if command == "format" else []),
            "python",
            "tests",
            "scripts",
            "_build_backend.py",
            cwd=root,
        )
    # uv builds the wheel from the sdist, exercising the packaged upstream code.
    run_checked("uv", "build", cwd=root)
    wheels = list((root / "dist").glob("*.whl"))
    if len(wheels) != 1:
        raise RuntimeError("Expected exactly one freshly built wheel")
    run_checked(
        "uv",
        "run",
        "--no-project",
        "--isolated",
        "--python",
        "3.9",
        "--with",
        "pytest",
        "--with",
        str(wheels[0]),
        "python",
        "-m",
        "pytest",
        "-q",
        cwd=root,
    )
    run_checked(
        "uv",
        "tool",
        "run",
        "twine",
        "check",
        "--strict",
        *(str(path) for path in sorted((root / "dist").glob("*.whl"))),
        *(str(path) for path in sorted((root / "dist").glob("*.tar.gz"))),
        cwd=root,
    )


def commit_release(root: Path, version: str, branch: str) -> None:
    run_checked("git", "add", *RELEASE_FILES, cwd=root)
    run_checked("git", "commit", "-m", f"chore(release): {version}", cwd=root)
    run_checked("git", "tag", "-a", f"v{version}", "-m", f"Release {version}", cwd=root)
    # Publish the branch and tag together, or neither if either ref has moved.
    run_checked(
        "git",
        "push",
        "--atomic",
        "origin",
        f"HEAD:refs/heads/{branch}",
        f"refs/tags/v{version}",
        cwd=root,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("part", choices=("major", "minor", "patch"))
    parser.add_argument(
        "--branch", default="main", help="remote branch (default: main)"
    )
    parser.add_argument(
        "-y", "--yes", action="store_true", help="commit, tag, and push"
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    run("git", "check-ref-format", "--branch", args.branch, cwd=root)
    origin = run("git", "remote", "get-url", "origin", cwd=root)
    # Like rio, release the remote branch without changing the caller's checkout.
    with tempfile.TemporaryDirectory(prefix="layerfs-bumpversion-") as temporary:
        clone = Path(temporary) / "layerfs-python"
        print(
            f"Cloning origin/{args.branch} and pinned upstream sources...", flush=True
        )
        run_checked(
            "git",
            "clone",
            "--quiet",
            "--branch",
            args.branch,
            "--",
            origin,
            str(clone),
            cwd=root,
        )
        cached = root / "upstream/layerfs"
        reference = (
            ["--reference", str(cached), "--dissociate"]
            if (cached / ".git").exists()
            else []
        )
        # Borrow only Git objects, never working files; the checkout still uses
        # the remote branch's pinned commit and becomes independent afterward.
        run_checked(
            "git",
            "submodule",
            "update",
            "--init",
            "--recursive",
            "--depth=1",
            *reference,
            cwd=clone,
        )
        run(
            "git",
            "rev-parse",
            "--verify",
            f"refs/remotes/origin/{args.branch}",
            cwd=clone,
        )
        for key in ("user.name", "user.email"):
            run_checked(
                "git", "config", key, run("git", "config", key, cwd=root), cwd=clone
            )
        version = prepare_release(clone, args.part)
        verify_release(clone)
        print(f"Release plan: {args.branch} -> v{version}", flush=True)
        print(run("git", "diff", "--", *RELEASE_FILES, cwd=clone), flush=True)
        if args.yes:
            commit_release(clone, version, args.branch)
            print(f"Pushed v{version}; Publish will build, test, then publish to PyPI.")
        else:
            print("Preview only. Rerun with -y to commit, tag, and push.")


if __name__ == "__main__":
    main()
