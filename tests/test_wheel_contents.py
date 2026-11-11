"""Every importable subpackage must be declared in [tool.setuptools] packages,
otherwise it is silently missing from the built wheel.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "mw75_streamer"


def _declared_packages() -> set:
    if sys.version_info >= (3, 11):
        import tomllib
    else:
        tomllib = pytest.importorskip("tomli")
    with open(ROOT / "pyproject.toml", "rb") as fh:
        return set(tomllib.load(fh)["tool"]["setuptools"]["packages"])


def test_all_subpackages_are_declared() -> None:
    on_disk = {"mw75_streamer"} | {
        f"mw75_streamer.{p.parent.relative_to(PKG).as_posix().replace('/', '.')}"
        for p in PKG.rglob("__init__.py")
        if p.parent != PKG and "__pycache__" not in p.parts
    }
    missing = on_disk - _declared_packages()
    assert not missing, f"packages missing from pyproject.toml: {sorted(missing)}"
