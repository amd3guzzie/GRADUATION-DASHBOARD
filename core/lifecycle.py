import datetime as dt
import json
from typing import Any

import pandas as pd

# Local imports
# Local imports
from config.settings import (
    DASHBOARD_FIELDS, REQUIRED_FIELDS, STATUS_VOCABULARY, 
    UNKNOWN, PILLARS, PILLAR_FIELD, WITHDRAWN_STATUSES, COMPLETED_STATUSES,
    STAGE_COURSEWORK, STAGE_COMP_EXAM, STAGE_CAPSTONE, STAGE_COMPLETED, STAGE_REMAINING,
    DEFAULT_MAX_DAYS_IN_PROGRESS
)
from db.queries import fetch_students

VALID_KINDS = {"direct", "lookup", "milestone"}

def validate_field_map(field_map: dict[str, dict[str, Any]]) -> list[str]:
    problems: list[str] = []
    for name in REQUIRED_FIELDS:
        if name not in field_map:
            problems.append(f"{name} has no mapping.")
    for name, spec in field_map.items():
        if name not in DASHBOARD_FIELDS:
            problems.append(f"{name} is not a dashboard field.")
            continue
        if not isinstance(spec, dict):
            problems.append(f"{name} mapping is not a valid record.")
            continue
        kind = spec.get("kind")
        if kind not in VALID_KINDS:
            problems.append(f"{name} has an unrecognised source kind: {kind!r}.")
            continue
        if kind in ("direct", "lookup") and not spec.get("column"):
            problems.append(f"{name} is missing a source column.")
        if kind == "lookup" and not spec.get("embed"):
            problems.append(f"{name} is missing the related table to read from.")
        if kind == "milestone" and not spec.get("milestone_type"):
            problems.append(f"{name} is missing a milestone type.")
    return problems

def _apply_value_map(raw: Any, spec: dict[str, Any], field_name: str) -> str:
    value_map = {str(k).strip().lower(): v for k, v in (spec.get("value_map") or {}).items()}
    key = "" if raw is None else str(raw).strip().lower()
    if not value_map:
        return "" if raw is None else str(raw)
    mapped = value_map.get(key)
    if mapped is not None:
        return mapped
    vocabulary = STATUS_VOCABULARY.get(field_name)
    if vocabulary:
        for allowed in vocabulary:
            if allowed.lower() == key:
                return allowed
        return UNKNOWN
    return "" if raw is None else str(raw)

def _first(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if value else None
    return value

def resolve_field(row: dict[str, Any], field_name: str, spec: dict[str, Any]) -> Any:
    kind = spec.get("kind")
    if kind == "direct":
        raw = row.get(spec["column"])
    elif kind == "lookup":
        related = _first(row.get(spec["embed"]))
        raw = related.get(spec["column"]) if isinstance(related, dict) else None
    elif kind == "milestone":
        raw = None
        wanted = str(spec["milestone_type"]).strip().lower()
        for milestone in row.get("student_milestones") or []:
            if str(milestone.get("milestone_type", "")).strip().lower() == wanted:
                raw = milestone.get("status")
                break
    else:
        raw = None

    if field_name in STATUS_VOCABULARY or spec.get("value_map"):
        return _apply_value_map(raw, spec, field_name)
    return raw

def resolve_row(row: dict[str, Any], field_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    record = {name: resolve_field(row, name, spec) for name, spec in field_map.items()}
    for name in DASHBOARD_FIELDS:
        record.setdefault(name, None)

    record["full_name"] = " ".join(
        part for part in [record.get("first_name"), record.get("last_name")] if part
    ).strip()

    milestone_dates = {
        str(m.get("milestone_type", "")).strip().lower(): m.get("updated_at")
        for m in row.get("student_milestones") or []
    }
    record["coursework_updated"] = row.get("coursework_last_updated") or row.get("updated_at")
    record["comprehensive_exam_updated"] = milestone_dates.get("comprehensive_exam")
    record["capstone_updated"] = milestone_dates.get("capstone")
    record["courses"] = row.get("student_course_enrollments") or []
    return record

def build_dataframe(raw_rows: list[dict[str, Any]], field_map: dict[str, dict[str, Any]]) -> pd.DataFrame:
    records = [resolve_row(row, field_map) for row in raw_rows]
    frame = pd.DataFrame(records)
    if frame.empty:
        return pd.DataFrame(columns=DASHBOARD_FIELDS + ["full_name", "courses"])
    return frame

def band_for(field_name: str, status: str, bands: dict[str, dict[str, str]]) -> str:
    return bands.get(field_name, {}).get(status, "grey")

def badge(field_name: str, status: str, bands: dict[str, dict[str, str]]) -> str:
    band = band_for(field_name, status, bands)
    return (
        f"<span class='status-badge' style='--badge:{BAND_COLORS[band]}'>"
        f"<span class='status-glyph'>{BAND_GLYPHS[band]}</span>"
        f"{status or UNKNOWN}</span>"
    )

def indicator_text(field_name: str, status: str, bands: dict[str, dict[str, str]]) -> str:
    band = band_for(field_name, status, bands)
    return f"{BAND_GLYPHS[band]} {status or UNKNOWN}"

def is_enrolled(record, rule: dict[str, Any]) -> bool:
    """True when the student is still part of the program (not withdrawn).
    Graduated students still count here: this is the cohort that completion
    % and the stage chart are measured against."""
    if str(record.get("enrollment_status") or "").strip().lower() in WITHDRAWN_STATUSES:
        return False
    if str(record.get("coursework_status") or "") in (rule.get("exclude_coursework_status") or []):
        return False
    remarks = str(record.get("remarks") or "").lower()
    return not any(phrase.lower() in remarks for phrase in rule.get("exclude_when_remarks_contains") or [])

def enrolled_frame(frame: pd.DataFrame, rule: dict[str, Any]) -> pd.DataFrame:
    if frame.empty:
        return frame
    if "_is_enrolled" in frame.columns:
        return frame.loc[frame["_is_enrolled"].fillna(False)]
    mask = pd.Series(True, index=frame.index)
    if "enrollment_status" in frame.columns:
        enrollment = frame["enrollment_status"].fillna("").astype(str).str.strip().str.lower()
        mask &= ~enrollment.isin(WITHDRAWN_STATUSES)
    if "coursework_status" in frame.columns:
        excluded_statuses = rule.get("exclude_coursework_status") or []
        if excluded_statuses:
            mask &= ~frame["coursework_status"].fillna("").astype(str).isin(excluded_statuses)
    if "remarks" in frame.columns:
        remarks = frame["remarks"].fillna("").astype(str).str.lower()
        for phrase in rule.get("exclude_when_remarks_contains") or []:
            phrase = str(phrase).strip().lower()
            if phrase:
                mask &= ~remarks.str.contains(phrase, regex=False, na=False)
    return frame.loc[mask]

def lifecycle_stage(record) -> str:
    """The furthest stage a student has reached, used by the stage chart,
    its drill-down and the roster's Stage column so they always agree."""
    if str(record.get("capstone_status") or "") == "Defended for Completion":
        return STAGE_COMPLETED
    if str(record.get("enrollment_status") or "").strip().lower() in COMPLETED_STATUSES:
        return STAGE_COMPLETED
    if str(record.get("comprehensive_exam_status") or "") == "Passed":
        return STAGE_CAPSTONE
    if str(record.get("coursework_status") or "") == "Completed":
        return STAGE_COMP_EXAM
    return STAGE_COURSEWORK

def lifecycle_stages(frame: pd.DataFrame) -> pd.Series:
    """Classify a roster in columns instead of invoking Python once per row."""
    if "_lifecycle_stage" in frame.columns:
        return frame["_lifecycle_stage"]
    if frame.empty:
        return pd.Series(index=frame.index, dtype="object")

    coursework = frame.get("coursework_status", pd.Series("", index=frame.index)).fillna("").astype(str)
    comp_exam = frame.get("comprehensive_exam_status", pd.Series("", index=frame.index)).fillna("").astype(str)
    capstone = frame.get("capstone_status", pd.Series("", index=frame.index)).fillna("").astype(str)
    enrollment = frame.get("enrollment_status", pd.Series("", index=frame.index)).fillna("").astype(str).str.strip().str.lower()

    stages = pd.Series(STAGE_COURSEWORK, index=frame.index, dtype="object")
    stages.loc[coursework == "Completed"] = STAGE_COMP_EXAM
    stages.loc[comp_exam == "Passed"] = STAGE_CAPSTONE
    completed = capstone.eq("Defended for Completion") | enrollment.isin(COMPLETED_STATUSES)
    stages.loc[completed] = STAGE_COMPLETED
    return stages

def is_active(record, rule: dict[str, Any]) -> bool:
    """US-05: an enrolled (active) student is in the program and has not
    completed it yet."""
    return is_enrolled(record, rule) and lifecycle_stage(record) != STAGE_COMPLETED

def students_in_stage(frame: pd.DataFrame, stage: str) -> pd.DataFrame:
    if frame.empty:
        return frame
    stages = lifecycle_stages(frame)
    if stage == STAGE_REMAINING:
        return frame[stages != STAGE_COMPLETED]
    return frame[stages == stage]

def overdue_limits(settings: dict[str, Any]) -> dict[str, int]:
    """US-26 / US-27: days a student may stay in progress on each stage
    before being flagged. One program-wide value, with optional per-stage
    overrides saved on the Program tab."""
    default = int(settings.get("max_days_in_progress") or DEFAULT_MAX_DAYS_IN_PROGRESS)
    per_stage = settings.get("max_days_per_stage") or {}
    return {pillar_key: int(per_stage.get(pillar_key) or default) for pillar_key, _ in PILLARS}

# Statuses that mean "still working on this stage". Coursework has no
# In-Progress value, so Pending plays that role for it (US-26).
IN_PROGRESS_STATUSES = {
    "coursework": {"Pending"},
    "comprehensive_exam": {"In-Progress"},
    "capstone": {"In-Progress"},
}

def overall_status_label(record, bands: dict[str, dict[str, str]], max_days: int | dict[str, int] = DEFAULT_MAX_DAYS_IN_PROGRESS,
                          rule: dict[str, Any] | None = None, labels: dict[str, str] | None = None) -> str:
    # A student removed from the program (per the same remarks phrases the
    # enrollment rule uses) is exactly what status_thresholds marks Enrollment:
    # Withdrawn as Red for -- catch it before anything else so it's never lost,
    # whichever list this label ends up feeding.
    remarks = str(record.get("remarks") or "").lower()
    flagged_phrases = [str(p).lower() for p in ((rule or {}).get("exclude_when_remarks_contains") or [])]
    if any(phrase in remarks for phrase in flagged_phrases):
        return "Needs Attention (Out Of Program)"
    if str(record.get("enrollment_status") or "").strip().lower() in WITHDRAWN_STATUSES:
        return "Needs Attention (Out Of Program)"

    # Name the stage that is red so the at-risk list can show why (US-28).
    for pillar_key, pillar_name in PILLARS:
        status = str(record.get(PILLAR_FIELD[pillar_key]) or "")
        if band_for(PILLAR_FIELD[pillar_key], status, bands) == "red":
            name = (labels or {}).get(pillar_key) or pillar_name
            return f"Needs Attention ({name}: {status})"

    # A failed or incomplete individual course (status_thresholds: Course:
    # abs/failed -> Red, cancelled -> Red) can hide inside an aggregate
    # coursework_status of "Pending", which only bands as amber -- check the
    # underlying course grades directly rather than relying on the aggregate.
    course_statuses = {str(c.get("status") or "").strip().lower() for c in (record.get("courses") or [])}
    if "abs/failed" in course_statuses:
        return "Needs Attention (Failed Coursework)"
    if "incomplete" in course_statuses:
        return "Needs Attention (Incomplete Grade)"

    # SPRINT 2: PHASE 4 - AUTOMATED RISK FLAGGING (US-26)
    # The reason says which stage and by how many days, e.g.
    # "Needs Attention (Overdue in Capstone by 45 days)".
    if isinstance(max_days, dict):
        limits = max_days
    else:
        limits = {pillar_key: int(max_days) for pillar_key, _ in PILLARS}
    now = dt.datetime.now(dt.timezone.utc)
    for pillar_key, pillar_name in PILLARS:
        if str(record.get(PILLAR_FIELD[pillar_key])) in IN_PROGRESS_STATUSES[pillar_key]:
            updated_str = record.get(f"{pillar_key}_updated")
            if updated_str:
                try:
                    updated_dt = dt.datetime.fromisoformat(str(updated_str).replace("Z", "+00:00"))
                    if updated_dt.tzinfo is None:
                        updated_dt = updated_dt.replace(tzinfo=dt.timezone.utc)
                    days_waiting = (now - updated_dt).days
                    limit = limits.get(pillar_key, DEFAULT_MAX_DAYS_IN_PROGRESS)
                    if days_waiting > limit:
                        name = (labels or {}).get(pillar_key) or pillar_name
                        return f"Needs Attention (Overdue in {name} by {days_waiting - limit} days)"
                except Exception:
                    pass

    if band_for("capstone_status", str(record.get("capstone_status") or ""), bands) == "green":
        return "Completed"
    if lifecycle_stage(record) == STAGE_COMPLETED:
        return "Completed"
    return "In Progress"

def attention_reason(label: Any) -> str:
    """Pulls the reason out of "Needs Attention (reason)" for the at-risk
    table (US-28). A bare "Needs Attention" means a red status on a stage."""
    text = str(label or "")
    if not text.startswith("Needs Attention"):
        return ""
    match = re.search(r"\((.*)\)", text)
    return match.group(1) if match else "Red status on a lifecycle stage"

def load_dashboard_frame(
    program_code: str,
    scope_column: str,
    field_map: dict[str, dict[str, Any]],
    status_bands: dict[str, dict[str, str]],
    limits: dict[str, int],
    enrollment_rule: dict[str, Any],
    labels: dict[str, str],
) -> pd.DataFrame:
    """Build the dashboard frame from the latest database student records."""
    raw = fetch_students(program_code, scope_column)
    frame = build_dataframe(raw, field_map)
    if not frame.empty:
        frame["overall_status"] = frame.apply(
            lambda row: overall_status_label(row, status_bands, limits, enrollment_rule, labels),
            axis=1,
        )
        frame["_lifecycle_stage"] = lifecycle_stages(frame)
        frame["_is_enrolled"] = frame.index.isin(enrolled_frame(frame, enrollment_rule).index)
    return frame