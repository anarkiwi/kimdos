"""Build the 6502 image with cc65 and read back its symbols."""

import fcntl
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Image:
    """A linked KIMDOS image: binary, tape, load address and symbol table."""

    binary: bytes
    ptp: Path
    labels: dict
    org: int

    @classmethod
    def load(cls, stem):
        """Read the .bin, .ptp and .lbl files an ld65 build left at stem."""
        stem = Path(stem)
        labels = read_labels(stem.with_suffix(".lbl"))
        return cls(
            stem.with_suffix(".bin").read_bytes(),
            stem.with_suffix(".ptp"),
            labels,
            labels["__RAM_START__"],
        )

    def __getitem__(self, name):
        return self.labels[name]


def read_labels(path):
    """Parse an ld65 -Ln (VICE) label file into {name: address}."""
    labels = {}
    for line in Path(path).read_text(encoding="ascii").splitlines():
        _, addr, name = line.split()
        labels[name.lstrip(".")] = int(addr, 16)
    return labels


def _make(build_dir, *args):
    build_dir.mkdir(parents=True, exist_ok=True)
    with open(build_dir / ".lock", "w", encoding="ascii") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        subprocess.run(
            ["make", "-s", "-C", str(ROOT), "BUILD=%s" % build_dir, *args],
            check=True,
            stdout=subprocess.DEVNULL,
        )


def build_c():
    """Build the C library and its test program (llvm-mos in docker) under the
    repository's build directory, which docker can mount; return kdtest.bin."""
    build_dir = ROOT / "build"
    _make(build_dir, "clib")
    return (build_dir / "c" / "kdtest.bin").read_bytes()


def build(org=0x2000, build_dir=None):
    """Run make for an image at org and return it."""
    build_dir = Path(build_dir or ROOT / "build")
    _make(build_dir, "ORG=%04X" % org)
    return Image.load(build_dir / ("kimdos-%04X" % org))
