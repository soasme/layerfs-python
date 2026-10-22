# Releasing to PyPI

[Usage guide](README.md)

The release helper follows the workflow used by `soasme/rio`: prepare and check
a release in a temporary clone, show the diff, and push only when `-y` is given.
The Python package version comes from `rust/Cargo.toml`. The helper also updates
the packaging crate's entry in `rust/Cargo.lock` and adds a changelog section.
It does not change the upstream submodule or dependency versions.

## Preview a release

Install Git, uv, and the Rust/C toolchain needed to build this package. Configure
your Git commit identity and SSH access to `origin`. Commit and push the changes
you intend to release before running the helper:

```sh
python3 scripts/bumpversion.py patch
```

Use `minor` or `major` instead of `patch` to reset lower version components.
Use `--branch NAME` to release a different remote branch (default `main`).

The helper clones the remote branch and its submodule into a temporary directory,
reusing local upstream Git objects when available to avoid another full download.
It checks out the pinned commit, never your local working files. It then
collects commits since the last `chore(release):` commit for the changelog, updates
the package and lockfile versions, checks formatting, builds the sdist and wheel,
tests the installed wheel with Python 3.9, and checks distribution metadata.
For the first release, changelog entries come from the branch's full history.

Without `-y`, it prints the release diff and removes the temporary clone. It
does not alter your checkout, commit, tag, or push. Local uncommitted or unpushed
changes are not included. Local macOS checks skip Store operations; the release
workflow tests them on supported Linux filesystems.

## Publish

```sh
python3 scripts/bumpversion.py patch -y
```

After the same checks pass, this commits `chore(release): X.Y.Z`, creates the
annotated tag `vX.Y.Z`, and atomically pushes the branch and tag. If another
writer advances the branch, the push refuses both refs. Your original checkout
stays unchanged; fast-forward it afterward with `git pull --ff-only`.

The tag starts [Publish](https://github.com/soasme/layerfs-python/actions/workflows/publish.yml):

1. Verify that the tag, package version, and Cargo lockfile agree.
2. Build one source archive, then build all wheels from that archive.
3. Build/test CPython 3.9+ ABI3 wheels for Linux x86_64 and ARM64 using
   manylinux 2.28 images, plus macOS ARM64.
4. Check distributions and publish through the `pypi` trusted publisher only
   after every build and test succeeds.

Linux Store tests use the runner's mounted project directory, since container
overlayfs is not supported by upstream. macOS wheels support import and CLI
help; Store operations still require Linux.

## Test the workflow without publishing

Run the workflow manually from GitHub Actions, or:

```sh
gh workflow run publish.yml --ref main
gh run list --workflow publish.yml
```

A manual run builds and tests the same artifacts but skips the publish job.
Download them from the run's artifacts to inspect or install them.

If a tagged run fails before publishing, fix the cause before releasing again.
PyPI does not allow replacing an uploaded file for the same version. If some
files were already uploaded, inspect PyPI and the run logs before retrying;
the workflow does not silently skip existing uploads.
