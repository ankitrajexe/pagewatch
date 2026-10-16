# conftest.py
# Ensures pytest can find the pagewatch package from the project root.
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
