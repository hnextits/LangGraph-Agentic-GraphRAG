"""Bootstrap helpers for standalone pipeline scripts."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import sys

_MARKER = "logging_config.py"


@lru_cache(maxsize=1)
def ensure_backend_root() -> Path:
    """Ensure the backend root directory is on sys.path and return it."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / _MARKER).exists():
            if str(parent) not in sys.path:
                sys.path.append(str(parent))
            return parent
    # Fallback: add grandparent directory
    fallback = current.parent
    if str(fallback) not in sys.path:
        sys.path.append(str(fallback))
    return fallback


def configure_logging() -> None:
    """Ensure backend root is available and configure logging once."""
    ensure_backend_root()
    from logging_config import configure_logging as _configure_logging

    _configure_logging()


def get_backend_dir() -> Path:
    """Return the backend root directory."""
    return ensure_backend_root()


def get_data_pipeline_dir() -> Path:
    """Return the data_pipeline directory under backend."""
    return ensure_backend_root() / "data_pipeline"


def get_project_root() -> Path:
    """Return the project root directory (parent of backend)."""
    return ensure_backend_root().parent


__all__ = [
    "ensure_backend_root",
    "configure_logging",
    "get_backend_dir",
    "get_data_pipeline_dir",
    "get_project_root",
]
