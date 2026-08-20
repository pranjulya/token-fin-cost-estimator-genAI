"""Version + build metadata.

The package version lives in pyproject.toml; read it once at runtime so
FastAPI /health and the OpenAPI title never drift from the packaged version.
GIT_SHA is injected at deploy time (CI sets it from the git revision).
"""

from __future__ import annotations

import os
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version as _pkg_version


@lru_cache
def get_version() -> str:
    try:
        return _pkg_version("token-cost-estimator")
    except PackageNotFoundError:
        return "0.0.0.dev"


@lru_cache
def get_build_sha() -> str:
    return os.environ.get("GIT_SHA", "dev")
