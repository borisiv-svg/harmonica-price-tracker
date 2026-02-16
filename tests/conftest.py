"""Shared pytest configuration and fixtures."""

import os
import sys

# Ensure project root is on sys.path so `import config`, `import utils`, etc. work
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Ensure tests/ is on sys.path so `from helpers import ...` works
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if TESTS_DIR not in sys.path:
    sys.path.insert(0, TESTS_DIR)
