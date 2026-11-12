"""Installed web stack must be at or above the versions fixing known DoS advisories.

- starlette >= 1.3.1: `request.form()` limits honoured for urlencoded bodies,
  and quadratic Range header merging in `FileResponse` fixed (0.49.1).
- python-multipart >= 0.0.31: quadratic `;` parsing, unbounded part headers.
- fastapi >= 0.133.1: first release allowing starlette >= 1.0.
"""

from __future__ import annotations

from importlib.metadata import version

import pytest
from packaging.version import Version


@pytest.mark.parametrize(
    ("package", "floor"),
    [
        ("starlette", "1.3.1"),
        ("python-multipart", "0.0.31"),
        ("fastapi", "0.133.1"),
    ],
)
def test_dependency_is_at_or_above_floor(package: str, floor: str) -> None:
    installed = Version(version(package))
    assert installed >= Version(floor), f"{package} {installed} < {floor}"
