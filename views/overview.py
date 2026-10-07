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

def compute_kpis(frame: pd.DataFrame, rule: dict[str, Any]) -> dict[str, Any]:
    """
    Every Overview number in one place, so a term and the term before it are
    always measured the same way (US-25). How each one is calculated is
    written up in docs/DATA_DICTIONARY.md (US-17).
      cohort       = students still in the program (withdrawn left out)
      enrolled     = all students still in the cohort, including completers
      completed    = cohort students who defended their capstone
      completion % = completed / cohort (US-18)
      on-time %    = completed students marked graduate_on_time "yes" / completed (US-17)
      remaining    = cohort - completed (US-19)
    """
    cohort = enrolled_frame(frame, rule)
    total = len(cohort)
    completed = students_in_stage(cohort, STAGE_COMPLETED)
    done = len(completed)
    on_time = int((completed["graduate_on_time"].astype(str).str.strip().str.lower() == "yes").sum()) if done else 0
    return {
        "cohort": cohort,
        "total": total,
        "enrolled": total,
        "completed": done,
        "completion_pct": (done / total * 100) if total else 0.0,
        "on_time": on_time,
        "on_time_pct": (on_time / done * 100) if done else 0.0,
        "remaining": total - done,
        "cw_done": int((cohort["coursework_status"] == "Completed").sum()) if total else 0,
        "ce_done": int((cohort["comprehensive_exam_status"] == "Passed").sum()) if total else 0,
    }

def go_to_roster(roster_filter: str) -> None:
    """Drill from a tile or chart bar into the student list (US-18, US-19,
    US-21). The term and cohort filters are left as they are, so the list
    shows the same students the tile was counting."""
    st.session_state["roster_filter"] = roster_filter
    st.session_state["roster_return_page"] = PAGE_OVERVIEW
    st.session_state["sidebar_menu"] = PAGE_STUDENTS

def view_overview(runtime: RuntimeConfig, session: Session, frame: pd.DataFrame, selected_term: str = ALL_TERMS) -> None:
    thresholds = {**DEFAULT_KPI_THRESHOLDS, **(fetch_settings(runtime.program.program_code).get("kpi_thresholds") or {})}
    kpis = compute_kpis(frame, runtime.enrollment_rule)
    enrolled = kpis["cohort"]
    total = kpis["total"]
    program_records = len(frame)
    excluded_records = max(program_records - total, 0)
    cw_done, ce_done, cap_done = kpis["cw_done"], kpis["ce_done"], kpis["completed"]
    # Deliberately read from the full roster, not `enrolled`: a withdrawn or
    # cancelled-coursework student is exactly what the database's own
    # status_thresholds table marks Red (Enrollment: Withdrawn, Coursework:
    # CANCELLED), and enrolled_frame() excludes both from the headcount KPIs
    # by design -- that exclusion must not also hide them from this count.
    # .startswith catches the reason-suffixed labels too (e.g. "Needs
    # Attention (Failed Coursework)"), not just the bare string.
    needs_attention = int(frame["overall_status"].astype(str).str.startswith("Needs Attention").sum()) if len(frame) else 0

    # SPRINT 2: EXECUTIVE SUMMARY & PILLARS (US-17, US-18, US-19)
    completion_pct = kpis["completion_pct"]
    on_time_count = kpis["on_time"]
    on_time_pct = kpis["on_time_pct"]
    remaining_count = kpis["remaining"]

    cw_pct = cw_done / max(total, 1) * 100
    ce_pct = ce_done / max(total, 1) * 100
    cap_pct = cap_done / max(total, 1) * 100

    # What the numbers cover, shown on every tile (US-05, US-17, US-18).
    cohort_choice = st.session_state.get("cohort_filter", ALL_COHORTS)
    if selected_term != ALL_TERMS:
        # Cohort names like "Term 2" already say "Term"; don't print it twice.
        scope = selected_term if str(selected_term).lower().startswith("term") else f"Term {selected_term}"
    elif cohort_choice != ALL_COHORTS:
        scope = f"Cohort {cohort_choice}"
    else:
        scope = "All terms"

    # US-30 Dynamic Labels for Drill-downs
    lbl_cw = runtime.stage_label(STAGE_COURSEWORK)
    lbl_ce = runtime.stage_label(STAGE_COMP_EXAM)
    lbl_cap = runtime.stage_label(STAGE_CAPSTONE)
    lbl_comp = runtime.stage_label(STAGE_COMPLETED)
    lbl_rem = runtime.stage_label(STAGE_REMAINING)

    completion_sub = f"{scope} · {cap_done} of {total} active students completed"
    if excluded_records:
        completion_sub += f" · {excluded_records} excluded by enrollment rules ({program_records} records)"

    # Custom CSS for Gradient Cards and fixing card height uniformity
    st.markdown("""
    <style>
    [data-testid="stTabs"] [role="tabpanel"] {
        padding-top: 0.5rem !important;
        gap: 0.5rem !important;
    }
    .gradient-card {
        background-color: var(--secondary-background-color);
        border: 1px solid rgba(128, 128, 128, 0.2);
        border-radius: 8px;
        border-bottom: 4px solid #E3182D;
        padding: 16px 18px;
        box-shadow: 0 4px 10px rgba(0, 0, 0, 0.04);
        box-sizing: border-box;
        width: 100%;
        height: 156px;
        min-height: 156px;
        overflow: hidden;         /* Prevents multi-line text breaking card bounds */
        margin-bottom: 4px;
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    .gradient-card:hover {
        transform: translateY(-3px);
        box-shadow: 0 8px 15px rgba(0, 0, 0, 0.08);
    }
    .gradient-card .metric-sub {
        /* Two lines max, so the term/cohort label is never cut off (US-05, US-17). */
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
    }
    </style>
    """, unsafe_allow_html=True)

    # SPRINT 2: TERM-OVER-TERM COMPARISON (US-25)
    # Only when one term is selected: that term vs. the term right before it,
    # both measured with compute_kpis() so the deltas compare like with like.
    delta_enr = delta_comp = delta_time = delta_rem = None
    prev_term = None
    unfiltered = st.session_state.get("unfiltered_frame")
    if selected_term != ALL_TERMS and unfiltered is not None and not unfiltered.empty:
        terms = sorted_terms(unfiltered["cohort"].dropna().unique())
        if selected_term in terms:
            idx = terms.index(selected_term)
            if idx > 0:
                prev_term = terms[idx - 1]
                prev = compute_kpis(unfiltered[unfiltered["cohort"].astype(str) == prev_term], runtime.enrollment_rule)
                if prev["total"]:
                    delta_enr = kpis["enrolled"] - prev["enrolled"]
                    delta_comp = completion_pct - prev["completion_pct"]
                    delta_time = on_time_pct - prev["on_time_pct"] if prev["completed"] else None
                    delta_rem = remaining_count - prev["remaining"]

    def gradient_html(label, value, sub, accent, delta=None, invert=False):
        badge = ""
        if delta is not None and round(delta, 1) != 0.0:
            is_pos = delta > 0
            is_good = not is_pos if invert else is_pos
            c_bg = "#E3F5EC" if is_good else "#FDECEC"
            c_tx = OK_GREEN if is_good else MAPUA_RED
            arr = "▲" if is_pos else "▼"
            val_str = f"{abs(delta):.1f}%" if isinstance(value, str) and "%" in value else f"{abs(int(delta))}"
            badge = f'<span style="float:right; background:{c_bg}; color:{c_tx}; font-size:11px; padding:2px 8px; border-radius:12px; font-weight:700;">{arr} {val_str}</span>'
            
        html_str = f'<div class="gradient-card"><div style="display:flex; justify-content:space-between; align-items:flex-start;"><div class="metric-label">{label}</div>{badge}</div><div class="metric-value {accent}">{value}</div><div class="metric-sub" style="color: #A5A7A9; margin-top: 8px;">{sub}</div></div>'
        return html_str

    # SPRINT 2: DYNAMIC KPI TILES (US-29)
    # 1. Register all possible metric calculations. "drill" is where the
    #    tile's "View students" button leads (US-18, US-19).
    vs_prev = f" \u00b7 vs {prev_term}" if prev_term else ""
    enrolled_sub = f"{scope} · includes completed students{vs_prev}"
    if excluded_records:
        enrolled_sub += f" · {excluded_records} excluded from {program_records} program records"
    kpi_registry = {
        "enrolled": {"lbl": "STUDENTS ENROLLED", "sub": enrolled_sub, "val": str(kpis["enrolled"]), "acc": "", "dlt": delta_enr, "inv": False, "drill": "enrolled"},
        "completion": {"lbl": "OVERALL COMPLETION %", "sub": completion_sub, "val": f"{completion_pct:.1f}%", "acc": "accent-green", "dlt": delta_comp, "inv": False, "drill": STAGE_COMPLETED},
        "on_time": {"lbl": "ON-TIME GRADUATION", "sub": f"{scope} \u00b7 {on_time_count} of {cap_done} graduates on time", "val": f"{on_time_pct:.1f}%", "acc": "accent-gold", "dlt": delta_time, "inv": False, "drill": STAGE_COMPLETED},
        "remaining": {"lbl": "REMAINING STUDENTS", "sub": f"{scope} \u00b7 {total} in cohort minus {cap_done} completed", "val": str(remaining_count), "acc": "accent-red", "dlt": delta_rem, "inv": True, "drill": STAGE_REMAINING},
        "coursework": {"lbl": f"{runtime.term('coursework').upper()} COMPLETED", "sub": f"{cw_done} of {total} \u00b7 {kpi_traffic_style(cw_pct, thresholds)['label']}", "val": f"{cw_pct:.0f}%", "acc": kpi_traffic_style(cw_pct, thresholds)["accent"], "dlt": None, "inv": False},
        "comp_exam": {"lbl": f"{runtime.term('comp_exam').upper()} PASSED", "sub": f"{ce_done} of {total} \u00b7 {kpi_traffic_style(ce_pct, thresholds)['label']}", "val": f"{ce_pct:.0f}%", "acc": kpi_traffic_style(ce_pct, thresholds)["accent"], "dlt": None, "inv": False},
        "capstone": {"lbl": f"{runtime.term('capstone').upper()} DEFENDED", "sub": f"{cap_done} of {total} \u00b7 {kpi_traffic_style(cap_pct, thresholds)['label']}", "val": f"{cap_pct:.0f}%", "acc": kpi_traffic_style(cap_pct, thresholds)["accent"], "dlt": None, "inv": False},
        "needs_attention": {"lbl": "NEEDS ATTENTION", "sub": "red status, overdue stage or out of program", "val": str(needs_attention), "acc": "accent-red" if needs_attention else "accent-green", "dlt": None, "inv": False, "drill": "at_risk"}
    }

    # Custom tiles from the KPI layout config: count (or %) of cohort
    # students whose field equals a value. No code change needed (US-29).
    for kpi_def in runtime.kpi_layout:
        k_id = kpi_def.get("id")
        if k_id in kpi_registry or not kpi_def.get("field") or kpi_def.get("field") not in enrolled.columns:
            continue
        hits = int((enrolled[kpi_def["field"]].astype(str) == str(kpi_def.get("value"))).sum()) if total else 0
        as_percent = kpi_def.get("show") == "percent"
        kpi_registry[k_id] = {
            "lbl": str(k_id).replace("_", " ").upper(),
            "sub": f"{scope} \u00b7 {hits} of {total} students",
            "val": f"{(hits / total * 100) if total else 0:.1f}%" if as_percent else str(hits),
            "acc": "", "dlt": None, "inv": False,
        }

    # 2. Render all retained KPI cards on a single row.
    removed_kpi_ids = {"coursework", "comp_exam", "capstone"}
    active_kpis = [
        k for k in runtime.kpi_layout
        if k.get("id") in kpi_registry and k.get("id") not in removed_kpi_ids
    ]
    if active_kpis:
        cols = st.columns(len(active_kpis), gap="small")
        for col, kpi_def in zip(cols, active_kpis):
            k_id = kpi_def.get("id")
            reg = kpi_registry[k_id]
            label = kpi_def.get("label", reg["lbl"])
            sub = kpi_def.get("sub", reg["sub"])
            with col:
                st.markdown(gradient_html(label, reg["val"], sub, reg["acc"], reg["dlt"], reg["inv"]), unsafe_allow_html=True)
                if reg.get("drill"):
                    if st.button("View students \u2192", key=f"kpi_drill_{k_id}", type="tertiary"):
                        go_to_roster(reg["drill"])
                        st.rerun()

    if session.is_admin:
        with st.expander("KPI threshold settings"):
            g = st.slider("Green threshold (%, at or above)", 0, 100, thresholds["green_min"], key="ov_green_slider")
            y = st.slider("Yellow threshold (%, at or above)", 0, 100, thresholds["yellow_min"], key="ov_yellow_slider")
            if g != thresholds["green_min"] or y != thresholds["yellow_min"]:
                if require_edit(session, "save KPI thresholds"):
                    save_setting(runtime.program.program_code, "kpi_thresholds", {"green_min": g, "yellow_min": y}, session.username)
                    st.success("Thresholds updated.")
                    st.rerun()
                else:
                    st.error("Blocked: this account is view-only. The attempt was logged.")
            legend("coursework_status", runtime.status_bands)

    st.write("")
    col_pipeline, col_trend = st.columns([1, 1])

    with col_pipeline:
        with st.container(border=True):
            st.markdown('<h4 class="section-card-title">Lifecycle Breakdown</h4>', unsafe_allow_html=True)

            if total == 0:
                st.info("No enrolled students to summarise yet.")
            else:
                # US-20 / US-21: one horizontal bar per stage. Use Streamlit's
                # native chart to avoid loading the much larger Plotly client.
                stage_rows = [STAGE_COMPLETED, STAGE_CAPSTONE, STAGE_COMP_EXAM, STAGE_COURSEWORK]
                stage_counts = lifecycle_stages(enrolled).value_counts()
                counts = [int(stage_counts.get(stage, 0)) for stage in stage_rows]
                labels = [runtime.stage_label(stage) for stage in stage_rows]
                st.bar_chart(
                    pd.DataFrame({"Students": counts}, index=labels),
                    horizontal=True,
                    sort=False,
                    color=MAPUA_RED,
                    height=260,
                    use_container_width=True,
                )
                st.caption(f"{total} students in the cohort ({scope}). Choose a stage below to open its student list.")

    with col_trend:
        with st.container(border=True):
            st.markdown('<h4 class="section-card-title">Multi-Term Trend</h4>', unsafe_allow_html=True)

            if total == 0:
                st.info("No enrolled students to summarise yet.")
            else:
                unfiltered = st.session_state.get("unfiltered_frame", frame)
                if not unfiltered.empty:
                    # Scope every term through enrolled_frame() before computing its
                    # rate -- without this, cancelled/withdrawn students count in the
                    # denominator here but not in Overall Completion %, so the same
                    # term's point on this chart silently disagreed with the KPI card
                    # above it (e.g. 33/65 = 50.8% here vs the correct 33/57 = 57.9%).
                    # US-24: terms are in calendar order (Term 2 before Term 10) and
                    # a term with no students is left as a gap, not drawn as 0%.
                    x_terms = sorted_terms(unfiltered["cohort"].dropna().unique())[-4:] # Last 4 terms
                    y_rates = []
                    for t in x_terms:
                        term_kpis = compute_kpis(unfiltered[unfiltered["cohort"].astype(str) == t], runtime.enrollment_rule)
                        y_rates.append(term_kpis["completion_pct"] if term_kpis["total"] else None)

                    trend_chart = pd.DataFrame(
                        {"Completion rate (%)": y_rates}, index=x_terms
                    )
                    st.line_chart(
                        trend_chart,
                        color=MAPUA_RED,
                        height=300,
                        use_container_width=True,
                    )
                    empty_terms = [t for t, v in zip(x_terms, y_rates) if v is None]
                    if empty_terms:
                        st.caption("No students yet in: " + ", ".join(empty_terms) + " (shown as a gap).")
                    if len(x_terms) < 4:
                        st.caption(f"Only {len(x_terms)} term(s) of data so far; the chart will show the last four once they exist.")

    st.write("")

    with st.container(border=True):
        st.markdown('<h4 class="section-card-title">Stage Roster</h4>', unsafe_allow_html=True)

        if total == 0:
            st.info("No students enrolled.")
        else:
            stage_choices = {lbl_cw: STAGE_COURSEWORK, lbl_ce: STAGE_COMP_EXAM, lbl_cap: STAGE_CAPSTONE,
                             lbl_comp: STAGE_COMPLETED, lbl_rem: STAGE_REMAINING}
            drill_target = st.selectbox("Select Lifecycle Stage", list(stage_choices), key="drill_target_select", label_visibility="collapsed")
            drill_df = students_in_stage(enrolled, stage_choices[drill_target])

            if drill_df.empty:
                st.info(f"No students currently {drill_target}.")
            else:
                preview_limit = 25
                drill_preview = drill_df.sort_values(["last_name", "first_name"], na_position="last").head(preview_limit)
                drill_display = drill_preview[["student_id", "full_name", "adviser"]].fillna("Unassigned")
                drill_display.columns = ["ID", "Name", "Adviser"]
                st.dataframe(drill_display, hide_index=True, use_container_width=True)
                if len(drill_df) > preview_limit:
                    st.caption(f"Showing {preview_limit} of {len(drill_df)} students. Open the Students page for the full list.")
                if st.button("Open full stage roster", key="overview_full_stage_roster"):
                    go_to_roster(stage_choices[drill_target])
                    st.rerun()

    with st.container(border=True):
            st.markdown('<h4 class="section-card-title">Students Needing Attention (At Risk)</h4>', unsafe_allow_html=True)
            risk = frame[frame["overall_status"].astype(str).str.startswith("Needs Attention")] if len(frame) else frame
            if risk.empty:
                st.success("No students currently flagged — nothing needs advisor attention right now.")
            else:
                risk_preview = risk.head(50)
                def outlook_email_link(value: Any) -> str:
                    if pd.isna(value) or not str(value).strip():
                        return ""
                    address = str(value).strip()
                    mailto_address = quote(address, safe="@.")
                    return '<a href="mailto:{}" title="{}">{}</a>'.format(
                        mailto_address, escape(address, quote=True), escape(address)
                    )

                # US-28: each row says why the student was flagged. The email
                # link moved under the name to make room for the Reason column.
                names_html = [
                    f"<b>{escape(str(name))}</b><br>{outlook_email_link(email)}"
                    for name, email in zip(risk_preview["full_name"], risk_preview["email"] if "email" in risk_preview.columns else [""] * len(risk_preview))
                ]
                table = pd.DataFrame({
                    "Student ID": risk_preview["student_id"].astype(str),
                    "Name": names_html,
                    "Reason": risk_preview["overall_status"].apply(lambda v: escape(attention_reason(v))),
                    "Term": risk_preview["cohort"],
                    # Inject the actual colored pill badges instead of plain text
                    runtime.pillar_label("coursework"): [status_pill_html("coursework_status", v, runtime.status_bands) for v in risk_preview["coursework_status"].fillna(UNKNOWN)],
                    runtime.pillar_label("comprehensive_exam"): [status_pill_html("comprehensive_exam_status", v, runtime.status_bands) for v in risk_preview["comprehensive_exam_status"].fillna(UNKNOWN)],
                    runtime.pillar_label("capstone"): [status_pill_html("capstone_status", v, runtime.status_bands) for v in risk_preview["capstone_status"].fillna(UNKNOWN)],
                    "Adviser": risk_preview["adviser"].fillna("Unassigned"),
                }).reset_index(drop=True)

                st.caption(f"{len(risk)} student(s) flagged ({scope}); showing up to 50 here.")
                risk_export = roster_export_frame(runtime, risk, include_reason=True)
                if st.download_button(
                    "Export at-risk list (CSV) ⤓",
                    data=risk_export.to_csv(index=False).encode("utf-8-sig"),
                    file_name=f"at_risk_students_{runtime.program.program_code}.csv",
                    mime="text/csv",
                    key="export_at_risk",
                ):
                    log_access(session.username, session.role, "export at-risk list", "allowed",
                               f"{len(risk_export)} rows; scope={scope}")
                
                # Keep the at-risk roster compact, readable, and independently scrollable.
                st.markdown("""
                <style>
                .at-risk-table-scroll {
                    height: min(560px, 58vh);
                    min-height: 260px;
                    overflow-y: auto;
                    overflow-x: hidden;
                    margin-top: 12px;
                    border: 1px solid rgba(128,128,128,0.18);
                    border-radius: 10px;
                    scrollbar-width: thin;
                    scrollbar-color: rgba(128,128,128,0.6) transparent;
                }
                .custom-html-table { width: 100%; table-layout: fixed; border-collapse: separate; border-spacing: 0; font-size: 13px; }
                .custom-html-table th {
                    /* Semi-transparent grey works on both the light and dark theme
                       (a solid near-black header looked wrong in light mode). */
                    background-color: rgba(128,128,128,0.12) !important;
                    color: #7A7E86;
                    font-weight: 700;
                    text-transform: uppercase;
                    letter-spacing: 0.04em;
                    font-size: 11px;
                    text-align: center;
                    padding: 12px 9px;
                    border-bottom: 1px solid rgba(128,128,128,0.24);
                    white-space: nowrap;
                }
                .custom-html-table td {
                    padding: 10px 9px;
                    border-bottom: 1px solid rgba(128,128,128,0.12);
                    color: var(--text-color);
                    vertical-align: middle;
                    overflow-wrap: anywhere;
                }
                .custom-html-table th:nth-child(1), .custom-html-table td:nth-child(1) { width: 9%; }
                .custom-html-table th:nth-child(2), .custom-html-table td:nth-child(2) { width: 18%; }
                .custom-html-table th:nth-child(3), .custom-html-table td:nth-child(3) { width: 20%; }
                .custom-html-table th:nth-child(4), .custom-html-table td:nth-child(4) { width: 8%; }
                .custom-html-table th:nth-child(5), .custom-html-table td:nth-child(5) { width: 11%; }
                .custom-html-table th:nth-child(6), .custom-html-table td:nth-child(6) { width: 14%; }
                .custom-html-table th:nth-child(7), .custom-html-table td:nth-child(7) { width: 10%; }
                .custom-html-table th:nth-child(8), .custom-html-table td:nth-child(8) { width: 10%; }
                .custom-html-table td:nth-child(1), .custom-html-table td:nth-child(4),
                .custom-html-table td:nth-child(5), .custom-html-table td:nth-child(6),
                .custom-html-table td:nth-child(7) { white-space: nowrap; }
                .custom-html-table th:nth-child(5), .custom-html-table th:nth-child(6),
                .custom-html-table th:nth-child(7), .custom-html-table td:nth-child(5),
                .custom-html-table td:nth-child(6), .custom-html-table td:nth-child(7) { text-align: center; }
                .custom-html-table th:nth-child(4), .custom-html-table td:nth-child(4) { text-align: center; }
                .custom-html-table .status-pill {
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    box-sizing: border-box;
                    min-width: 96px;
                    max-width: 100%;
                    padding: 4px 7px;
                    font-size: 0.76rem;
                    line-height: 1.2;
                    white-space: nowrap;
                    text-align: center;
                }
                .custom-html-table td:nth-child(2) a { display: block; color: #60a5fa; text-decoration: none; font-weight: 500; font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; overflow-wrap: normal; word-break: normal; }
                .custom-html-table td:nth-child(2) a:hover { color: #93c5fd; text-decoration: underline; text-underline-offset: 2px; }
                .custom-html-table td:nth-child(3) { color: #B3261E; font-weight: 600; }
                .custom-html-table tr:hover td { background-color: rgba(128,128,128,0.06); }
                .custom-html-table tr:last-child td { border-bottom: none; }
                /* US-32: on tablets the table wraps instead of scrolling sideways. */
                @media (max-width: 1100px) {
                    .custom-html-table { table-layout: auto; font-size: 12px; }
                    .custom-html-table th, .custom-html-table td { white-space: normal !important; padding: 8px 6px; }
                    .custom-html-table .status-pill { min-width: 0; white-space: normal; }
                    .custom-html-table th:nth-child(4), .custom-html-table td:nth-child(4),
                    .custom-html-table th:nth-child(8), .custom-html-table td:nth-child(8) { display: none; }
                }
                </style>
                """, unsafe_allow_html=True)

                # The fixed-height wrapper prevents long lists from stretching the dashboard.
                html_table = table.to_html(escape=False, index=False, classes="custom-html-table", border=0)
                st.markdown(f'<div class="at-risk-table-scroll">{html_table}</div>', unsafe_allow_html=True)