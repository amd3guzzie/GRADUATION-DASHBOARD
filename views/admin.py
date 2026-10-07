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

def render_admin_tab(runtime: RuntimeConfig, session: Session, frame: pd.DataFrame) -> None:
    if not session.is_admin:
        log_access(session.username, session.role, "open tab: Admin Config", "denied", "Role may not administer the dashboard")
        st.error("\U0001F6AB Admin Config is restricted to IT/Admin accounts. This attempt has been logged.")
        return

    with st.container(border=True):
        st.markdown('<h4 class="section-card-title">Admin Configuration</h4>', unsafe_allow_html=True)
        sub_map, sub_users, sub_logs = st.tabs(["Field mapping", "Users & permissions", "Integration logs"])
        with sub_map:
            view_field_mapping(runtime, session, frame)
        with sub_users:
            view_users(runtime, session, frame)
        with sub_logs:
            view_logs(runtime, session, frame)

def view_field_mapping(runtime: RuntimeConfig, session: Session, frame) -> None:
    page_header("Field mapping", runtime)
    if runtime.mapping_errors:
        st.error("The dashboard is not live for this program. Fix the following, then reopen a data view:\n\n" + "\n".join(f"- {problem}" for problem in runtime.mapping_errors))
    else:
        st.success("All required fields are mapped. The dashboard is live for this program.")

    tab_fields, tab_bands, tab_program = st.tabs(["Dashboard fields", "Status colours", "Program"])
    with tab_fields:
        st.caption("Each row is a field the dashboard renders. Pick where its value comes from.")
        kinds = ["direct", "lookup", "milestone"]
        for field_name in DASHBOARD_FIELDS:
            spec = dict(runtime.field_map.get(field_name) or DEFAULT_FIELD_MAP.get(field_name) or {})
            marker = "  \u2014 required" if field_name in REQUIRED_FIELDS else ""
            state = "  (using default, not saved)" if field_name not in runtime.field_map else ""

            with st.expander(f"{field_name}{marker}{state}"):
                kind = st.selectbox("Source kind", kinds, index=kinds.index(spec.get("kind", "direct")), key=f"kind_{field_name}")
                new_spec: dict = {"kind": kind}
                if kind == "direct":
                    new_spec["column"] = st.text_input("Source column", spec.get("column", ""), key=f"col_{field_name}")
                elif kind == "lookup":
                    new_spec["embed"] = st.text_input("Related table", spec.get("embed", "advisers"), key=f"emb_{field_name}")
                    new_spec["column"] = st.text_input("Column on that table", spec.get("column", ""), key=f"col_{field_name}")
                else:
                    new_spec["milestone_type"] = st.text_input("Milestone type", spec.get("milestone_type", ""), key=f"mt_{field_name}")

                if field_name in STATUS_VOCABULARY or spec.get("value_map"):
                    st.caption("Allowed dashboard values: " + ", ".join(STATUS_VOCABULARY.get(field_name, [])))
                    raw_map = st.text_area("Value map (JSON: source value -> dashboard value)", json.dumps(spec.get("value_map", {}), indent=2), height=180, key=f"vm_{field_name}")
                    try:
                        new_spec["value_map"] = json.loads(raw_map or "{}")
                    except json.JSONDecodeError as exc:
                        st.error(f"That value map is not valid JSON: {exc}")
                        new_spec["value_map"] = spec.get("value_map", {})

                problems = validate_field_map({field_name: new_spec})
                for problem in problems:
                    st.warning(problem)

                if st.button("Save mapping", key=f"save_{field_name}"):
                    if not require_edit(session, f"save mapping: {field_name}"):
                        st.error("Blocked: this account is view-only. The attempt was logged.")
                    elif problems:
                        st.error("Fix the problems above before saving.")
                    else:
                        try:
                            save_field_map(runtime.program.program_code, field_name, new_spec, session.username)
                            log_access(session.username, session.role, f"save mapping: {field_name}", "allowed", "")
                            st.success("Saved. It applies on the next data read.")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Could not save the mapping: {exc}")

    with tab_bands:
        edited = st.text_area("Status bands (JSON)", json.dumps(runtime.status_bands, indent=2), height=320, key="bands_json")
        if st.button("Save colour bands"):
            if not require_edit(session, "save status bands"):
                st.error("Blocked: this account is view-only. The attempt was logged.")
            else:
                try:
                    parsed = json.loads(edited)
                    bad = [band for table in parsed.values() for band in table.values() if band not in BAND_COLORS]
                    if bad:
                        st.error(f"Unknown band name(s): {', '.join(sorted(set(bad)))}")
                    else:
                        save_setting(runtime.program.program_code, "status_bands", parsed, session.username)
                        st.success("Saved.")
                        st.rerun()
                except json.JSONDecodeError as exc:
                    st.error(f"That is not valid JSON: {exc}")
        st.write("")
        for field_name, table in runtime.status_bands.items():
            st.markdown(f"**{field_name}**")
            st.markdown(" &nbsp; ".join(badge(field_name, status, runtime.status_bands) for status in table), unsafe_allow_html=True)

    with tab_program:
        # US-02: create a program record before its data is loaded.
        st.markdown("##### Programs")
        st.caption("Programs come from the database's programs table. You can also add one here so it can be "
                   "set up (mapping, labels, thresholds) before its student data is loaded.")
        with st.form("new_program_form"):
            p1, p2, p3 = st.columns(3)
            new_code = p1.text_input("Program code", placeholder="e.g. MSIT")
            new_name = p2.text_input("Program name", placeholder="e.g. Master of Science in IT")
            new_term = p3.text_input("Current term", placeholder="e.g. Term 1")
            create_program = st.form_submit_button("Create program")
        if create_program:
            code = new_code.strip().upper()
            if not require_edit(session, f"create program: {code}"):
                st.error("Blocked: this account is view-only. The attempt was logged.")
            elif not re.fullmatch(r"[A-Z0-9_-]{2,20}", code or ""):
                st.error("Use 2-20 letters, numbers, dashes or underscores for the program code.")
            elif not new_name.strip():
                st.error("A program name is required.")
            else:
                save_program_record(code, new_name.strip(), new_term.strip(), session.username)
                log_access(session.username, session.role, f"create program: {code}", "allowed", new_name.strip())
                st.success(f"Created {code}. Pick it from the program selector above to configure it.")
                st.rerun()

        st.divider()
        # SPRINT 2: PHASE 4 - MULTI-PROGRAM CONFIGURATION (US-27)
        st.markdown("##### Alert & Risk Settings")
        prog_settings = fetch_settings(runtime.program.program_code)
        current_max = int(prog_settings.get("max_days_in_progress") or DEFAULT_MAX_DAYS_IN_PROGRESS)
        st.caption(f"Default for the MBA program: {DEFAULT_MAX_DAYS_IN_PROGRESS} days on any stage "
                   "(about one 14-week term plus a term of allowance). Leave a stage at 0 to use the program-wide value.")
        new_max = st.number_input("Expected Duration Threshold (Days 'In-Progress' before flagging as Overdue)", min_value=1, value=current_max)
        per_stage = dict(prog_settings.get("max_days_per_stage") or {})
        stage_cols = st.columns(3)
        new_per_stage = {}
        for col, (pillar_key, _) in zip(stage_cols, PILLARS):
            new_per_stage[pillar_key] = col.number_input(
                f"{runtime.pillar_label(pillar_key)} (days)", min_value=0,
                value=int(per_stage.get(pillar_key) or 0), key=f"max_days_{pillar_key}",
            )
        if st.button("Save duration threshold"):
            if not require_edit(session, "save duration threshold"):
                st.error("Blocked: this account is view-only.")
            else:
                save_setting(runtime.program.program_code, "max_days_in_progress", int(new_max), session.username)
                save_setting(runtime.program.program_code, "max_days_per_stage",
                             {k: int(v) for k, v in new_per_stage.items() if v}, session.username)
                log_access(session.username, session.role, "save duration threshold", "allowed", f"default={new_max}, per_stage={new_per_stage}")
                st.success(f"Saved! Students in progress on a stage for more than {new_max} days (or that stage's own limit) will be flagged.")
                st.rerun()

        st.divider()
        st.markdown("##### Enrollment Rules")
        edited_rule = st.text_area("Enrollment rule (JSON)", json.dumps(runtime.enrollment_rule, indent=2), height=180, key="rule_json")
        if st.button("Save enrollment rule"):
            if not require_edit(session, "save enrollment rule"):
                st.error("Blocked: this account is view-only. The attempt was logged.")
            else:
                try:
                    save_setting(runtime.program.program_code, "enrollment_rule", json.loads(edited_rule), session.username)
                    st.success("Saved.")
                    st.rerun()
                except json.JSONDecodeError as exc:
                    st.error(f"That is not valid JSON: {exc}")

        st.divider()
        st.markdown("##### Program Terminology")
        st.caption("These labels are used everywhere a stage is named: KPI tiles, charts, the roster, "
                   "the student profile and the at-risk list. The last two set the dashboard header.")
        edited_terms = st.text_area("Terminology labels (JSON)", json.dumps({**DEFAULT_TERMINOLOGY, **runtime.terminology}, indent=2, ensure_ascii=False), height=220, key="terms_json")
        if st.button("Save terminology"):
            if not require_edit(session, "save terminology"):
                st.error("Blocked: this account is view-only.")
            else:
                try:
                    save_setting(runtime.program.program_code, "terminology", json.loads(edited_terms), session.username)
                    st.success("Saved! Labels will update across the dashboard.")
                    st.rerun()
                except json.JSONDecodeError as exc:
                    st.error(f"That is not valid JSON: {exc}")

        st.divider()
        st.markdown("##### KPI Tile Layout")
        st.caption(
            "Built-in tile ids: " + ", ".join(BUILT_IN_KPI_IDS) + ". Any tile can take a \"label\" and \"sub\". "
            "A new tile needs no code: give it a new id plus \"field\" and \"value\", e.g. "
            '{"id": "in_capstone", "label": "IN CAPSTONE", "field": "capstone_status", "value": "In-Progress", "show": "count"} '
            '("show" can be "count" or "percent").'
        )
        edited_kpis = st.text_area("KPI Layout (JSON list)", json.dumps(runtime.kpi_layout, indent=2), height=200, key="kpi_json")
        if st.button("Save KPI layout"):
            if not require_edit(session, "save kpi layout"):
                st.error("Blocked: this account is view-only.")
            else:
                try:
                    parsed_kpis = json.loads(edited_kpis)
                    problems = validate_kpi_layout(parsed_kpis)
                    if problems:
                        st.error("Fix these before saving:\n\n" + "\n".join(f"- {p}" for p in problems))
                    else:
                        save_setting(runtime.program.program_code, "kpi_layout", parsed_kpis, session.username)
                        st.success("Saved! Dashboard tiles updated.")
                        st.rerun()
                except Exception as exc:
                    st.error(f"Invalid JSON or format: {exc}")

def view_users(runtime: RuntimeConfig, session: Session, frame) -> None:
    page_header("Users and permissions", runtime)
    if not session.is_admin:
        log_access(session.username, session.role, "open page: Users and permissions", "denied", "Role may not administer accounts")
        st.error("This screen is limited to IT/Admin accounts.")
        return

    try:
        users = list_users()
    except Exception as exc:
        st.error(f"The account list could not be read: {exc}")
        return

    if users:
        table = pd.DataFrame(users)
        table["role"] = table["role"].map(role_label)
        table = table.rename(columns={
            "username": "Username", "full_name": "Name", "role": "Role",
            "permission_level": "Permission", "adviser_name": "Adviser name in database", "is_active": "Active",
        })
        st.dataframe(table, hide_index=True, width="stretch")
    else:
        st.info("No accounts exist yet. Create the first one below.")

    st.divider()
    st.subheader("Create or update an account")
    st.caption("Saving an existing username updates it. Leave the password blank to keep it.")

    with st.form("user_form"):
        col_1, col_2 = st.columns(2)
        with col_1:
            username = st.text_input("Username", placeholder="j.reyes")
            role = st.selectbox("Role", ROLES, format_func=role_label)
            permission = st.selectbox("Permission level", [PERMISSION_VIEW, PERMISSION_EDIT], help="View-only accounts cannot trigger any write action.")
        with col_2:
            full_name = st.text_input("Full name", placeholder="Jonna Reyes")
            password = st.text_input("Password", type="password")
            adviser_name = st.text_input("Adviser name in database (advisors only)", placeholder="Prof. Jonna Reyes",
                                         help="Exactly as it appears in the capstone adviser column. Used for the My advisees filter.")
            is_active = st.checkbox("Account is active", value=True)
        submitted = st.form_submit_button("Save account")

    if not submitted:
        return
    if not username.strip():
        st.error("A username is required.")
        return
    if password and len(password) < 10:
        st.error("Use at least 10 characters for the password.")
        return

    try:
        ok, message = upsert_user(session, username, full_name, role, permission, password or None, is_active, adviser_name)
    except Exception as exc:
        st.error(f"The account was not saved: {exc}")
        return

    if ok:
        st.success(message)
        st.rerun()
    else:
        st.error(message)

def view_logs(runtime: RuntimeConfig, session: Session, frame) -> None:
    page_header("Integration logs", runtime)
    if not session.is_admin:
        log_access(session.username, session.role, "open page: Integration logs", "denied", "Role may not read integration logs")
        st.error("This screen is limited to IT/Admin accounts.")
        return

    program_code = runtime.program.program_code
    sync_banner(program_code)
    status_column, action_column = st.columns([3, 1])
    with status_column:
        ok, message = connection_check()
        (st.success if ok else st.error)(f"Database: {message}")
    with action_column:
        if st.button("Test connection", width="stretch"):
            refresh_data()
            st.rerun()

    tab_sync, tab_access = st.tabs(["Data syncs", "Access attempts"])
    with tab_sync:
        try:
            entries = fetch_sync_logs(program_code, limit=200)
        except Exception as exc:
            st.error(f"Sync logs could not be read: {exc}")
            entries = []
        if entries:
            table = pd.DataFrame(entries)
            table["finished_at"] = table["finished_at"].map(humanise)
            st.dataframe(
                table.rename(columns={"finished_at": "Finished", "status": "Result", "rows_loaded": "Rows", "error_message": "Reason", "source": "Source"}),
                hide_index=True, width="stretch",
            )
            failures = [e for e in entries if e.get("status") != "success"]
            st.caption(f"{len(failures)} failed run(s) in the last {len(entries)} entries.")
        else:
            st.info("No sync runs have been recorded for this program yet.")

    with tab_access:
        try:
            logs = fetch_access_logs(limit=300)
        except Exception as exc:
            st.error(f"Access logs could not be read: {exc}")
            return
        if not logs:
            st.info("No access events recorded yet.")
            return

        table = pd.DataFrame(logs)
        table["logged_at"] = table["logged_at"].map(humanise)
        if st.toggle("Show blocked attempts only", value=False):
            table = table[table["outcome"] == "denied"]
        st.dataframe(
            table.rename(columns={"logged_at": "When", "username": "User", "role": "Role", "action": "Action", "outcome": "Outcome", "detail": "Detail"}),
            hide_index=True, width="stretch",
        )