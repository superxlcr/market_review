"""Ensure the src-layout package is importable during tests."""
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if SRC.exists() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
