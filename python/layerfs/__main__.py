"""``python -m layerfs`` forwards arguments to the bundled Rust daemon."""

from __future__ import annotations

import os
import sys

from . import find_layerfs_bin


def main() -> None:
    """Launch the daemon, preserving its arguments, streams, and exit status."""
    executable = find_layerfs_bin()
    args = [executable, *sys.argv[1:]]
    if sys.platform == "win32":
        import subprocess

        try:
            result = subprocess.run(args, check=False)
        except KeyboardInterrupt:
            raise SystemExit(130) from None
        raise SystemExit(result.returncode)
    os.execv(executable, args)


if __name__ == "__main__":
    main()
