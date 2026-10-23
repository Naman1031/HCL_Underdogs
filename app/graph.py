"""
The /ask workflow as a fixed LangGraph graph (spec D.2, D.3): Understand (LLM)
-> Guardrail -> route -> Policy | Personal | What-if | Clarify -> Compose (LLM)
-> Assemble -> Audit. "The LLM explains. Code decides." Code picks the path,
the tool, the answer_type and the citations [BRIEF R5, R9]. The LLM only
classifies the question and words the explanation: at most 2 calls [spec C.2].
"""

import json
import re
import time
from datetime import date, datetime, timezone
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app import audit, config, db, guardrail, llm, precedence, retrieval, tools
from app.schemas import (
    AnswerType, AppliedRule, AskResponse, AuditRecord, Chunk, Citation, ComposeOutput,
    Resolution, Rule, SourceHit, SourceMeta, StudentProfile, ToolInvocation, ToolResult,
    Understanding,
)

# Fixed messages (spec G.1). The not_found text must match the brief exactly.
NOT_FOUND_MESSAGE = "I could not find this information in the authorised university sources."
UNCLEAR_MESSAGE = "I'm not sure what you are asking. Could you rephrase your question?"
RULE_UNCERTAIN_MESSAGE = ("The rule registry may be out of date for this rule; "
                          "please contact the issuing office.")
CONFLICT_MESSAGE = ("The authorised sources disagree on this and the precedence policy cannot "
                    "resolve it. Please contact the issuing office.")

# Keywords that pick a tool (spec D.3 node 5: plain if/elif routing, decided by code).
# These choose WHICH tool runs; they are not decision thresholds.
ATTENDANCE_WORDS = ("attendance", "attend", "classes")
RESULT_WORDS = ("result", "marks", "grade", "score", "pass", "fail")
PLACEMENT_WORDS = ("placement", "placed", "recruit")
SUPPLEMENTARY_WORDS = ("supplementary", "supple", "reappear")
TOOLS_NEEDING_COURSE = {"get_attendance", "check_exam_eligibility", "check_supplementary_eligibility"}
SUPERSEDE_LEVELS = precedence.SUPERSESSION_LEVELS  # only level 1-2 may supersede (Annex A step 2)
UNTRUSTED_LEVEL = precedence.UNTRUSTED_AUTHORITY_LEVEL  # level 5 never decides (Annex A)
NUMBER = re.compile(r"\d+(?:\.\d+)?")  # for the number grounding check [BRIEF R3]
# Code checks on the LLM's category (found in evaluation: the 7B model sometimes mislabels).
FIRST_PERSON = re.compile(r"\b(i|me|my|mine|i'm)\b", re.IGNORECASE)
ASKS_OWN_ELIGIBILITY = re.compile(r"\b(am i|can i|could i|will i|do i qualify|my eligibility)\b", re.IGNORECASE)
PERSONAL = ("personal_data", "personal_eligibility", "what_if")


class AskState(TypedDict, total=False):
    # Request
    trace_id: str
    question: str
    as_of_date: str
    student_id: str | None
    started: float
    # Filled in by the nodes
    understanding: Understanding
    student: StudentProfile | None
    answer_type: AnswerType
    answer: str
    explanation: str
    chunks: list[Chunk]  # evidence kept for the answer
    sources_retrieved: list[SourceHit]
    tool_results: list[ToolResult]
    applied_rules: list[AppliedRule]
    rule_citations: list[Citation]
    conflicts: list[str]
    upcoming: list[str]
    assumptions: list[str]
    precedence_decision: str
    llm_calls: int
    tokens: int
    response: AskResponse


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _has_any(text: str, words: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in words)


def _load_sources() -> dict[str, SourceMeta]:
    """All registered documents, keyed by doc_id. Empty DB values become "" for the model."""
    sources = {}
    for row in db.get_sources():
        fields = {k: ("" if row[k] is None else row[k]) for k in SourceMeta.model_fields if k in row}
        sources[row["doc_id"]] = SourceMeta(**fields)
    return sources


def _rule_citation(rule: Rule, sources: dict[str, SourceMeta]) -> Citation | None:
    source = sources.get(rule.source_doc_id)
    if source is None:
        return None
    return Citation(doc_id=source.doc_id, title=source.title, section=rule.source_section,
                    page=None, version=source.version, effective_from=source.effective_from)


def _applied(rule: Rule) -> AppliedRule:
    return AppliedRule(rule_id=rule.rule_id, value=f"{rule.operator} {rule.value}",
                       source_doc_id=rule.source_doc_id)


def _rules_by_ids(rule_ids: list[str]) -> list[Rule]:
    if not rule_ids:
        return []
    marks = ", ".join("?" * len(rule_ids))
    return [Rule(**row) for row in db.query(f"SELECT * FROM rule_registry WHERE rule_id IN ({marks})",
                                            tuple(rule_ids))]


def _is_superseded(chunk: Chunk, superseded: set[str]) -> bool:
    """True if the chunk's whole document, or its clause, is listed in a `supersedes` field."""
    if chunk.source.doc_id in superseded:
        return True
    # PDF text often has stray spaces ("R. 1(B).22"), so clause labels are compared without spaces.
    section = chunk.section.replace(" ", "")
    for entry in superseded:
        doc_id, _, clause = entry.partition("#")
        clause = clause.replace(" ", "")
        if doc_id == chunk.source.doc_id and clause and section == clause:
            return True
    return False


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------
def understand(state: AskState) -> dict:
    """LLM call 1: question -> category and slots. Code re-checks every slot against the DB."""
    courses = db.query("SELECT course_code, course_name FROM courses ORDER BY course_code")
    parameters = [r["parameter"] for r in db.query("SELECT DISTINCT parameter FROM rule_registry")]
    course_list = ", ".join(f"{c['course_code']} ({c['course_name']})" for c in courses)
    user = (f"Question: {state['question']}\n"
            f"Known courses: {course_list or 'none'}\n"
            f"Known parameters: {', '.join(parameters) or 'none'}")
    mock = Understanding(category="policy_fact", search_query=state["question"])
    result, usage = llm.chat_json(llm.UNDERSTAND_SYSTEM, user, Understanding, mock)
    if result is None:  # two invalid replies in a row (spec D.3 node 1)
        result = Understanding(category="unclear", search_query=state["question"])

    # A question with no "I/me/my" cannot be about the asker's own records: treat it as policy.
    # A question asking "am I / can I ..." is about the asker's own eligibility.
    question = state["question"]
    if result.category in PERSONAL and not FIRST_PERSON.search(question):
        result.category = "policy_fact"
    elif result.category in ("policy_fact", "procedure") and ASKS_OWN_ELIGIBILITY.search(question):
        result.category = "personal_eligibility"

    known_codes = {c["course_code"] for c in courses}
    code = result.course_code.upper() if result.course_code else None
    result.course_code = code if code in known_codes else None
    result.parameter = result.parameter if result.parameter in parameters else None
    result.search_query = result.search_query or state["question"]
    return {"understanding": result, "llm_calls": usage.calls, "tokens": usage.tokens}


def check_access(state: AskState) -> dict:
    """Guardrail [BRIEF R7]: runs before any student data is read."""
    category = state["understanding"].category
    refusal = guardrail.check(state["student_id"], state["question"], category)
    if not refusal and category == "other_student":
        refusal = guardrail.REFUSE_OTHER_STUDENT  # defence in depth: never route this anywhere else
    if refusal:
        return {"answer_type": "refused", "answer": refusal}
    student = tools.get_student(state["student_id"]) if state["student_id"] else None
    return {"student": student}


def route(state: AskState) -> str:
    """Code router (spec D.3 node 3). Not an LLM call."""
    if state.get("answer_type") == "refused":
        return "assemble"
    category = state["understanding"].category
    if category in ("policy_fact", "procedure"):
        return "policy"
    if category in ("personal_data", "personal_eligibility"):
        return "personal"
    if category == "what_if":
        return "what_if"
    # "unclear" still searches the documents: weak evidence then gives the honest not_found,
    # which is safer for unseen questions than asking a student to rephrase a valid question.
    return "policy"


def policy(state: AskState) -> dict:
    """Retrieval + Annex A precedence + evidence check [BRIEF R1-R4] (spec D.3 node 4)."""
    u = state["understanding"]
    # precedence.py works on plain dicts and a date object (Person A's interface).
    as_of = date.fromisoformat(state["as_of_date"])
    student = state["student"].model_dump() if state.get("student") else None
    sources = _load_sources()

    # Documents that are in force today and allowed to supersede others.
    superseded: set[str] = set()
    for source in sources.values():
        if (source.authority_level in SUPERSEDE_LEVELS and source.supersedes
                and precedence.applicability(source.model_dump(), as_of, student) == "current"):
            superseded.update(s.strip() for s in source.supersedes.split(";") if s.strip())

    kept: list[Chunk] = []
    upcoming: list[str] = []
    for chunk in retrieval.search(u.search_query, config.FETCH_K):
        status = precedence.applicability(chunk.source.model_dump(), as_of, student)
        if status == "upcoming":
            note = f"{chunk.source.title} ({chunk.source.doc_id}) takes effect on {chunk.source.effective_from}."
            if note not in upcoming:
                upcoming.append(note)
        elif status == "current" and not _is_superseded(chunk, superseded):
            kept.append(chunk)

    # Highest score first; ties go to higher authority, then the newer document.
    # (Two stable sorts: the second one keeps the first one's order for ties.)
    kept.sort(key=lambda c: c.source.effective_from, reverse=True)
    kept.sort(key=lambda c: (-c.score, c.source.authority_level))
    kept = kept[:config.TOP_K]

    update: dict = {
        "chunks": kept, "upcoming": upcoming,
        "sources_retrieved": [SourceHit(doc_id=c.source.doc_id, section=c.section, score=c.score)
                              for c in kept],
    }

    resolution = Resolution(status="NO_RULE")
    if u.parameter:
        resolution = precedence.resolve_rules(db.get_rules(u.parameter), db.get_sources(), as_of, student)
        if resolution.status != "NO_RULE":
            update.update(_resolution_fields(resolution, sources))

    strong = [c for c in kept if c.score >= config.MIN_SCORE and c.source.authority_level < UNTRUSTED_LEVEL]
    if resolution.status == "CONFLICT":
        update.update(answer_type="conflict_flagged", answer=CONFLICT_MESSAGE)
    elif resolution.status == "RULE_UNCERTAIN":  # safety net, spec D.6 step 5
        update.update(answer_type="conflict_flagged", answer=RULE_UNCERTAIN_MESSAGE)
    elif not strong and resolution.status != "RESOLVED":
        update.update(answer_type="not_found", answer=NOT_FOUND_MESSAGE)
    else:
        update["answer_type"] = "retrieved_fact"
    return update


def _resolution_fields(resolution: Resolution, sources: dict[str, SourceMeta]) -> dict:
    """Turns a precedence Resolution into response fields (rules applied, citations, conflicts)."""
    deciding = [resolution.winner] if resolution.winner else []
    if resolution.status == "CONFLICT":
        deciding = resolution.conflicts
    citations = [c for c in (_rule_citation(r, sources) for r in deciding) if c]
    conflicts = [f"{r.rule_id} ({r.source_doc_id}, {r.operator} {r.value}) was not applied."
                 for r in resolution.overridden]
    if resolution.status == "CONFLICT":
        conflicts.append("Unresolved conflict between " + ", ".join(
            f"{r.rule_id} ({r.source_doc_id})" for r in resolution.conflicts) + ".")
    if conflicts:
        conflicts.append(f"Precedence decision: {resolution.decision_text}.")
    return {"applied_rules": [_applied(r) for r in deciding], "rule_citations": citations,
            "conflicts": conflicts, "precedence_decision": resolution.decision_text}


def _pick_tool(category: str, parameter: str | None, question: str) -> str:
    """Plain if/elif tool choice from the category and slots (spec D.3 node 5)."""
    if category == "personal_eligibility":
        if _has_any(question, PLACEMENT_WORDS) or (parameter or "").startswith("placement"):
            return "check_placement_eligibility"
        if _has_any(question, SUPPLEMENTARY_WORDS):
            return "check_supplementary_eligibility"
        return "check_exam_eligibility"
    if parameter == "min_attendance_pct" or _has_any(question, ATTENDANCE_WORDS):
        return "get_attendance"
    if parameter == "pass_mark_pct" or _has_any(question, RESULT_WORDS):
        return "get_results"
    return "get_student_profile"


def _run_tool(name: str, student_id: str, course_code: str | None, as_of: str,
              assume_passed: list[str] | None = None) -> ToolResult:
    # student_id always comes from the graph state (the header), never from the LLM.
    if name == "get_attendance":
        return tools.get_attendance(student_id, course_code)
    if name == "get_results":
        return tools.get_results(student_id, course_code)
    if name == "check_exam_eligibility":
        return tools.check_exam_eligibility(student_id, course_code, as_of)
    if name == "check_supplementary_eligibility":
        return tools.check_supplementary_eligibility(student_id, course_code, as_of)
    if name == "check_placement_eligibility":
        return tools.check_placement_eligibility(student_id, as_of, assume_passed=assume_passed)
    return tools.get_student_profile(student_id)


def _clarify_course(courses: list[dict]) -> dict:
    listing = ", ".join(f"{c['course_code']} ({c['course_name']})" for c in courses)
    return {"answer_type": "clarification_needed",
            "answer": f"Which course do you mean? Your courses: {listing or 'none found'}."}


def _match_course(question: str, courses: list[dict]) -> str | None:
    """The one course the question names, or the student's only course; else None."""
    lowered = question.lower()
    named = [c for c in courses
             if c["course_code"].lower() in lowered or c["course_name"].lower() in lowered]
    candidates = named or courses
    return candidates[0]["course_code"] if len(candidates) == 1 else None


def _tool_fields(result: ToolResult) -> dict:
    """Response fields for one tool result: answer_type, the code-built answer and cited rules."""
    sources = _load_sources()
    rules = _rules_by_ids(result.rule_ids)
    fields = {"tool_results": [result], "applied_rules": [_applied(r) for r in rules],
              "rule_citations": [c for c in (_rule_citation(r, sources) for r in rules) if c]}
    if result.status == "error":
        return fields | {"answer_type": "not_found", "answer": NOT_FOUND_MESSAGE,
                         "explanation": str(result.output.get("error", ""))}
    if result.output.get("result") == "RULE_UNCERTAIN":  # safety net, spec D.6 step 5
        return fields | {"answer_type": "conflict_flagged", "answer": RULE_UNCERTAIN_MESSAGE}
    return fields | {"answer_type": "calculated", "answer": _calculated_answer(result)}


def _calculated_answer(result: ToolResult) -> str:
    """One-line answer for a tool result, always built by code (spec D.3 node 7)."""
    out, code = result.output, result.input.get("course_code")
    in_course = f" in {code}" if code else ""
    try:
        if result.tool == "get_attendance":
            return (f"Your attendance{in_course} is {out['attendance_pct']}% "
                    f"({out['classes_attended']} of {out['classes_held']} classes).")
        if result.tool == "get_student_profile":
            return f"Your CGPA is {out['cgpa']} and you have {out['active_backlogs']} active backlog(s)."
        if result.tool == "get_results":
            latest = out["results"][0]
            return (f"Your latest result in {latest['course_code']} is {latest['result']}: "
                    f"{latest['total_marks']}/{latest['max_marks']} ({latest['exam_session']}, "
                    f"{latest['exam_type'].lower()}).")
        targets = {"check_exam_eligibility": f"the end-semester exam{in_course}",
                   "check_supplementary_eligibility": f"the supplementary exam{in_course}",
                   "check_placement_eligibility": "placement"}
        if result.tool in targets and out.get("result") in ("ELIGIBLE", "NOT_ELIGIBLE"):
            verdict = "eligible" if out["result"] == "ELIGIBLE" else "not eligible"
            line = f"You are {verdict} for {targets[result.tool]}"
            if result.tool == "check_exam_eligibility":
                line += f": your attendance is {out['attendance_pct']}% against a minimum of {out['threshold']:g}%"
            elif out.get("failed_checks"):
                line += ": " + "; ".join(out["failed_checks"])
            return line + "."
    except KeyError:
        pass  # unexpected tool output: fall through to the generic line
    return f"Here is your {result.tool.replace('_', ' ')} result{in_course}."


def personal(state: AskState) -> dict:
    """Deterministic tools for the logged-in student only [BRIEF R5, R7] (spec D.3 node 5)."""
    student = state.get("student")
    if student is None:  # defence in depth: the guardrail should already have refused
        return {"answer_type": "refused", "answer": guardrail.REFUSE_NOT_LOGGED_IN}
    u = state["understanding"]
    tool = _pick_tool(u.category, u.parameter, state["question"])
    code = u.course_code
    if tool in TOOLS_NEEDING_COURSE and code is None:
        courses = tools.list_courses(student.student_id)
        code = _match_course(state["question"], courses)
        if code is None:
            return _clarify_course(courses)
    return _tool_fields(_run_tool(tool, student.student_id, code, state["as_of_date"]))


def what_if(state: AskState) -> dict:
    """Hypotheticals [BRIEF R6]: rerun the placement check assuming named courses are passed."""
    student = state.get("student")
    if student is None:
        return {"answer_type": "refused", "answer": guardrail.REFUSE_NOT_LOGGED_IN}
    u, question = state["understanding"], state["question"]
    if not _has_any(question, PLACEMENT_WORDS):
        return personal(state)  # only "if I pass X, am I placement-eligible?" is supported for now

    courses = tools.list_courses(student.student_id)
    text = " ".join([question, *u.assumptions]).lower()
    assume = sorted({c["course_code"] for c in courses if c["course_code"].lower() in text
                     or c["course_name"].lower() in text} | ({u.course_code} if u.course_code else set()))
    if not assume:
        return _clarify_course(courses)
    result = tools.check_placement_eligibility(student.student_id, state["as_of_date"], assume_passed=assume)
    assumptions = [f"You pass {code}: its latest result is treated as PASS." for code in assume]
    return _tool_fields(result) | {"assumptions": assumptions}


def clarify(state: AskState) -> dict:
    return {"answer_type": "clarification_needed", "answer": UNCLEAR_MESSAGE}


def _evidence_prompt(state: AskState) -> str:
    """The Compose input. Evidence is wrapped in tags and marked as data [BRIEF R8]."""
    parts = [f"Question: {state['question']}"]
    for chunk in state.get("chunks", []):
        informational = ' informational="true"' if chunk.source.authority_level >= UNTRUSTED_LEVEL else ""
        # Escape "<" so text inside a document can never close or fake an evidence tag [BRIEF R8].
        text = chunk.text.replace("<", "&lt;")
        parts.append(f'<evidence id="{chunk.chunk_id}" doc="{chunk.source.doc_id}" '
                     f'section="{chunk.section}"{informational}>\n{text}\n</evidence>')
    if state.get("tool_results"):
        outputs = [{"tool": r.tool, "output": r.output} for r in state["tool_results"]]
        parts.append("Tool outputs (already calculated by code):\n" + json.dumps(outputs))
    if state.get("applied_rules"):
        parts.append("Rules applied:\n" + json.dumps([r.model_dump() for r in state["applied_rules"]]))
        parts.append("Rule sources:\n" + json.dumps([c.model_dump() for c in state.get("rule_citations", [])]))
    if state.get("conflicts"):
        parts.append("Precedence notes:\n" + "\n".join(state["conflicts"]))
    if state.get("assumptions"):
        parts.append("Assumptions:\n" + "\n".join(state["assumptions"]))
    if state.get("upcoming"):
        parts.append("Upcoming changes (not yet in force):\n" + "\n".join(state["upcoming"]))
    if state.get("answer"):
        parts.append(f"The answer, already decided by code: {state['answer']}")
    return "\n\n".join(parts)


def _fallback_text(state: AskState) -> ComposeOutput:
    """Code-built wording, used in mock mode and whenever the LLM reply cannot be used."""
    if state["answer_type"] == "retrieved_fact":
        if state.get("applied_rules"):
            rule = state["applied_rules"][0]
            cites = state.get("rule_citations", [])
            where = f" ({cites[0].doc_id}, section {cites[0].section})" if cites else ""
            answer = f"The rule in force is {rule.value}{where}."
        else:
            top = state["chunks"][0]
            answer = f'{top.source.title}, section {top.section}: "{top.text[:300].strip()}"'
        return ComposeOutput(answer=answer, explanation="This answer is taken from the cited document.")
    if state["answer_type"] == "conflict_flagged":
        return ComposeOutput(answer=state["answer"],
                             explanation=" ".join(state.get("conflicts", [])) or state["answer"])
    return ComposeOutput(answer=state["answer"],
                         explanation="This result was calculated from your records using the cited rules.")


def _numbers_grounded(llm_text: str, prompt: str) -> bool:
    """Number grounding check (spec D.3 node 7): every number the LLM wrote must appear in what
    it was given (evidence, tool outputs, rules, the code's answer). 75 and 75.0 count as equal."""
    def normalise(n: str) -> str:
        return f"{float(n):g}"
    allowed = {normalise(n) for n in NUMBER.findall(prompt)}
    return all(normalise(n) in allowed for n in NUMBER.findall(llm_text))


def compose(state: AskState) -> dict:
    """LLM call 2: words the explanation. Skipped for fixed-message answers (spec D.3 node 7)."""
    if state["answer_type"] in ("refused", "not_found", "clarification_needed"):
        return {}
    fallback = _fallback_text(state)
    prompt = _evidence_prompt(state)
    result, usage = llm.chat_json(llm.COMPOSE_SYSTEM, prompt, ComposeOutput, fallback)
    if result is None or not _numbers_grounded(f"{result.answer} {result.explanation}", prompt):
        result = fallback  # never show a number the evidence does not contain [BRIEF R3]
    update = {"explanation": result.explanation,
              "llm_calls": state.get("llm_calls", 0) + usage.calls,
              "tokens": state.get("tokens", 0) + usage.tokens}
    # Only a retrieved fact takes its one-line answer from the LLM; everything else keeps the code's line.
    update["answer"] = result.answer if state["answer_type"] == "retrieved_fact" else fallback.answer
    return update


def assemble(state: AskState) -> dict:
    """Builds the API response. Citations come only from chunk and rule metadata [BRIEF R2]."""
    citations: list[Citation] = list(state.get("rule_citations", []))
    if state["answer_type"] in ("retrieved_fact", "conflict_flagged"):
        for chunk in state.get("chunks", []):
            if chunk.score >= config.MIN_SCORE and chunk.source.authority_level < UNTRUSTED_LEVEL:
                citations.append(Citation(doc_id=chunk.source.doc_id, title=chunk.source.title,
                                          section=chunk.section, page=chunk.page,
                                          version=chunk.source.version,
                                          effective_from=chunk.source.effective_from))
    # One citation per (document, section); a chunk citation (which knows its page) beats a rule's.
    by_clause: dict[tuple[str, str], Citation] = {}
    for citation in citations:
        key = (citation.doc_id, citation.section.replace(" ", ""))
        if key not in by_clause or (by_clause[key].page is None and citation.page is not None):
            by_clause[key] = citation
    unique = list(by_clause.values())
    response = AskResponse(
        trace_id=state["trace_id"], answer=state["answer"], answer_type=state["answer_type"],
        citations=unique,
        tools_invoked=[ToolInvocation(tool=r.tool, input=r.input, output=r.output)
                       for r in state.get("tool_results", [])],
        applied_rules=state.get("applied_rules", []), conflicts_detected=state.get("conflicts", []),
        explanation=state.get("explanation", ""), as_of_date=state["as_of_date"],
        upcoming_changes=state.get("upcoming", []), assumptions=state.get("assumptions", []),
    )
    return {"response": response}


def write_audit(state: AskState) -> dict:
    """Annex D record. No question text and no LLM reasoning [BRIEF R7, R10]."""
    audit.write(AuditRecord(
        trace_id=state["trace_id"],
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        student_id=state["student_id"],
        question_category=state["understanding"].category,
        sources_retrieved=state.get("sources_retrieved", []),
        precedence_decision=state.get("precedence_decision", ""),
        rules_applied=state.get("applied_rules", []),
        conflicts_detected=state.get("conflicts", []),
        tools_invoked=state.get("tool_results", []),
        answer_type=state["answer_type"],
        model=llm.model_name(),
        llm_calls=state.get("llm_calls", 0),
        tokens=state.get("tokens", 0),
        latency_ms=round((time.perf_counter() - state["started"]) * 1000, 1),
    ))
    return {}


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------
def build_graph():
    graph = StateGraph(AskState)
    for name, node in [("understand", understand), ("guardrail", check_access), ("policy", policy),
                       ("personal", personal), ("what_if", what_if), ("clarify", clarify),
                       ("compose", compose), ("assemble", assemble), ("audit", write_audit)]:
        graph.add_node(name, node)
    graph.add_edge(START, "understand")
    graph.add_edge("understand", "guardrail")
    graph.add_conditional_edges("guardrail", route, ["policy", "personal", "what_if", "clarify", "assemble"])
    for name in ("policy", "personal", "what_if", "clarify"):
        graph.add_edge(name, "compose")
    graph.add_edge("compose", "assemble")
    graph.add_edge("assemble", "audit")
    graph.add_edge("audit", END)
    return graph.compile()


GRAPH = build_graph()


def run_ask(question: str, as_of_date: str, student_id: str | None) -> AskResponse:
    state = GRAPH.invoke({"trace_id": audit.new_trace_id(), "question": question,
                          "as_of_date": as_of_date, "student_id": student_id,
                          "started": time.perf_counter()})
    return state["response"]
