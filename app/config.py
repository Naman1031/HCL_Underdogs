"""
Central settings, read once from environment variables (and .env for local dev).
Only technical knobs live here: paths, top_k, timeouts, model names, keywords.
Decision thresholds (e.g. minimum attendance) are NOT here: they come from
rule_registry [BRIEF R5, spec A.2]. docker-compose.yml overrides the paths and
URLs inside the containers. Each owner edits only their own section.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"


def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes"}


def _env_path(name: str, default: str) -> Path:
    # Relative paths are taken from the repo root, so scripts work from any folder.
    path = Path(os.getenv(name, default))
    return path if path.is_absolute() else ROOT / path


# Shared (tell the team before changing)
SQLITE_PATH = _env_path("SQLITE_PATH", "data/sqlite/app.db")

# --- A ---  ingestion, retrieval, precedence
EMBED_MODEL = os.getenv("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
CHUNK_MAX_TOKENS = int(os.getenv("CHUNK_MAX_TOKENS", "256"))  # MiniLM's max input length
FETCH_K = int(os.getenv("FETCH_K", "20"))
TOP_K = int(os.getenv("TOP_K", "4"))
MIN_SCORE = float(os.getenv("MIN_SCORE", "0.5"))  # tuned on our index: answerable 0.69-0.85, unanswerable 0.28-0.45
CHROMA_PATH = _env_path("CHROMA_PATH", "data/chroma")
CHROMA_COLLECTION = "university_docs"
UPLOADS_DIR = _env_path("UPLOADS_DIR", "data/uploads")  # files received by POST /ingest
DOCUMENTS_DIR = DATA_DIR / "documents"
SOURCE_REGISTER_CSV = DATA_DIR / "source_register.csv"
RULES_CSV = DATA_DIR / "rules.csv"

# Chunks containing one of these words are sent for rule extraction at /ingest (spec D.6).
# Keys must match rule_registry.parameter values. Finalise after reading the DTU documents.
PARAMETER_KEYWORDS: dict[str, list[str]] = {
    "min_attendance_pct": ["attendance"],
    "pass_mark_pct": ["pass marks", "minimum marks"],
    "placement_min_cgpa": ["placement", "cgpa"],
    "placement_max_backlogs": ["backlog"],
}

# --- B ---  students, tools, guardrail, eval
STUDENTS_DIR = DATA_DIR / "students"
PROMPTS_DIR = DATA_DIR / "prompts"
GENERATOR_TEMPERATURE = 0.7  # variety in synthetic names (spec F.6); answers always use 0

# --- C ---  LLM, API
MOCK_LLM = _env_bool("MOCK_LLM", False)
LLM_BACKEND = os.getenv("LLM_BACKEND", "ollama")  # ollama | cloud (fallback, disclose in README)
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:7b-instruct")
LLM_TIMEOUT_S = float(os.getenv("LLM_TIMEOUT_S", "120"))
LLM_HEALTH_TIMEOUT_S = 3.0  # /health must answer fast even when Ollama is down
