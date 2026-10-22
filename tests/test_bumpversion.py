"""Exercise version updates and preview/publish against disposable Git repositories."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "bumpversion", Path(__file__).resolve().parents[1] / "scripts/bumpversion.py"
)
assert SPEC and SPEC.loader
bumpversion = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bumpversion)


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "--initial-branch=main")
    git(root, "config", "user.name", "Release Test")
    git(root, "config", "user.email", "release@example.invalid")
    (root / "rust").mkdir()
    (root / "rust/Cargo.toml").write_text(
        '[package]\nname = "layerfs-python"\nversion = "1.2.3"\n'
        '[dependencies]\ntempfile = "=3.23.0"\n'
    )
    (root / "rust/Cargo.lock").write_text(
        'version = 4\n\n[[package]]\nname = "layerfs-python"\nversion = "1.2.3"\n'
        '\n[[package]]\nname = "layerfs-api"\nversion = "1.0.0"\n'
    )
    (root / "CHANGELOG.md").write_text("# Changelog\n\n## 1.2.3\n\n- Previous\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "chore(release): 1.2.3")
    git(root, "commit", "--allow-empty", "-m", "feat: add an operation")
    return root


@pytest.mark.parametrize(
    "part, expected", [("patch", "1.2.4"), ("minor", "1.3.0"), ("major", "2.0.0")]
)
def test_updates_only_package_version(
    repository: Path, part: str, expected: str
) -> None:
    assert bumpversion.prepare_release(repository, part) == expected
    assert bumpversion.current_version(repository) == expected
    assert 'tempfile = "=3.23.0"' in (repository / "rust/Cargo.toml").read_text()
    assert (
        'name = "layerfs-api"\nversion = "1.0.0"'
        in (repository / "rust/Cargo.lock").read_text()
    )
    assert (
        (repository / "CHANGELOG.md")
        .read_text()
        .startswith(f"# Changelog\n\n## {expected}\n\n- feat: add an operation\n")
    )


def test_first_release_without_previous_marker(repository: Path) -> None:
    git(repository, "checkout", "--orphan", "first-release")
    git(repository, "commit", "-m", "Initial implementation")
    assert bumpversion.prepare_release(repository, "patch") == "1.2.4"
    assert "- Initial implementation" in (repository / "CHANGELOG.md").read_text()


@pytest.mark.parametrize("fault", ["mismatch", "duplicate_tag", "no_changes"])
def test_refuses_invalid_release_before_edits(repository: Path, fault: str) -> None:
    if fault == "mismatch":
        path = repository / "rust/Cargo.lock"
        path.write_text(
            path.read_text().replace('version = "1.2.3"', 'version = "1.2.2"')
        )
    elif fault == "duplicate_tag":
        git(repository, "tag", "v1.2.4")
    else:
        git(repository, "reset", "--hard", "HEAD~1")
    before = {p: (repository / p).read_bytes() for p in bumpversion.RELEASE_FILES}
    with pytest.raises(RuntimeError):
        bumpversion.prepare_release(repository, "patch")
    assert before == {p: (repository / p).read_bytes() for p in before}


@pytest.mark.parametrize("publish", [False, True])
def test_preview_and_publish(
    repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, publish: bool
) -> None:
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "--bare", "--initial-branch=main", str(remote))
    git(repository, "remote", "add", "origin", str(remote))
    git(repository, "push", "origin", "main")
    original = git(repository, "rev-parse", "HEAD")
    # Uncommitted local work must neither enter the release nor be changed.
    (repository / "notes.txt").write_text("local work")
    monkeypatch.setattr(
        bumpversion, "__file__", str(repository / "scripts/bumpversion.py")
    )
    monkeypatch.setattr(
        sys, "argv", ["bumpversion.py", "patch", *(["-y"] if publish else [])]
    )
    checked = []

    def verify(root: Path) -> None:
        assert root != repository
        assert bumpversion.current_version(root) == "1.2.4"
        assert not (root / "notes.txt").exists()
        checked.append(root)

    monkeypatch.setattr(bumpversion, "verify_release", verify)
    bumpversion.main()
    assert len(checked) == 1
    assert git(repository, "rev-parse", "HEAD") == original
    assert bumpversion.current_version(repository) == "1.2.3"
    assert (repository / "notes.txt").read_text() == "local work"
    if publish:
        assert git(remote, "log", "-1", "--format=%s") == "chore(release): 1.2.4"
        assert git(remote, "rev-parse", "v1.2.4^{}") == git(remote, "rev-parse", "main")
    else:
        assert git(remote, "rev-parse", "main") == original
        assert git(remote, "tag", "--list") == ""


def test_atomic_push_does_not_publish_tag_after_branch_moves(
    repository: Path, tmp_path: Path
) -> None:
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "--bare", "--initial-branch=main", str(remote))
    git(repository, "remote", "add", "origin", str(remote))
    git(repository, "push", "origin", "main")
    competitor = tmp_path / "competitor"
    git(tmp_path, "clone", str(remote), str(competitor))
    git(competitor, "config", "user.name", "Another Writer")
    git(competitor, "config", "user.email", "other@example.invalid")
    git(competitor, "commit", "--allow-empty", "-m", "Concurrent change")
    git(competitor, "push", "origin", "main")
    advanced = git(remote, "rev-parse", "main")
    version = bumpversion.prepare_release(repository, "patch")
    with pytest.raises(subprocess.CalledProcessError):
        bumpversion.commit_release(repository, version, "main")
    assert git(remote, "rev-parse", "main") == advanced
    assert git(remote, "tag", "--list") == ""


def test_distribution_check_ignores_uv_metadata(
    repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dist = repository / "dist"
    dist.mkdir()
    for name in (".gitignore", "layerfs-1.2.4.whl", "layerfs-1.2.4.tar.gz"):
        (dist / name).touch()
    commands = []

    def checked(*args: str, cwd: Path) -> None:
        commands.append(args)

    monkeypatch.setattr(bumpversion, "run_checked", checked)
    bumpversion.verify_release(repository)
    twine = commands[-1]
    assert twine[:6] == ("uv", "tool", "run", "twine", "check", "--strict")
    assert set(twine[6:]) == {
        str(dist / "layerfs-1.2.4.whl"),
        str(dist / "layerfs-1.2.4.tar.gz"),
    }
