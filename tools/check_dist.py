"""Check that a built sdist and wheel carry the C library and shell images."""

import sys
import tarfile
import zipfile
from pathlib import Path

DATA = [
    "c/Dockerfile",
    "c/include/kimdos.h",
    "c/src/kdint.h",
    "c/src/iec.s",
    "c/src/dos.c",
    "c/src/dir.c",
    "c/src/con.s",
    "c/kim1/crt.s",
    "c/kim1/link.ld",
] + [
    f"images/kimdos-{o}.{e}"
    for o in ("0400", "2000", "C000")
    for e in ("bin", "ptp", "lbl")
]


def missing(names, prefix):
    """Package data files not under prefix in an archive's names."""
    have = {n.split(prefix, 1)[1] for n in names if prefix in n}
    return [f for f in DATA if f not in have]


def main(dist):
    """Exit non-zero, listing what is missing, unless both archives are complete."""
    dist = Path(dist)
    (wheel,) = dist.glob("*.whl")
    (sdist,) = dist.glob("*.tar.gz")
    with zipfile.ZipFile(wheel) as z:
        bad = missing(z.namelist(), "kimdos/")
    with tarfile.open(sdist) as t:
        bad += missing(t.getnames(), "src/kimdos/")
    for f in bad:
        print("missing:", f)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
