import os
import sys

# Add project root to sys.path so tests can import local packages regardless of how pytest is invoked
ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
