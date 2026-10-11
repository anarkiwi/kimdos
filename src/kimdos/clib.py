"""The llvm-mos C library sources shipped with the package.

`python -m kimdos.clib` prints their directory (include/, src/, kim1/);
with --sources, the files a program compiles with it.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "c"
SOURCES = ("kim1/crt.s", "src/iec.s", "src/dos.c", "src/dir.c", "src/con.s")


def main(argv=None):
    """Print the directory, or with --sources the source files."""
    argv = sys.argv[1:] if argv is None else argv
    print(" ".join(str(ROOT / s) for s in SOURCES) if "--sources" in argv else ROOT)


if __name__ == "__main__":
    main()
