import json
from html import escape
from urllib.parse import quote
from typing import Any
import datetime as dt

import pandas as pd
import streamlit as st

# Local imports
from config.settings import *
from db.queries import *
from core.lifecycle import *
from ui.components import *

def _matches_search(frame: pd.DataFrame, query: str) -> pd.DataFrame:
    query = query.strip()
    if not query:
        return frame
    ids = frame["student_id"].astype(str)
    names = frame["full_name"].fillna("").str.lower()
    emails = frame["email"].fillna("").astype(str).str.lower()
    needle = query.lower()
    # regex=False so typing "(" or "+" searches for that text instead of crashing.
    return frame[(ids == query) | names.str.contains(needle, regex=False) | emails.str.contains(needle, regex=False)]

def roster_export_frame(runtime: RuntimeConfig, frame: pd.DataFrame, include_reason: bool = False) -> pd.DataFrame:
    """US-31: the columns people see on screen, with readable headers, for
    the CSV export (instead of the raw internal column names)."""
    export = pd.DataFrame({
        "Student ID": frame["student_id"].astype(str),
        "Last name": frame["last_name"],
        "First name": frame["first_name"],
        "Email": frame["email"] if "email" in frame.columns else "",
        "Term / cohort": frame["cohort"],
        "Stage": lifecycle_stages(frame).map(runtime.stage_label).tolist(),
        "Overall status": frame["overall_status"] if "overall_status" in frame.columns else "",
        runtime.pillar_label("coursework"): frame["coursework_status"],
        runtime.pillar_label("comprehensive_exam"): frame["comprehensive_exam_status"],
        runtime.pillar_label("capstone"): frame["capstone_status"],
        "Adviser": frame["adviser"],
    })
    if include_reason:
        export.insert(2, "Reason flagged", frame["overall_status"].apply(attention_reason).values)
    return export.reset_index(drop=True)

@st.dialog("Student Profile", width="large")
def profile_dialog(runtime: RuntimeConfig, session: Session, record: pd.Series) -> None:
    _render_profile_card(runtime, session, record, context="dialog")

def view_students(runtime: RuntimeConfig, session: Session, frame: pd.DataFrame) -> None:
    with st.container(border=True):
        st.markdown('<h4 class="section-card-title">Student Roster</h4>', unsafe_allow_html=True)
        _roster_breadcrumb(runtime)
        if frame.empty:
            st.info("No students are mapped to this program yet. An IT/Admin can load the source data, then use Refresh in the header above.")
            return
        _student_roster_fragment(runtime, session, frame)

def roster_filter_label(runtime: RuntimeConfig, roster_filter: str) -> str:
    if roster_filter == "enrolled":
        return "All enrolled students"
    if roster_filter == "at_risk":
        return "Students needing attention"
    return runtime.stage_label(roster_filter)

def _roster_breadcrumb(runtime: RuntimeConfig) -> None:
    """US-21: after drilling in from a tile or chart, show where the list
    came from and a way back. Term and cohort filters stay as they were."""
    roster_filter = st.session_state.get("roster_filter")
    if not roster_filter:
        return
    crumb_col, back_col, clear_col = st.columns([3, 1.2, 1.2])
    crumb_col.markdown(f"Dashboard › **{roster_filter_label(runtime, roster_filter)}**")
    if back_col.button("← Back to dashboard", key="roster_back", width="stretch"):
        st.session_state.pop("roster_filter", None)
        st.session_state["sidebar_menu"] = st.session_state.pop("roster_return_page", PAGE_OVERVIEW)
        st.rerun()
    if clear_col.button("Show all students", key="roster_show_all", width="stretch"):
        st.session_state.pop("roster_filter", None)
        st.session_state.pop("roster_return_page", None)
        st.rerun()

@st.fragment
def _student_roster_fragment(runtime: RuntimeConfig, session: Session, frame: pd.DataFrame) -> None:
    # =========================================================
    # SPRINT 2: PHASE 3 - MY ADVISEES FILTER (US-23)
    # =========================================================
    # An advisor's account is matched to the adviser column by the
    # "adviser_name" saved on their account (Admin Config > Users), or by
    # their display name. Advisors start on their own students; if they have
    # none yet they see an empty-state message instead of everyone.
    all_advisers = "All Advisers"
    advisors = [all_advisers] + sorted({str(a) for a in frame["adviser"].dropna().unique() if str(a).strip()})
    my_name = session.adviser_name or session.full_name
    if session.role == ROLE_STAFF and my_name not in advisors:
        advisors.insert(1, my_name)
    if st.session_state.get("advisor_filter") not in advisors:
        st.session_state["advisor_filter"] = my_name if session.role == ROLE_STAFF else all_advisers

    def clear_roster_filters():
        # Runs as an on_click callback, i.e. before the widgets are drawn again,
        # which is the only time Streamlit lets us reset their values.
        st.session_state["search_text"] = ""
        st.session_state["cohort_filter"] = ALL_COHORTS
        st.session_state["advisor_filter"] = all_advisers
        st.session_state.pop("roster_filter", None)
        st.session_state["_roster_filters_cleared"] = True

    f1, f2, f3, f4 = st.columns([1.1, 1.7, 1.6, 1.05], gap="small")
    with f1:
        advisor_choice = st.selectbox("Adviser", advisors, key="advisor_filter",
                                      format_func=lambda a: f"{a} (my advisees)" if a == my_name and session.role == ROLE_STAFF else a)
        count_slot = st.empty()
    with f2:
        query = st.text_input("Search", key="search_text", placeholder="Name, email or exact ID")
    with f3:
        sort_choice = st.selectbox("Sort by", list(SORT_OPTIONS), key="sort_choice")
    with f4:
        st.markdown("<div style='height: 29px;'></div>", unsafe_allow_html=True)
        st.button("Clear filters", width="stretch", on_click=clear_roster_filters)
        export_slot = st.empty()

    # The cohort picker lives outside this fragment, so rerun the whole page
    # once after clearing to show it reset too.
    if st.session_state.pop("_roster_filters_cleared", False):
        st.rerun(scope="app")

    cohort = st.session_state.get("cohort_filter", ALL_COHORTS)
    working = frame if cohort == ALL_COHORTS else frame[frame["cohort"] == cohort]
    roster_filter = st.session_state.get("roster_filter")
    if roster_filter == "at_risk":
        working = working[working["overall_status"].astype(str).str.startswith("Needs Attention")]
    elif roster_filter == "enrolled":
        working = enrolled_frame(working, runtime.enrollment_rule)
    elif roster_filter:
        working = students_in_stage(enrolled_frame(working, runtime.enrollment_rule), roster_filter)
    if advisor_choice != all_advisers:
        working = working[working["adviser"].astype(str) == advisor_choice]
    working = _matches_search(working, query)

    # Helper columns so "Overall status" sorts problems first and IDs sort
    # as numbers (US-03).
    working = working.assign(
        _overall_rank=working["overall_status"].apply(overall_rank) if "overall_status" in working.columns else 3,
        _id_number=pd.to_numeric(working["student_id"], errors="coerce"),
    )
    sort_column, ascending = SORT_OPTIONS[sort_choice]
    if sort_column in working.columns and not working.empty:
        working = working.sort_values([sort_column, "last_name"], ascending=[ascending, True], kind="stable")

    count_slot.markdown(
        f'<div style="margin-left: 10px; font-weight: 700;">{len(working)} students</div>',
        unsafe_allow_html=True,
    )
    if not working.empty:
        # US-31: readable headers, Excel-friendly encoding (utf-8-sig keeps
        # names like "Mapúa" intact) and every export is logged.
        export = roster_export_frame(runtime, working)
        if export_slot.download_button(
            "Export CSV ⤓",
            data=export.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"student_roster_{runtime.program.program_code}.csv",
            mime="text/csv",
            width="stretch",
        ):
            filters = (f"term={st.session_state.get('term_filter', ALL_TERMS)}; cohort={cohort}; adviser={advisor_choice}; "
                       f"search={query!r}; view={roster_filter or 'all'}")
            log_access(session.username, session.role, "export student roster", "allowed", f"{len(export)} rows; {filters}")

    if working.empty:
        if session.role == ROLE_STAFF and advisor_choice == my_name and not query:
            st.info("You don't have any advisees assigned in this term yet. Pick \"All Advisers\" to browse the full roster.", icon="\U0001f4cb")
        else:
            st.warning("No students match that search. Check the spelling, or clear the filters.", icon="\U0001f50d")
        return

    # US-19: when drilled into "remaining", show how those students split by stage.
    if roster_filter == STAGE_REMAINING:
        stage_counts = lifecycle_stages(working).value_counts()
        st.caption("By stage: " + " · ".join(
            f"{runtime.stage_label(stage)}: {int(stage_counts.get(stage, 0))}" for stage in STAGE_ORDER[:-1]
        ))

    def _overall_text(lbl):
        if str(lbl).startswith("Needs Attention"): return "✖ " + str(lbl)
        if lbl == "Completed": return "✔ Completed"
        return "◓ In Progress"

    cw_label = runtime.pillar_label("coursework")
    ce_label = runtime.pillar_label("comprehensive_exam")
    cap_label = runtime.pillar_label("capstone")
    display_df = pd.DataFrame({
        "ID": working["student_id"].astype(str),
        "Name": working["full_name"],
        "Cohort": working["cohort"],
        "Stage": lifecycle_stages(working).map(runtime.stage_label).tolist(),
        "Overall": working["overall_status"].apply(_overall_text),
        cw_label: [indicator_text("coursework_status", v, runtime.status_bands) for v in working["coursework_status"].fillna(UNKNOWN)],
        ce_label: [indicator_text("comprehensive_exam_status", v, runtime.status_bands) for v in working["comprehensive_exam_status"].fillna(UNKNOWN)],
        cap_label: [indicator_text("capstone_status", v, runtime.status_bands) for v in working["capstone_status"].fillna(UNKNOWN)],
        "Adviser": working["adviser"].apply(_or_dash)
    }).reset_index(drop=True)

    st.markdown(
        '<div class="student-table-hint">Click any student data cell to open that student\'s profile. '
        'Use the table scrollbars to view every column.</div>',
        unsafe_allow_html=True,
    )
    event = st.dataframe(
        display_df,
        hide_index=True,
        width="stretch",
        height=650,
        key="student_roster_dataframe",
        column_config={
            "ID": st.column_config.TextColumn(width=105),
            "Name": st.column_config.TextColumn(width=175),
            "Cohort": st.column_config.TextColumn(width=80),
            "Stage": st.column_config.TextColumn(width=140),
            "Overall": st.column_config.TextColumn(width=300),
            cw_label: st.column_config.TextColumn(width=135),
            ce_label: st.column_config.TextColumn(width=145),
            cap_label: st.column_config.TextColumn(width=175),
            "Adviser": st.column_config.TextColumn(width=170),
        },
        on_select="rerun",
        selection_mode="single-cell"
    )

    if hasattr(event, "selection") and event.selection.cells:
        # Single-cell selection fires from any data cell, avoiding the row
        # checkbox being the only obvious way to open a student's profile.
        selected_cell = event.selection.cells[-1]
        selected_idx = int(selected_cell[0]) if isinstance(selected_cell, (tuple, list)) else -1
        if 0 <= selected_idx < len(display_df):
            selected_id = display_df.iloc[selected_idx]["ID"]
            record = working[working["student_id"].astype(str) == selected_id].iloc[0]
            profile_dialog(runtime, session, record)

    legend("coursework_status", runtime.status_bands)

def _profile_print_document(runtime: RuntimeConfig, record, courses, history) -> str:
    """Build one self-contained, print-ready HTML document for a student profile."""
    def text_value(value) -> str:
        return escape(_or_dash(value))

    if isinstance(courses, pd.DataFrame):
        course_rows = courses.to_dict(orient="records")
    elif isinstance(courses, dict):
        course_rows = [courses]
    elif isinstance(courses, (list, tuple)):
        course_rows = list(courses)
    else:
        course_rows = []

    course_table_rows = []
    for course in course_rows:
        if not isinstance(course, dict):
            continue
        course_name = course.get("course_code", course.get("Course", course.get("course")))
        course_status = course.get("status", course.get("Status"))
        cells = [text_value(course_name), text_value(course_status)]
        course_table_rows.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>")
    course_table = (
        f"<table><thead><tr><th>Course</th><th>Status</th></tr></thead><tbody>{''.join(course_table_rows)}</tbody></table>"
        if course_table_rows else '<p class="empty">No coursework records are available.</p>'
    )

    history_table_rows = []
    for item in history or []:
        pillar = item.get("pillar")
        try:
            pillar_label = runtime.pillar_label(str(pillar)) if pillar else "\u2014"
        except (KeyError, ValueError):
            pillar_label = str(pillar or "\u2014").replace("_", " ").title()
        history_cells = [
            text_value(humanise(item.get("changed_at"))),
            text_value(pillar_label),
            text_value(item.get("old_status")),
            text_value(item.get("new_status")),
            text_value(item.get("changed_by")),
        ]
        history_table_rows.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in history_cells) + "</tr>")
    history_table = (
        "<table><thead><tr><th>When</th><th>Stage</th><th>From</th><th>To</th><th>Changed by</th></tr></thead>"
        f"<tbody>{''.join(history_table_rows)}</tbody></table>"
        if history_table_rows else '<p class="empty">No status history is available.</p>'
    )

    status_cards = []
    for pillar_key, _ in PILLARS:
        field_name = PILLAR_FIELD[pillar_key]
        status = _or_dash(record.get(field_name))
        band = band_for(field_name, status, runtime.status_bands)
        style = BAND_PILL_STYLE.get(band, BAND_PILL_STYLE["grey"])
        stamp = humanise(record.get(f"{pillar_key}_updated"))
        stamp_text = "not recorded" if stamp == "never" else stamp
        status_cards.append(
            '<div class="status-card">'
            f'<div class="label">{escape(runtime.pillar_label(pillar_key))}</div>'
            f'<span class="badge" style="color:{style["color"]};background:{style["bg"]};">'
            f'{style["icon"]} {text_value(status)}</span>'
            f'<div class="muted small">Updated {escape(stamp_text)}</div>'
            '</div>'
        )

    facts = [
        ("On-time projection", record.get("graduate_on_time")),
        ("Target term", record.get("graduation_term")),
        ("Overall status", record.get("overall_status")),
        ("Enrollment", record.get("enrollment_status")),
    ]
    fact_cards = "".join(
        f'<div class="fact"><div class="label">{escape(label)}</div><div class="value">{text_value(value)}</div></div>'
        for label, value in facts
    )
    meta = [
        ("Student ID", record.get("student_id")),
        ("Cohort", record.get("cohort")),
        ("Adviser", record.get("adviser")),
        ("Email", record.get("email")),
    ]
    meta_items = "".join(
        f'<div><div class="label">{escape(label)}</div><div class="meta-value">{text_value(value)}</div></div>'
        for label, value in meta
    )
    remarks = text_value(record.get("remarks"))
    if remarks == "\u2014":
        remarks = "No remarks on file."
    name = text_value(record.get("full_name"))
    generated = escape(humanise(now_iso()))
    styles = """
    @page { size: A4; margin: 14mm; }
    * { box-sizing: border-box; }
    body { margin: 0; color: #252936; background: #fff; font: 11px/1.5 Arial, sans-serif; }
    .document { max-width: 100%; margin: 0 auto; }
    .masthead { display:flex; align-items:center; justify-content:space-between; gap:20px; padding:0 0 13px; border-bottom:3px solid #E3182D; }
    .brand { color:#252936; font-weight:800; font-size:12px; letter-spacing:.08em; }
    .brand span { display:block; margin-top:2px; color:#727783; font-size:9px; font-weight:600; letter-spacing:.02em; }
    .brand-mark { width:34px; height:5px; margin-top:7px; border-radius:9px; background:linear-gradient(90deg,#E3182D 0 52%,#FFC20E 52%); }
    .doc-tag { color:#727783; font-size:9px; font-weight:700; letter-spacing:.1em; text-transform:uppercase; }
    h1 { margin:18px 0 4px; font-size:25px; line-height:1.2; }
    .student-id-line { margin:0 0 18px; color:#737987; font-size:10px; }
    .section { margin-top:18px; page-break-inside:auto; break-inside:auto; }
    h2 { margin:0 0 9px; font-size:14px; page-break-after:avoid; break-after:avoid; }
    .meta-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; padding:13px; border:1px solid #e4e6ea; border-radius:10px; background:#fafafb; }
    .label { margin-bottom:5px; color:#727783; font-size:8px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }
    .meta-value { overflow-wrap:anywhere; font-size:10px; font-weight:700; }
    .status-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:9px; }
    .status-card { min-height:78px; padding:11px; border:1px solid #e4e6ea; border-top:3px solid #E3182D; border-radius:9px; page-break-inside:avoid; break-inside:avoid; }
    .badge { display:inline-block; padding:4px 8px; border-radius:99px; font-size:10px; font-weight:700; }
    .muted { color:#737987; }
    .small { margin-top:8px; font-size:9px; }
    .fact-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:9px; }
    .fact { padding:11px; border:1px solid #e4e6ea; border-radius:9px; page-break-inside:avoid; break-inside:avoid; }
    .fact .value { overflow-wrap:anywhere; font-size:13px; font-weight:700; }
    .remarks { padding:11px 13px; border-left:3px solid #FFC20E; border-radius:0 8px 8px 0; background:#fffaf0; white-space:pre-wrap; overflow-wrap:anywhere; }
    table { width:100%; border-collapse:collapse; font-size:9px; }
    thead { display:table-header-group; }
    th { background:#f2f3f5; color:#424754; text-align:left; font-weight:700; }
    th,td { padding:7px 8px; border:1px solid #e0e2e6; vertical-align:top; overflow-wrap:anywhere; }
    tr { page-break-inside:avoid; break-inside:avoid; }
    .empty { margin:0; padding:11px; border:1px dashed #ccd0d7; border-radius:8px; color:#737987; }
    footer { margin-top:22px; padding-top:9px; border-top:1px solid #e0e2e6; color:#737987; font-size:8px; }
    @media print { body { -webkit-print-color-adjust:exact; print-color-adjust:exact; } }
    @media screen { body { padding:20px; } }
    """
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>Student Profile - {name}</title><style>{styles}</style></head><body><main class="document">'
        '<header class="masthead"><div><div class="brand">MAP\u00daA UNIVERSITY'
        '<span>ETYSB Succession Board</span><div class="brand-mark"></div></div></div>'
        '<div class="doc-tag">Student profile</div></header>'
        f'<h1>{name}</h1><p class="student-id-line">Student profile record \u00b7 Generated {generated}</p>'
        f'<section class="meta-grid">{meta_items}</section>'
        f'<section class="section"><h2>Lifecycle pillars</h2><div class="status-grid">{"".join(status_cards)}</div></section>'
        f'<section class="section"><h2>Student overview</h2><div class="fact-grid">{fact_cards}</div></section>'
        f'<section class="section"><h2>Remarks</h2><div class="remarks">{remarks}</div></section>'
        f'<section class="section"><h2>Coursework</h2>{course_table}</section>'
        f'<section class="section"><h2>Status history</h2>{history_table}</section>'
        '<footer>Confidential student record \u00b7 ETYSB Succession Board</footer>'
        '</main></body></html>'
    )


def _profile_print_control(document: str) -> None:
    """Render a user-gesture print control that opens the standalone profile document."""
    encoded_document = base64.b64encode(document.encode("utf-8")).decode("ascii")
    component = f"""<!doctype html><html><head><meta charset="utf-8"><style>
        html,body{{margin:0;padding:0;background:transparent;font-family:Arial,sans-serif}}
        .actions{{display:flex;justify-content:flex-end;align-items:center;height:44px}}
        button{{display:inline-flex;align-items:center;gap:8px;padding:9px 14px;border:0;
          border-radius:9px;background:{MAPUA_RED};color:#fff;font-size:12px;font-weight:700;
          cursor:pointer;box-shadow:0 3px 9px rgba(227,24,45,.18)}}
        button:hover{{background:#bf1023}}button:focus-visible{{outline:3px solid #FFC20E;outline-offset:2px}}
        #message{{margin-left:8px;color:#8b2532;font-size:11px}}
    </style></head><body><div class="actions">
      <button id="print-profile" type="button" aria-label="Print this student profile">&#128438; Print profile</button>
      <span id="message" role="status" aria-live="polite"></span>
    </div><script>
      const profileDocument = "{encoded_document}";
      document.getElementById("print-profile").addEventListener("click", () => {{
        const bytes = Uint8Array.from(atob(profileDocument), ch => ch.charCodeAt(0));
        const printableHtml = new TextDecoder("utf-8").decode(bytes);
        const printWindow = window.open("", "_blank");
        if (!printWindow) {{
          document.getElementById("message").textContent = "Allow pop-ups to print this profile.";
          return;
        }}
        printWindow.document.open();
        printWindow.document.write(printableHtml);
        printWindow.document.close();
        let printStarted = false;
        const beginPrint = () => {{
          if (printStarted || printWindow.closed) return;
          printStarted = true;
          printWindow.focus();
          printWindow.print();
        }};
        printWindow.addEventListener("load", beginPrint, {{ once: true }});
        setTimeout(beginPrint, 600);
      }});
    </script></body></html>"""
    streamlit_html(component, height=48, scrolling=False)


def _render_profile_card(runtime: RuntimeConfig, session: Session, record, context: str) -> None:
    try:
        history = fetch_status_history(int(record["student_id"]))
        history_error = None
    except Exception as exc:
        history = []
        history_error = exc
    courses = record.get("courses")
    print_document = _profile_print_document(runtime, record, courses, history)

    toolbar, print_col = st.columns([4.2, 1])
    with toolbar:
        st.caption("Complete student record · Print or save as PDF")
    with print_col:
        _profile_print_control(print_document)

    meta = [
        ("Student ID", record.get("student_id")),
        ("Cohort", record.get("cohort")),
        ("Adviser", record.get("adviser")),
        ("Email", record.get("email")),
    ]
    meta_items = "".join(
        f'<div class="profile-meta-item"><span class="profile-meta-label">{escape(label)}</span>'
        f'<span class="profile-meta-value">{escape(_or_dash(value))}</span></div>'
        for label, value in meta
    )
    st.markdown(
        f'<div class="profile-hero-card"><div class="profile-kicker">Map\u00faa University · ETYSB</div>'
        f'<h2 class="profile-student-name">{escape(_or_dash(record.get("full_name")))}</h2>'
        f'<div class="profile-meta-grid">{meta_items}</div></div>',
        unsafe_allow_html=True,
    )

    st.markdown('<div class="profile-section-title">Lifecycle pillars</div>', unsafe_allow_html=True)
    cols = st.columns(3, gap="small")
    for col, (pillar_key, _) in zip(cols, PILLARS):
        field_name = PILLAR_FIELD[pillar_key]
        value = _or_dash(record.get(field_name))
        band = band_for(field_name, value, runtime.status_bands)
        style = BAND_PILL_STYLE.get(band, BAND_PILL_STYLE["grey"])
        stamp_value = record.get(f"{pillar_key}_updated")
        stamp = humanise(stamp_value)
        stamp_label = "Last updated" if stamp != "never" else "Update date unavailable"
        with col:
            st.markdown(
                f'<div class="profile-status-card">'
                f'<div class="profile-status-label">{escape(runtime.pillar_label(pillar_key))}</div>'
                f'<div class="profile-status-value" style="color:{style["color"]};">'
                f'{style["icon"]} {escape(value)}</div>'
                f'<div class="profile-status-date">{stamp_label}: {escape(stamp if stamp != "never" else "not recorded")}</div>'
                '</div>',
                unsafe_allow_html=True,
            )

    st.markdown('<div class="profile-section-title">Student overview</div>', unsafe_allow_html=True)
    facts = [
        ("On-time projection", record.get("graduate_on_time")),
        ("Target term", record.get("graduation_term")),
        ("Overall status", record.get("overall_status")),
        ("Enrollment", record.get("enrollment_status")),
    ]
    fact_cols = st.columns(4, gap="small")
    for col, (label, value) in zip(fact_cols, facts):
        with col:
            st.markdown(
                f'<div class="profile-fact-card"><div class="profile-fact-label">{escape(label)}</div>'
                f'<div class="profile-fact-value">{escape(_or_dash(value))}</div></div>',
                unsafe_allow_html=True,
            )

    st.markdown('<div class="profile-section-title">Remarks</div>', unsafe_allow_html=True)
    remarks = record.get("remarks")
    remarks_text = _or_dash(remarks)
    if remarks_text == "\u2014":
        remarks_text = "No remarks on file."
    st.markdown(
        f'<div class="profile-remarks">{escape(remarks_text)}</div>',
        unsafe_allow_html=True,
    )

    left, right = st.columns([1.05, 1], gap="large")
    with left:
        st.markdown('<div class="profile-section-title">Coursework</div>', unsafe_allow_html=True)
        if isinstance(courses, pd.DataFrame):
            course_records = courses.to_dict(orient="records")
        elif isinstance(courses, dict):
            course_records = [courses]
        elif isinstance(courses, (list, tuple)):
            course_records = list(courses)
        else:
            course_records = []
        course_records = [course for course in course_records if isinstance(course, dict)]
        course_frame = pd.DataFrame([
            {
                "Course": course.get("course_code", course.get("Course", course.get("course", "\u2014"))),
                "Status": course.get("status", course.get("Status", "\u2014")),
            }
            for course in course_records
        ])
        if not course_frame.empty:
            st.dataframe(course_frame, hide_index=True, width="stretch")
        else:
            st.markdown('<div class="profile-empty-state">No coursework records are available.</div>', unsafe_allow_html=True)

    with right:
        st.markdown('<div class="profile-section-title">Status history</div>', unsafe_allow_html=True)
        if history_error is not None:
            st.error(f"History could not be read: {history_error}")
        elif history:
            history_frame = pd.DataFrame(history)
            history_frame["changed_at"] = history_frame["changed_at"].map(humanise)
            history_frame["pillar"] = history_frame["pillar"].map(runtime.pillar_label)
            st.dataframe(history_frame[["changed_at", "pillar", "old_status", "new_status", "changed_by"]].rename(
                columns={"changed_at": "When", "pillar": "Stage", "old_status": "From", "new_status": "To", "changed_by": "By"}),
                hide_index=True, width="stretch")
        else:
            st.markdown('<div class="profile-empty-state">No status changes are recorded yet.</div>', unsafe_allow_html=True)

    # US-07 / US-13: statuses are read from the student records system and
    # are never typed in on the dashboard. The old "Record a status change"
    # form was removed because what it saved never changed the status shown.
    st.divider()
    st.caption("Statuses come from the student records system. Update them there; they appear here after the next data refresh.")