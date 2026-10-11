"""Shared fixtures: one built image per test worker."""

import pytest

from kimdos.build import build


@pytest.fixture(scope="session")
def image(tmp_path_factory):
    """The shell image built at $2000."""
    return build(0x2000, tmp_path_factory.mktemp("build"))
