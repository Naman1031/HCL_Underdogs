"""
Every Pydantic model that crosses a boundary: API bodies, LLM outputs, CSV rows,
tool results and audit records (spec A.2). Field names follow the spec exactly;
the API models in the C section are the brief's fixed contract (Part G), so never
rename them. Models sit in the section of the person who provides them. Add only
inside your own section, and tell the team before changing a model others use.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

DATE = r"^\d{4}-\d{2}-\d{2}$"
DATE_OR_EMPTY = r"^(\d{4}-\d{2}-\d{2})?$"

# Shared types (tell the team before changing)
AnswerType = Literal[
    "retrieved_fact", "calculated", "not_found",
    "clarification_needed", "refused", "conflict_flagged",
]
Category = Literal[
    "policy_fact", "procedure", "personal_data", "personal_eligibility",
    "what_if", "other_student", "unclear",
]


# --- A ---  documents, rules, retrieval, precedence

class SourceMeta(BaseModel):
    """One Source Register row (Annex B). Also the metadata JSON for POST /ingest."""
    doc_id: str = Field(pattern=r"^[A-Za-z0-9._-]+$")  # also used as a file name on upload
    title: str
    issuer: str
    authority_level: int = Field(ge=1, le=5)  # 1 = highest authority (Annex A.1)
    doc_type: Literal["regulation", "circular", "notice", "faq", "handbook", "unofficial"]
    version: str
    effective_from: str = Field(pattern=DATE)
    effective_to: str = Field("", pattern=DATE_OR_EMPTY)  # empty = still in force
    supersedes: str = ""  # "DOC-ID" or "DOC-ID#clause", separated by ";"
    scope_programmes: str = "ALL"  # ALL or "B.Tech CSE;B.Tech EE"
    scope_batches: str = "ALL"  # ALL, "2023+" or "2022;2023"
    provenance: str = ""
    retrieved_on: str = Field("", pattern=DATE_OR_EMPTY)
    synthetic: Literal["Y", "N"] = "N"


class Rule(BaseModel):
    """One rule_registry row (Annex C). Every threshold used in a decision is one of these."""
    rule_id: str
    description: str
    parameter: str  # e.g. min_attendance_pct
    operator: Literal[">=", "<=", "between", "in"]
    value: str
    scope_programmes: str
    scope_batches: str
    effective_from: str
    effective_to: str | None = None  # None or empty = still in force
    source_doc_id: str
    source_section: str
    origin: Literal["manual", "auto_extracted"] = "manual"


class Chunk(BaseModel):
    """A retrieved passage plus everything needed to cite it (spec F.4)."""
    chunk_id: str  # "{doc_id}::{chunk_no}"
    text: str
    section: str  # nearest heading or clause number
    page: int | None
    score: float  # 1 - cosine distance
    source: SourceMeta


Applicability = Literal["current", "upcoming", "expired", "out_of_scope"]


class Resolution(BaseModel):
    """Result of precedence.resolve_rules() for one parameter (spec D.5)."""
    status: Literal["RESOLVED", "CONFLICT", "NO_RULE", "RULE_UNCERTAIN"]
    winner: Rule | None = None
    overridden: list[Rule] = []
    conflicts: list[Rule] = []
    decision_text: str = ""  # e.g. "ACAD-2026-08 supersedes ACAD-REG-2024#7.2 (step 2)"
    step_used: int | None = None


# --- B ---  students, tools, synthetic data

class StudentProfile(BaseModel):
    """The logged-in student, as needed by tools and by precedence scope checks."""
    student_id: str
    programme: str
    batch_year: int
    current_semester: int
    cgpa: float
    active_backlogs: int


class ToolResult(BaseModel):
    """What every deterministic tool returns (spec D.7)."""
    tool: str
    input: dict[str, Any]
    output: dict[str, Any]
    rule_ids: list[str] = []
    status: Literal["ok", "error"] = "ok"
    ms: float = 0.0


class StudentRow(BaseModel):
    """students.csv row (Annex C)."""
    student_id: str = Field(pattern=r"^S\d{4}$")
    full_name: str
    programme: str
    batch_year: int
    current_semester: int = Field(ge=1, le=10)
    cgpa: float = Field(ge=0, le=10)
    active_backlogs: int = Field(ge=0)


class CourseRow(BaseModel):
    """courses.csv row (Annex C)."""
    course_code: str
    course_name: str
    programme: str
    semester: int
    credits: int


class AttendanceRow(BaseModel):
    """attendance.csv row (Annex C). attended <= held is checked by the validator."""
    student_id: str
    course_code: str
    classes_held: int = Field(gt=0)
    classes_attended: int = Field(ge=0)


class ResultRow(BaseModel):
    """results.csv row (Annex C). total = internal + external is checked by the validator."""
    student_id: str
    course_code: str
    exam_session: str  # e.g. 2026-MAY
    exam_type: Literal["REGULAR", "SUPPLEMENTARY"]
    internal_marks: int
    external_marks: int
    total_marks: int
    max_marks: int
    result: Literal["PASS", "FAIL", "ABSENT", "DETAINED"]


class GeneratedAttendance(BaseModel):
    course_code: str
    classes_held: int
    classes_attended: int


class GeneratedMarks(BaseModel):
    course_code: str
    internal_marks: int
    external_marks: int


class GeneratedStudent(BaseModel):
    """LLM output for one synthetic student (scripts/generate_students.py).
    Ranges are checked in code, not here, so each LLM mistake can be logged for the data card."""
    student_id: str
    full_name: str
    cgpa: float
    attendance: list[GeneratedAttendance]
    results: list[GeneratedMarks]


# --- C ---  LLM outputs, API contract (Part G), audit (Annex D)

class Understanding(BaseModel):
    """Output of the Understand LLM call (spec D.3 node 1). Code re-checks every field."""
    category: Category
    course_code: str | None = None
    parameter: str | None = None
    assumptions: list[str] = []
    search_query: str = ""


class LLMUsage(BaseModel):
    calls: int = 0
    tokens: int = 0  # prompt_eval_count + eval_count from Ollama


class AskRequest(BaseModel):
    question: str = Field(min_length=1)
    as_of_date: str | None = Field(None, pattern=DATE)  # defaults to today


class Citation(BaseModel):
    doc_id: str
    title: str
    section: str
    page: int | None
    version: str
    effective_from: str


class ToolInvocation(BaseModel):
    tool: str
    input: dict[str, Any] = {}
    output: dict[str, Any]


class AppliedRule(BaseModel):
    rule_id: str
    value: str  # e.g. ">= 75%"
    source_doc_id: str


class AskResponse(BaseModel):
    trace_id: str
    answer: str
    answer_type: AnswerType
    citations: list[Citation] = []
    tools_invoked: list[ToolInvocation] = []
    applied_rules: list[AppliedRule] = []
    conflicts_detected: list[str] = []
    explanation: str = ""
    as_of_date: str
    upcoming_changes: list[str] = []  # [TEAM] extra field
    assumptions: list[str] = []  # [TEAM] extra field


class IngestResponse(BaseModel):
    doc_id: str
    chunks_indexed: int
    status: Literal["indexed", "error"]
    rules_extracted: int = 0  # [TEAM] extra field
    detail: str = ""  # [TEAM] extra field: error message when status == "error"


class HealthResponse(BaseModel):
    api: Literal["ok"]
    vector_store: Literal["ok", "error"]
    sqlite: Literal["ok", "error"]
    llm: Literal["ok", "error", "mock"]


class SourceHit(BaseModel):
    doc_id: str
    section: str
    score: float


class AuditRecord(BaseModel):
    """Annex D record. Never holds the question text or LLM reasoning [BRIEF R7, R10]."""
    trace_id: str
    timestamp: str  # UTC ISO
    student_id: str | None
    question_category: str
    sources_retrieved: list[SourceHit] = []
    precedence_decision: str = ""
    rules_applied: list[AppliedRule] = []
    conflicts_detected: list[str] = []
    tools_invoked: list[ToolResult] = []  # includes input and output, as R10 asks
    answer_type: AnswerType
    model: str
    llm_calls: int = 0
    tokens: int = 0
    latency_ms: float = 0.0
