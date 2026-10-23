"""
Annex A Source Precedence Policy, as pure functions.

Serves R4 (versions and conflicts). Given some rules, the documents they came
from and an as_of_date, this decides which rule is in force and why.

There are no database, LLM or network calls in this file on purpose: every
branch is unit-testable, and in the Q&A we can walk a judge through the exact
decision path. See PROJECT_SPEC D.4 (applicability) and D.5 (resolve_rules).

Inputs are plain dicts, so rows from SQLite or from a CSV both work unchanged.
Outputs use the shared models in app/schemas.py (WORKLOG section 3).
"""

from datetime import date
from typing import Any, Mapping, Sequence

from app.schemas import Applicability, Resolution, Rule

# Annex A.1: lower number = higher authority. Level 5 is untrusted and can
# never win a conflict; it may only ever be cited as informational.
UNTRUSTED_AUTHORITY_LEVEL = 5

# Annex A.2 step 2: only these levels may explicitly supersede another document.
SUPERSESSION_LEVELS = (1, 2)


# --------------------------------------------------------------------------
# Small helpers for the messy string formats in the Source Register (Annex B)
# --------------------------------------------------------------------------


def _text(row: Mapping[str, Any], key: str) -> str:
    """Read a field as a trimmed string. Missing or NULL becomes ''."""
    value = row.get(key)
    return "" if value is None else str(value).strip()


def _parse_date(value: str) -> date | None:
    """Parse YYYY-MM-DD. Anything unparseable is treated as 'not set'."""
    value = value.strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _split_list(value: str) -> list[str]:
    """Split a semicolon-separated Annex B field into trimmed, non-empty parts."""
    return [part.strip() for part in value.split(";") if part.strip()]


def _level_of(source: Mapping[str, Any]) -> int:
    """Authority level of a document; unreadable values are treated as untrusted."""
    try:
        return int(_text(source, "authority_level"))
    except ValueError:
        return UNTRUSTED_AUTHORITY_LEVEL


def _to_rule(row: Mapping[str, Any]) -> Rule:
    """Build the shared Rule model from a rule_registry row."""
    return Rule(
        rule_id=_text(row, "rule_id"),
        description=_text(row, "description"),
        parameter=_text(row, "parameter"),
        operator=_text(row, "operator") or ">=",
        value=_text(row, "value"),
        scope_programmes=_text(row, "scope_programmes") or "ALL",
        scope_batches=_text(row, "scope_batches") or "ALL",
        effective_from=_text(row, "effective_from"),
        effective_to=_text(row, "effective_to") or None,
        source_doc_id=_text(row, "source_doc_id"),
        source_section=_text(row, "source_section"),
        origin=_text(row, "origin") or "manual",
    )


def scope_covers_programme(scope: str, programme: str | None) -> bool:
    """
    Annex B scope_programmes: 'ALL', or a ';' list such as 'B.Tech CSE;B.Tech IT'.

    With no student (a general question) only 'ALL' passes, so we never apply a
    programme-specific rule to someone we cannot place (PROJECT_SPEC D.4).
    """
    scope = scope.strip()
    if not scope or scope.upper() == "ALL":
        return True
    if programme is None:
        return False
    wanted = programme.strip().casefold()
    return any(part.casefold() == wanted for part in _split_list(scope))


def scope_covers_batch(scope: str, batch_year: int | None) -> bool:
    """Annex B scope_batches: 'ALL', '2023+' (that year onwards), or '2022;2023'."""
    scope = scope.strip()
    if not scope or scope.upper() == "ALL":
        return True
    if batch_year is None:
        return False
    for part in _split_list(scope):
        if part.endswith("+"):
            start = part[:-1].strip()
            if start.isdigit() and batch_year >= int(start):
                return True
        elif part.isdigit() and batch_year == int(part):
            return True
    return False


# --------------------------------------------------------------------------
# Annex A.2 step 1
# --------------------------------------------------------------------------


def applicability(
    source: Mapping[str, Any],
    as_of_date: date,
    student: Mapping[str, Any] | None = None,
) -> Applicability:
    """
    Decide whether one document applies on as_of_date (Annex A.2 step 1).

    Scope is checked before dates: a document that does not cover this student
    is irrelevant whatever its date, and must not be announced to them as an
    upcoming change.
    """
    programme = (_text(student, "programme") or None) if student else None
    batch_year = student.get("batch_year") if student else None

    if not scope_covers_programme(_text(source, "scope_programmes"), programme):
        return "out_of_scope"
    if not scope_covers_batch(_text(source, "scope_batches"), batch_year):
        return "out_of_scope"

    effective_from = _parse_date(_text(source, "effective_from"))
    if effective_from and effective_from > as_of_date:
        return "upcoming"

    effective_to = _parse_date(_text(source, "effective_to"))
    if effective_to and effective_to < as_of_date:
        return "expired"

    return "current"


# --------------------------------------------------------------------------
# Annex A.2 steps 2 to 5
# --------------------------------------------------------------------------


def _superseded_keys(current_sources: Sequence[Mapping[str, Any]]) -> set[str]:
    """
    Collect every doc_id and doc_id#clause named in the `supersedes` field of an
    applicable level 1-2 document (Annex A.2 step 2).
    """
    keys: set[str] = set()
    for source in current_sources:
        if _level_of(source) in SUPERSESSION_LEVELS:
            keys.update(_split_list(_text(source, "supersedes")))
    return keys


def resolve_rules(
    rules: Sequence[Mapping[str, Any]],
    sources: Sequence[Mapping[str, Any]],
    as_of_date: date,
    student: Mapping[str, Any] | None = None,
) -> Resolution:
    """
    Apply Annex A.2 steps 1-5 and say which rule wins, and by which step.

    `step_used` is the earliest step that eliminated a rival, which is how the
    brief's own worked example (A.3) reports its answer as "step 2".
    """
    by_doc_id = {_text(s, "doc_id"): s for s in sources}
    overridden: list[Rule] = []
    reasons: dict[str, str] = {}  # rule_id -> why it lost, for decision_text

    def drop(rule_row: Mapping[str, Any], reason: str) -> None:
        rule = _to_rule(rule_row)
        overridden.append(rule)
        reasons[rule.rule_id] = reason

    # --- Step 1: applicability of the rule and of the document behind it ---
    candidates: list[Rule] = []
    levels: dict[str, int] = {}  # rule_id -> authority level of its source
    for row in rules:
        doc_id = _text(row, "source_doc_id")
        source = by_doc_id.get(doc_id)
        if source is None:
            # Authority is unknown, so the rule cannot be trusted or ranked.
            drop(row, f"source document {doc_id} is not registered (step 1)")
            continue

        doc_state = applicability(source, as_of_date, student)
        rule_state = applicability(row, as_of_date, student)
        if doc_state != "current" or rule_state != "current":
            state = doc_state if doc_state != "current" else rule_state
            drop(row, f"not in force on {as_of_date.isoformat()}: {state} (step 1)")
            continue

        level = _level_of(source)
        # Annex A: level 5 is informational only and can never decide a value.
        if level >= UNTRUSTED_AUTHORITY_LEVEL:
            drop(row, f"{doc_id} is level {level} (untrusted), cannot decide a value")
            continue

        rule = _to_rule(row)
        levels[rule.rule_id] = level
        candidates.append(rule)

    if not candidates:
        return Resolution(
            status="NO_RULE",
            overridden=overridden,
            decision_text=f"no applicable rule on {as_of_date.isoformat()} (step 1)",
        )

    # Step 1 only filters out rules that do not apply at all; it never decides
    # between genuine rivals, so it must not claim to be the deciding step.
    step_used: int | None = None

    # --- Step 2: explicit supersession by an applicable level 1-2 document ---
    current_sources = [
        s for s in sources if applicability(s, as_of_date, student) == "current"
    ]
    superseded = _superseded_keys(current_sources)
    survivors: list[Rule] = []
    for rule in candidates:
        clause_key = f"{rule.source_doc_id}#{rule.source_section}"
        hit = next((k for k in (clause_key, rule.source_doc_id) if k in superseded), None)
        if hit is None:
            survivors.append(rule)
            continue
        superseding = next(
            (_text(s, "doc_id") for s in current_sources
             if hit in _split_list(_text(s, "supersedes"))),
            "a later document",
        )
        overridden.append(rule)
        reasons[rule.rule_id] = f"{superseding} supersedes {hit} (step 2)"
        step_used = 2 if step_used is None else step_used

    # Supersession must never wipe out every rule; if it does, report a conflict
    # rather than silently returning nothing (PROJECT_SPEC D.6 safety net).
    if not survivors:
        return Resolution(
            status="CONFLICT",
            conflicts=candidates,
            overridden=overridden,
            decision_text="every applicable rule was superseded but no replacement exists (step 5)",
            step_used=5,
        )

    # --- Step 3: authority (lowest level number wins, regardless of date) ---
    best_level = min(levels[rule.rule_id] for rule in survivors)
    ranked: list[Rule] = []
    for rule in survivors:
        if levels[rule.rule_id] == best_level:
            ranked.append(rule)
        else:
            overridden.append(rule)
            reasons[rule.rule_id] = (
                f"lower authority: level {levels[rule.rule_id]} loses to "
                f"level {best_level} (step 3)"
            )
            step_used = 3 if step_used is None else step_used

    # --- Step 4: recency among equals ---
    if len(ranked) > 1:
        latest = max((_parse_date(r.effective_from) or date.min) for r in ranked)
        newest: list[Rule] = []
        for rule in ranked:
            if (_parse_date(rule.effective_from) or date.min) == latest:
                newest.append(rule)
            else:
                overridden.append(rule)
                reasons[rule.rule_id] = (
                    f"superseded by recency: {rule.effective_from} is older than "
                    f"{latest.isoformat()} (step 4)"
                )
                step_used = 4 if step_used is None else step_used
        ranked = newest

    # --- Step 5: anything left that disagrees is an unresolved conflict ---
    if len({rule.value for rule in ranked}) > 1:
        names = " and ".join(f"{r.source_doc_id}#{r.source_section}" for r in ranked)
        return Resolution(
            status="CONFLICT",
            conflicts=ranked,
            overridden=overridden,
            decision_text=f"precedence could not separate {names} (step 5)",
            step_used=5,
        )

    winner = ranked[0]
    step_used = step_used or 1
    return Resolution(
        status="RESOLVED",
        winner=winner,
        overridden=overridden,
        decision_text=_decision_text(winner, reasons, step_used),
        step_used=step_used,
    )


def _decision_text(winner: Rule, reasons: dict[str, str], step: int) -> str:
    """
    One plain sentence for the audit record (Annex D `precedence_decision`).

    For step 2 the brief's own example reads
    "ACAD-2026-08 supersedes ACAD-REG-2024#7.2 (step 2)", so we reuse the
    reason we already recorded instead of inventing new wording.
    """
    if step in (2, 3, 4):
        for reason in reasons.values():
            if reason.endswith(f"(step {step})"):
                return reason
    return (f"{winner.source_doc_id}#{winner.source_section} applies: "
            f"{winner.parameter} {winner.operator} {winner.value} (step {step})")
