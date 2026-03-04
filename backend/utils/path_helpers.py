"""Common path calculation helpers to avoid duplication."""
from pathlib import Path
from functools import lru_cache


@lru_cache(maxsize=1)
def get_backend_dir() -> Path:
    """Return the backend root directory."""
    return Path(__file__).parent.parent.absolute()


@lru_cache(maxsize=1)
def get_project_root() -> Path:
    """Return the project root directory (parent of backend)."""
    return get_backend_dir().parent


@lru_cache(maxsize=1)
def get_notebooklm_dir() -> Path:
    """Return the notebooklm directory."""
    return get_backend_dir() / "notebooklm"


@lru_cache(maxsize=1)
def get_data_pipeline_dir() -> Path:
    """Return the data_pipeline directory."""
    return get_backend_dir() / "data_pipeline"


__all__ = [
    "get_backend_dir",
    "get_project_root",
    "get_notebooklm_dir",
    "get_data_pipeline_dir",
]
