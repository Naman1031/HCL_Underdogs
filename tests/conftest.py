"""
Test settings shared by every test file: no Ollama, and a throwaway SQLite
database so tests never touch real data. These must be set before any `app`
module is imported, because app/config.py reads the environment at import time.
"""

import importlib
import os
import sys
import tempfile
import types

_tmp = tempfile.mkdtemp(prefix="student-assistant-tests-")
os.environ["MOCK_LLM"] = "true"
os.environ["SQLITE_PATH"] = os.path.join(_tmp, "test.db")
os.environ["CHROMA_PATH"] = os.path.join(_tmp, "chroma")
os.environ["UPLOADS_DIR"] = os.path.join(_tmp, "uploads")

# TEMPORARY: until Persons A and B push their modules, register empty stand-ins
# so app.graph can be imported. Each test replaces the functions it needs with
# monkeypatch, so the same tests keep working once the real modules exist.
import app  # noqa: E402

for _name in ("retrieval", "precedence", "tools", "guardrail"):
    try:
        importlib.import_module(f"app.{_name}")
    except ImportError:
        _stand_in = types.ModuleType(f"app.{_name}")
        sys.modules[f"app.{_name}"] = _stand_in
        setattr(app, _name, _stand_in)

if not hasattr(app.retrieval, "health"):
    app.retrieval.health = lambda: "error"  # stand-in: no vector store in tests
