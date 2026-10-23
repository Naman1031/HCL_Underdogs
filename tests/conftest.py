"""
Test settings shared by every test file: no Ollama, and throwaway stores so
tests never touch real data. These must be set before any `app` module is
imported, because app/config.py reads the environment at import time.
"""

import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="student-assistant-tests-")
os.environ["MOCK_LLM"] = "true"
os.environ["SQLITE_PATH"] = os.path.join(_tmp, "test.db")
os.environ["CHROMA_PATH"] = os.path.join(_tmp, "chroma")
os.environ["UPLOADS_DIR"] = os.path.join(_tmp, "uploads")
