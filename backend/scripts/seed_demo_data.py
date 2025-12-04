"""Compatibility wrapper for the packaged seed script."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.append(str(SRC_DIR))

from app.scripts.seed_demo_data import main  # noqa: E402


if __name__ == "__main__":
    main()

