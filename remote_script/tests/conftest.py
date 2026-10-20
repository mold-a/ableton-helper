import os
import sys

# The Remote Script package is not part of the backend install: make it importable.
_RS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RS_ROOT not in sys.path:
    sys.path.insert(0, _RS_ROOT)
_TESTS = os.path.dirname(os.path.abspath(__file__))
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)
