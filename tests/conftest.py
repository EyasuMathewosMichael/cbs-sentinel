"""Test environment bootstrap for local integration services."""

import os
from pathlib import Path


def _load_local_environment() -> None:
    environment_file = Path(__file__).parents[1] / ".env"
    if not environment_file.is_file():
        return
    for line in environment_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip())


_load_local_environment()
