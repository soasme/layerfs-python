# Daemon and FUSE

[Usage guide](README.md)

Use the [Python API](python-api.md) when your application needs direct Store
operations. It does not start a daemon or mount a filesystem. Use the bundled
daemon for an upstream deployment that exposes mounted filesystem access.

## Commands

The package installs two native executables and a Python module entry point:

```sh
layerfs --help
layerfs --version
python3 -m layerfs --help
```

In this repository's uv environment:

```sh
uv run layerfs
uv run python3 -m layerfs
```

With no arguments, `layerfs` and `python3 -m layerfs` display help and exit.
Neither command creates a Store or starts a daemon without configuration.

After provisioning the upstream daemon configuration, start it using one of:

```sh
layerfs --config /absolute/path/to/protected-config
python3 -m layerfs --config /absolute/path/to/protected-config
layerfs-daemon --config /absolute/path/to/protected-config
```

`layerfs-daemon` preserves upstream's exact CLI; the help/version additions are
provided by `layerfs` and `python3 -m layerfs`.

## Deployment requirements

Actual Store and FUSE operation requires Linux, a supported backing filesystem,
and the configuration, credentials, FUSE access, and permissions required by
upstream. Installing the Python package does not provision these resources.
`Store.create()` makes a Store for in-process application use and does not
generate daemon credentials or a daemon configuration.

Follow the [SDK deployment guide for the pinned upstream revision](https://github.com/Ephemeral-AI-Lab/layerfs/blob/5fb68ddc1acc3163e3ac3486133bde014c5fbed3/sdk/js/README.md)
for the packaged upstream version. The
[upstream repository](https://github.com/Ephemeral-AI-Lab/layerfs) contains the
full deployment documentation. Coordinate Store ownership rather than opening
the same Store independently through both a daemon and an application.

## Locate the executable from Python

```python
import subprocess

from layerfs import find_layerfs_bin

subprocess.run([find_layerfs_bin(), "--version"], check=True)
```

`find_layerfs_bin()` returns the installed `layerfs` executable path and raises
`LayerFSNotFound` if it cannot locate an executable. For configured daemon use,
pass `--config` and the protected configuration path in the argument list.
