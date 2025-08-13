# Ensure project root is importable as a module location when running pytest from various working directories.
import os
import sys

ROOT = os.path.dirname(__file__)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
