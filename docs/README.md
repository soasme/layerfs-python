# Usage guide

LayerFS provides a Python `Store` API for operations inside your application
process, plus native commands for running the upstream daemon.

- [Installation and quickstart](getting-started.md): install the package, create
  a Store, and reopen it.
- [Python API](python-api.md): file operations, atomic batches, branches,
  pagination, errors, and handle lifetime.
- [Daemon and FUSE](daemon.md): command entry points and deployment requirements.
- [Troubleshooting](troubleshooting.md): installation, platform refusals, and
  common API errors.
- [Releasing to PyPI](releasing.md): preview version bumps and publish releases.

Store operations require Python 3.9+ and Linux on ext4, XFS, or Btrfs. The Python
API needs no daemon, FUSE mount, container, or root privileges. macOS supports
package import and CLI help, but upstream refuses Store operations there.

Stores use upstream's Disposable SQLite profile (`WAL`, `synchronous=OFF`). They
can be closed and reopened normally; this profile does not guarantee durability
after power loss or an OS crash.

[Repository README](../README.md)
