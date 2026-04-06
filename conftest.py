"""Root conftest.py — adds local pip-packages directory to sys.path."""
import sys
from pathlib import Path

# Add the local package target so tests can import installed dependencies
_pip_packages = Path(__file__).parent / ".pip-packages"
if _pip_packages.exists() and str(_pip_packages) not in sys.path:
    sys.path.insert(0, str(_pip_packages))
