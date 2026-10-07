import base64
import datetime as dt
from html import escape
import hashlib
import sys
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit.components.v1 import html as streamlit_html
from streamlit_cookies_controller import CookieController

# Local imports
from config.settings import *
from db.connection import connection_check
from db.queries import fetch_programs, last_successful_sync, log_access, load_demo_accounts, authenticate, log_sync, record_database_status_changes
from core.lifecycle import load_dashboard_frame, overdue_limits
from ui.styles import inject_style
from ui.components import sync_banner

# Import your Views
from views.overview import view_overview
from views.students import view_students, profile_dialog
from views.admin import render_admin_tab

# Define the base directory for local assets
APP_DIR = Path(__file__).resolve().parent

# Initialize cookies
cookie_manager = CookieController()

def boot_screen() -> bool:
    ok, message = connection_check()
    if ok:
        return True
    st.title("Graduate Program Lifecycle Dashboard")
    st.error(f"The dashboard cannot reach its database.\n\n{message}")
    if st.button("Try again"):
        refresh_data()
        st.rerun()
    return False

def build_runtime(program_row: dict) -> RuntimeConfig:
    program = Program(
        program_code=program_row["program_code"],
        program_name=program_row.get("program_name") or program_row["program_code"],
        current_term=program_row.get("current_term") or NO_CURRENT_TERM,
        is_active=bool(program_row.get("is_active", True)),
        scope_column=program_row.get("scope_column") or "program_code",
    )
    try:
        stored_map = fetch_field_map(program.program_code)
    except Exception as exc:
        stored_map = {}
        st.error(f"Field mappings could not be read: {exc}")
    field_map = {**DEFAULT_FIELD_MAP, **stored_map}
    try:
        settings = fetch_settings(program.program_code)
    except Exception:
        settings = {}
    return RuntimeConfig(
        program=program, field_map=field_map,
        status_bands=settings.get("status_bands") or DEFAULT_STATUS_BANDS,
        enrollment_rule=settings.get("enrollment_rule") or DEFAULT_ENROLLMENT_RULE,
        mapping_errors=validate_field_map(field_map),
        terminology=settings.get("terminology") or DEFAULT_TERMINOLOGY,
        kpi_layout=settings.get("kpi_layout") or DEFAULT_KPI_LAYOUT,
    )

@st.cache_data(show_spinner=False)
def _login_slideshow_markup() -> str:
    asset_dir = Path(__file__).resolve().parent / "assets"
    photos = [
        (asset_dir / "mapua-campus-main.jpg", "Mapúa University main campus"),
        (asset_dir / "mapua-campus-blue.jpg", "Mapúa University campus building"),
    ]
    slides = []
    for index, (path, description) in enumerate(photos):
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        slides.append(
            f'<img src="data:image/jpeg;base64,{encoded}" '
            f'alt="{escape(description, quote=True)}" '
            f'style="animation-delay: -{index * 18 + 2}s">'
        )
    return f"""<!doctype html>
    <html><head><meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
      * {{ box-sizing: border-box; }}
      html, body {{ width: 100%; height: 100%; margin: 0; padding: 0; background: transparent; }}
      .login-slideshow {{
        position: relative; width: 100%; height: 100%; min-height: 100vh; overflow: hidden;
        background: transparent;
      }}
      .login-slideshow img {{
        position: absolute; inset: 0; width: 100%; height: 100%;
        object-fit: cover; object-position: center; opacity: 0;
        animation: mapua-crossfade 36s infinite ease-in-out;
      }}
      @keyframes mapua-crossfade {{
        0% {{ opacity: .58; }} 10% {{ opacity: .82; }}
        42% {{ opacity: .82; }} 58% {{ opacity: 0; }} 90% {{ opacity: 0; }} 100% {{ opacity: .58; }}
      }}
      @media (prefers-reduced-motion: reduce) {{
        .login-slideshow img {{ animation: none; opacity: 0; }}
        .login-slideshow img:first-child {{ opacity: 1; }}
      }}
    </style></head><body>
      <div class="login-slideshow" aria-label="Mapúa University photo slideshow">
        {''.join(slides)}
      </div>
    </body></html>"""


def login_page() -> None:
    st.markdown("""
    <style>
      html:has(.st-key-login_content), body:has(.st-key-login_content) {
        height: 100vh !important; min-height: 100vh !important; max-height: 100vh !important;
        overflow: hidden !important;
        background: transparent !important;
      }
      #root:has(.st-key-login_content) {
        zoom: .8 !important; width: 125% !important;
        height: 125vh !important; min-height: 125vh !important; max-height: 125vh !important;
        overflow: hidden !important; background: transparent !important;
      }
      #root .stApp:has(.st-key-login_content),
      #root [data-testid="stAppViewContainer"]:has(.st-key-login_content),
      #root [data-testid="stMain"]:has(.st-key-login_content),
      [data-testid="stAppViewBlockContainer"]:has(.st-key-login_content) {
        background: transparent !important;
        color: var(--text-color) !important;
      }
      #root .stApp:has(.st-key-login_content) [data-testid="stHeader"],
      #root .stApp:has(.st-key-login_content) [data-testid="stToolbar"] {
        position: relative !important; z-index: 5 !important;
        height: 32px !important; min-height: 32px !important; max-height: 32px !important;
        background: transparent !important;
      }
      #root .stApp:has(.st-key-login_content) [data-testid="stToolbar"] { align-items: center !important; }
      #root .stApp:has(.st-key-login_content),
      #root [data-testid="stAppViewContainer"]:has(.st-key-login_content),
      #root [data-testid="stMain"]:has(.st-key-login_content) {
        height: 125vh !important; min-height: 125vh !important; max-height: 125vh !important;
        overflow: hidden !important;
      }
      [data-testid="stAppViewBlockContainer"]:has(.st-key-login_content) {
        box-sizing: border-box !important; width: 100% !important; max-width: 100% !important;
        height: calc(125vh - 40px) !important; min-height: calc(125vh - 40px) !important;
        max-height: calc(125vh - 40px) !important;
        padding: 0 !important; margin: 0 !important; overflow: hidden !important;
        background: transparent !important;
      }
      .st-key-login_content {
        position: fixed !important; inset: 0 !important; z-index: 2 !important;
        display: flex !important; align-items: center !important; justify-content: center !important;
        box-sizing: border-box !important; width: 100% !important; max-width: 100% !important;
        height: auto !important; min-height: 0 !important; max-height: none !important;
        margin: 0 !important; padding: 40px 30px !important; overflow: auto !important;
        background: transparent !important;
      }
      .st-key-login_content [data-testid="stVerticalBlockBorderWrapper"]:not(.st-key-login_card),
      .st-key-login_content [data-testid="stVerticalBlockBorderWrapper"]:not(.st-key-login_card) > div,
      .st-key-login_content [data-testid="stContainer"]:not(.st-key-login_card) {
        background: transparent !important;
        border: 0 !important; box-shadow: none !important;
      }
      .st-key-login_content > div {
        width: 100% !important; min-height: inherit !important;
        display: flex !important; align-items: center !important; justify-content: center !important;
        margin: 0 !important; padding: 0 !important;
        background: transparent !important;
      }
      .st-key-login_content [data-testid="stVerticalBlock"] {
        width: 100% !important; gap: .7rem !important;
      }
      .st-key-login_card {
        width: min(100%, 520px) !important; max-width: 520px !important;
        margin: auto !important; padding: clamp(20px, 3vw, 32px) !important;
        border: 1px solid color-mix(in srgb, var(--text-color) 22%, transparent) !important;
        border-radius: 24px !important; height: fit-content !important;
        min-height: 0 !important; max-height: calc(125vh - 80px) !important;
        flex: 0 0 auto !important; align-self: center !important;
        background: color-mix(in srgb, var(--background-color) 96%, transparent) !important;
        box-shadow: 0 18px 64px rgba(0, 0, 0, .24) !important;
        overflow: hidden !important;
        position: relative !important;
        top: auto !important;
        transform: none !important;
        -webkit-backdrop-filter: blur(18px) saturate(125%);
        backdrop-filter: blur(18px) saturate(125%);
      }
      .st-key-login_card > div,
      .st-key-login_card > div > [data-testid="stVerticalBlock"] {
        height: fit-content !important; min-height: 0 !important;
        border-radius: inherit !important; background: transparent !important;
      }
      .st-key-login_card [data-testid="stVerticalBlock"] { gap: .5rem !important; }
      .login-brand-pill {
        display: flex; flex-direction: column; align-items: center; justify-content: center;
        position: relative; width: max-content; max-width: 100%; min-height: 78px;
        padding: 15px 32px 20px; margin: 0 auto 10px;
        border: 1px solid color-mix(in srgb, #C8102E 48%, var(--text-color) 52%);
        border-radius: 999px;
        background: color-mix(in srgb, var(--background-color) 88%, #C8102E 12%);
        box-shadow: 0 5px 18px rgba(0, 0, 0, .12);
        color: var(--text-color); font: 650 15px/1.2 Inter, sans-serif;
        letter-spacing: .07em; text-align: center;
        transform: translateY(-8px) scale(1.04); transform-origin: center;
      }
      .login-brand-pill::after {
        content: ""; position: absolute; left: 50%; bottom: 7px;
        width: 46px; height: 3px; transform: translateX(-50%);
        border-radius: 999px; background: linear-gradient(90deg, #C8102E 0 50%, #F2B21A 50% 100%);
      }
      .login-brand-pill span:first-child {
        color: color-mix(in srgb, var(--text-color) 82%, #C8102E 18%);
        text-transform: uppercase;
      }
      .login-brand-pill span + span {
        font-size: 14px; letter-spacing: .04em;
        color: color-mix(in srgb, var(--text-color) 88%, #F2B21A 12%);
      }
      .stApp h1.login-heading,
      [data-testid="stAppViewBlockContainer"]:has(.st-key-login_content) .login-heading {
        margin: 0 0 7px; color: var(--text-color) !important;
        font: 750 clamp(25px, 2.3vw, 36px)/1.12 Inter, sans-serif;
        letter-spacing: -.035em; width: 100%; text-align: center;
      }
      #root .stApp:has(.st-key-login_content) .login-welcome-heading {
        transform: translateX(8px);
      }
      #root .stApp:has(.st-key-login_content) .login-demo-heading {
        transform: translateX(8px);
      }
      .login-description {
        margin: 0 0 18px; color: var(--text-color); opacity: .76;
        font: 400 14px/1.55 Inter, sans-serif;
      }
      #root .stApp:has(.st-key-login_content) [data-testid="stWidgetLabel"],
      #root .stApp:has(.st-key-login_content) [data-testid="stWidgetLabel"] p,
      #root .stApp:has(.st-key-login_content) [data-testid="stWidgetLabel"] label,
      #root .stApp:has(.st-key-login_content) label { color: var(--text-color) !important; }
      #root .stApp:has(.st-key-login_content) [data-testid="stTextInput"] div[data-baseweb="input"],
      #root .stApp:has(.st-key-login_content) [data-testid="stTextInput"] div[data-baseweb="input"] > div,
      #root .stApp:has(.st-key-login_content) [data-testid="stTextInput"] [data-baseweb],
      #root .stApp:has(.st-key-login_content) [data-testid="stTextInput"] input {
        background: var(--secondary-background-color) !important;
        color: var(--text-color) !important;
        border: 1px solid color-mix(in srgb, var(--text-color) 14%, transparent) !important;
        border-radius: 12px !important;
      }
      #root .stApp:has(.st-key-login_content) [data-testid="stSelectbox"] [data-baseweb="select"],
      #root .stApp:has(.st-key-login_content) [data-testid="stSelectbox"] [data-baseweb="select"] > div {
        background: var(--secondary-background-color) !important;
        color: var(--text-color) !important;
        border-color: color-mix(in srgb, var(--text-color) 14%, transparent) !important;
        border-radius: 12px !important;
      }
      #root .stApp:has(.st-key-login_content) [data-baseweb="select"] *,
      #root .stApp:has(.st-key-login_content) [data-testid="stTextInput"] input { color: var(--text-color) !important; }
      #root .stApp:has(.st-key-login_content) [data-testid="stTextInput"] input::placeholder {
        color: var(--text-color) !important; opacity: .62 !important;
      }
      #root .stApp:has(.st-key-login_content) [data-testid="stExpander"] {
        background: var(--secondary-background-color) !important;
        border: 1px solid color-mix(in srgb, var(--text-color) 18%, transparent) !important;
        border-radius: 12px !important; color: var(--text-color) !important;
      }
      #root .stApp:has(.st-key-login_content) [data-testid="stExpander"] * {
        color: var(--text-color) !important;
      }
      .st-key-login_view_toggle > div {
        display: flex !important; justify-content: flex-end !important;
      }
      .st-key-login_view_toggle button {
        width: auto !important; min-height: 30px !important; height: 30px !important;
        padding: 0 11px !important; border-radius: 999px !important;
        font-size: 11px !important; font-weight: 700 !important;
        position: relative !important; top: -18px !important; left: 38px !important; z-index: 4 !important;
      }
      .login-demo-table {
        width: 100%; overflow: hidden; border-radius: 10px;
        border: 1px solid color-mix(in srgb, var(--text-color) 18%, transparent);
        background: var(--secondary-background-color); color: var(--text-color);
      }
      .login-demo-table-head, .login-demo-table-row {
        display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(0, 1.1fr) minmax(0, .8fr);
        align-items: center;
      }
      .login-demo-table-head {
        min-height: 34px; background: linear-gradient(105deg, #A90E28, #C8102E 62%, #D9293F);
        color: #fff; font-size: 11px; font-weight: 750; letter-spacing: .06em;
        text-transform: uppercase;
      }
      #root .stApp:has(.st-key-login_content) .login-demo-table-head,
      #root .stApp:has(.st-key-login_content) .login-demo-table-head * { color: #fff !important; }
      .login-demo-table-body {
        max-height: 240px; overflow-y: auto; overscroll-behavior: contain;
        scrollbar-width: thin; scrollbar-color: #C8102E transparent;
      }
      .login-demo-table-row {
        min-height: 32px; border-top: 1px solid color-mix(in srgb, var(--text-color) 11%, transparent);
        transition: background-color 140ms ease;
      }
      .login-demo-table-row:nth-child(even) { background: color-mix(in srgb, var(--background-color) 46%, transparent); }
      .login-demo-table-row:hover { background: color-mix(in srgb, var(--secondary-background-color) 78%, #F2B21A 22%); }
      .login-demo-table-head span, .login-demo-table-row span {
        min-width: 0; padding: 8px 10px; overflow: hidden;
        text-overflow: ellipsis; white-space: nowrap;
      }
      .login-demo-note {
        margin: 12px 0 0; padding-top: 10px;
        border-top: 1px solid color-mix(in srgb, var(--text-color) 28%, transparent);
        color: var(--text-color); opacity: .72;
        font-size: 12px; line-height: 1.45;
      }
      .st-key-login_slideshow iframe {
        display: block; width: 100% !important; height: 125vh !important;
        border: 0 !important; border-radius: 0 !important;
      }
      .st-key-login_slideshow {
        position: fixed !important; inset: 0 !important;
        width: 125vw !important; height: 125vh !important; min-height: 125vh !important;
        margin: 0 !important; padding: 0 !important; z-index: 0 !important;
        overflow: hidden !important; pointer-events: none !important;
        background: transparent !important;
      }
      .st-key-login_slideshow::after {
        content: ""; position: absolute; inset: 0; z-index: 1; pointer-events: none;
        background: color-mix(in srgb, var(--background-color) 32%, transparent);
      }
      .st-key-login_slideshow > div {
        position: absolute !important; inset: 0 !important; width: 100% !important;
        height: 125vh !important; margin: 0 !important; padding: 0 !important;
        overflow: hidden !important; background: transparent !important;
      }
      .st-key-login_slideshow iframe {
        position: absolute !important; inset: 0 !important;
        width: 100% !important; height: 100% !important; border-radius: 0 !important;
      }
      @media (max-width: 700px) {
        html:has(.st-key-login_content), body:has(.st-key-login_content) { overflow: hidden !important; }
        #root .stApp:has(.st-key-login_content),
        #root [data-testid="stAppViewContainer"]:has(.st-key-login_content),
        #root [data-testid="stMain"]:has(.st-key-login_content),
        [data-testid="stAppViewBlockContainer"]:has(.st-key-login_content) {
          height: 125vh !important; min-height: 125vh !important; max-height: 125vh !important;
          overflow: hidden !important;
        }
        .st-key-login_content {
          padding: 30px 20px !important;
        }
        .st-key-login_card { padding: 30px !important; border-radius: 20px !important; }
      }
      @media (max-height: 720px) and (min-width: 701px) {
        .st-key-login_content { align-items: flex-start !important; padding-top: 18px !important; padding-bottom: 18px !important; }
      }
    </style>
    """, unsafe_allow_html=True)

    with st.container(key="login_slideshow"):
        streamlit_html(_login_slideshow_markup(), height=900, scrolling=False)

    with st.container(border=False, key="login_content"):
        with st.container(border=False, key="login_card"):
            showcase_key = "login_show_demo_accounts"
            showing_demo_accounts = bool(st.session_state.get(showcase_key, False))
            _, toggle_col = st.columns([5, 1])
            with toggle_col:
                toggle_label = "↩️" if showing_demo_accounts else "💾"
                toggle_help = "Return to sign in" if showing_demo_accounts else "View demo accounts"
                if st.button(
                    toggle_label,
                    key="login_view_toggle",
                    help=toggle_help,
                    type="secondary",
                ):
                    st.session_state[showcase_key] = not showing_demo_accounts
                    st.rerun()

            st.markdown(
                '<div class="login-brand-pill"><span>Mapúa University</span>'
                '<span>ETYSB Succession Board</span></div>',
                unsafe_allow_html=True,
            )

            if showing_demo_accounts:
                st.markdown(
                    '<h1 class="login-heading login-demo-heading">Demo accounts</h1>'
                    '<p class="login-description">Explore the dashboard roles and access levels.</p>',
                    unsafe_allow_html=True,
                )
                try:
                    demo_accounts = load_demo_accounts()
                except Exception:
                    st.error("Demo accounts could not be loaded. Please try again later.")
                    return

                if demo_accounts:
                    demo_rows = "".join(
                        '<div class="login-demo-table-row" role="row">'
                        f'<span role="cell">{escape(str(account.get("full_name") or ""))}</span>'
                        f'<span role="cell">{escape(role_label(str(account.get("role") or "")))}</span>'
                        f'<span role="cell">{escape(str(account.get("permission_level") or PERMISSION_VIEW))}</span>'
                        '</div>'
                        for account in demo_accounts
                    )
                    st.markdown(
                        '<div class="login-demo-table" role="table" aria-label="Demo accounts">'
                        '<div class="login-demo-table-head" role="row">'
                        '<span role="columnheader">Account</span>'
                        '<span role="columnheader">Role</span>'
                        '<span role="columnheader">Access</span>'
                        '</div>'
                        f'<div class="login-demo-table-body">{demo_rows}</div>'
                        '</div>'
                        '<p class="login-demo-note">Demo Password: Password123</p>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.info("No active demo accounts are available.")
                return

            st.markdown('<h1 class="login-heading login-welcome-heading">Welcome back</h1>', unsafe_allow_html=True)
            role_choice = st.selectbox("Choose your role", options=ROLES, format_func=role_label, key="login_role")
            username_input = st.text_input("Account name", key="login_username", placeholder="Enter your full name")
            password_input = st.text_input("Password", key="login_password", type="password")

            if st.button("Log In", type="primary", use_container_width=True, key="login_btn"):
                try:
                    session = authenticate(username_input, password_input, role_choice)
                except Exception as exc:
                    st.error(f"Sign-in could not be completed: {exc}")
                    return
                if session:
                    st.session_state["session"] = session
                    # Set a cookie that remembers them for 7 days
                    cookie_manager.set('dashboard_user', session.username, max_age=604800)
                    st.rerun()
                else:
                    st.error("No account found for that role, username, and password combination.")
                    st.caption("The attempt has been logged.")

def render_top_header(session: Session, runtime: RuntimeConfig) -> None:
    st.markdown('<div class="header-topbar"></div>', unsafe_allow_html=True)
    
    # Drop a colored "sheet of glass" directly on the exact div that has the white background
    st.markdown("""
    <style>
        /* 1. Set the white background div to relative so it can hold the absolute overlay */
        .st-key-top_header_card [data-testid="stVerticalBlockBorderWrapper"] > div {
            position: relative !important;
        }
        
        /* 2. Create the gradient overlay exactly the same size as the container */
        .st-key-top_header_card [data-testid="stVerticalBlockBorderWrapper"] > div::after {
            content: "";
            position: absolute;
            top: 0; left: 0; right: 0; bottom: 0;
            background: linear-gradient(135deg, rgba(227,24,45,0.15) 0%, transparent 40%, rgba(255,194,14,0.18) 100%);
            border-radius: 12px;
            pointer-events: none;
            z-index: 1;
        }
        
        /* 3. Elevate the actual content (logos, text) so it sits on top of the gradient */
        .st-key-top_header_card [data-testid="stVerticalBlockBorderWrapper"] > div > * {
            position: relative;
            z-index: 2;
        }
    </style>
    """, unsafe_allow_html=True)

    with st.container(border=True, key="top_header_card"):
        # Adjusted columns to remove the logo space
        title_col, meta_col = st.columns([1, 1])
        
        with title_col:
            # US-02 / US-30: header text comes from the program's terminology.
            st.markdown(f"""
            <div class="header-title-block">
                <p>{escape(runtime.term("institution_line"))}</p>
                <h1>{escape(runtime.term("dashboard_title"))}</h1>
            </div>
            """, unsafe_allow_html=True)

        with meta_col:
            # This timestamp tracks the scheduled database check. Student
            # records shown below are read live on each app rerun.
            stamp = humanise(last_successful_sync(runtime.program.program_code))
            st.markdown(
                f"""
                <div class="header-context">
                    <div class="header-context-row header-context-program">
                        <span class="header-context-label">Program:</span>
                        <span class="header-context-value">{escape(runtime.program.program_name)}</span>
                    </div>
                    <div class="header-context-row header-context-term">
                        <span class="header-context-label">Current term</span>
                        <span class="header-context-value">{escape(runtime.program.current_term)}</span>
                    </div>
                    <div class="header-context-row">
                        <span class="header-context-label">Last scheduled check</span>
                        <span class="header-context-value">{escape(stamp)}</span>
                    </div>
                </div>
                """, unsafe_allow_html=True,
            )

def render_controls_bar(
    session: Session,
    programs: list[dict],
    runtime: RuntimeConfig,
    frame: pd.DataFrame,
    active_page: str,
) -> str:
    program_col, cohort_col, term_col = st.columns([1.8, 1, 1])
    with program_col:
        codes = [p["program_code"] for p in programs]
        labels = {p["program_code"]: p.get("program_name", p["program_code"]) for p in programs}
        if session.is_admin:
            st.selectbox(
                "Program", codes, format_func=lambda c: labels.get(c, c),
                key="program_code",
            )
        else:
            st.selectbox(
                "Program",
                [runtime.program.program_code],
                index=0,
                format_func=lambda c: labels.get(c, c),
                disabled=True,
                help="Only IT/Admin can switch the active program.",
            )
    # US-22: the term list is in calendar order and starts on the program's
    # current term. The choice is remembered per program.
    terms = [ALL_TERMS]
    if not frame.empty and "cohort" in frame.columns:
        terms += sorted_terms(frame["cohort"].dropna().unique())
    else:
        # Keep the selected term available while Admin Config skips the roster read.
        for term in (runtime.program.current_term, st.session_state.get("term_filter")):
            if term and term != ALL_TERMS and term not in terms:
                terms.append(term)
    if st.session_state.get("term_filter_program") != runtime.program.program_code:
        st.session_state["term_filter_program"] = runtime.program.program_code
        current = runtime.program.current_term
        st.session_state["term_filter"] = current if current in terms else ALL_TERMS
    if st.session_state.get("term_filter") not in terms:
        st.session_state["term_filter"] = ALL_TERMS
    with cohort_col:
        if active_page in (PAGE_OVERVIEW, PAGE_STUDENTS) and not frame.empty:
            cohorts = [ALL_COHORTS] + sorted_terms(frame["cohort"].dropna().unique())
            selected_term = st.session_state.get("term_filter", ALL_TERMS)
            if selected_term != ALL_TERMS:
                cohorts = [ALL_COHORTS] + [c for c in cohorts[1:] if c == selected_term]
            if st.session_state.get("cohort_filter", ALL_COHORTS) not in cohorts:
                st.session_state["cohort_filter"] = ALL_COHORTS
            st.selectbox("Cohort", cohorts, key="cohort_filter")
    with term_col:
        selected_term = st.selectbox("Term", terms, key="term_filter",
                                     format_func=lambda t: f"{t} (current)" if t == runtime.program.current_term else t)
    return selected_term

def render_footer() -> None:
    current_date = dt.datetime.now().strftime("%B %d, %Y")
    st.markdown(f"""
    <div class="dashboard-footer">
        Graduate Program Lifecycle Dashboard &middot; Rendered {current_date}
    </div>
    """, unsafe_allow_html=True)

PAGE_ADMIN = "Admin Config"

ROLE_TABS: dict[str, list[str]] = {
    ROLE_ADMIN: [PAGE_OVERVIEW, PAGE_STUDENTS, PAGE_ADMIN],
    ROLE_EXEC: [PAGE_OVERVIEW, PAGE_STUDENTS],
    ROLE_MANAGER: [PAGE_OVERVIEW, PAGE_STUDENTS],
    ROLE_STAFF: [PAGE_STUDENTS],
}

NAV_LABELS: dict[str, str] = {
    PAGE_OVERVIEW: "📊  Dashboard",
    PAGE_STUDENTS: "🧑‍🎓  Students",
    PAGE_ADMIN: "⚙️  Admin Config",
}

def run_dashboard() -> None:
    inject_style()

    session = current_session()
    # Keep the database preflight on the sign-in page. Authenticated reruns
    # already perform real reads below, so a separate ping only adds latency.
    if session is None and not boot_screen():
        return

    # Attempt auto-login via cookie if Streamlit's memory was wiped by an F5 refresh
    if session is None:
        saved_user = cookie_manager.get('dashboard_user')
        if saved_user:
            session = auto_login(saved_user)
            if session:
                st.session_state["session"] = session

    if session is None:
        login_page()
        return

    try:
        programs = fetch_programs()
    except Exception as exc:
        st.error(f"The program list could not be read: {exc}")
        return

    if not programs:
        st.error("No active program is configured.")
        return

    codes = [p["program_code"] for p in programs]
    chosen_code = st.session_state.get("program_code")
    if chosen_code not in codes:
        chosen_code = codes[0]
    st.session_state["program_code"] = chosen_code
    runtime = build_runtime(next(p for p in programs if p["program_code"] == chosen_code))

    # Student data is read directly on every app rerun. The scheduled refresh
    # still records a sync result; ordinary page reads do not create sync-log
    # entries.

    render_top_header(session, runtime)
    sync_banner(runtime.program.program_code)

    tabs_available = ROLE_TABS.get(session.role, [])
    if not tabs_available:
        st.error("No screens are available to your role. Contact an IT/Admin.")
        return

    # US-01: each role starts on a page it is allowed to open.
    if st.session_state.get("sidebar_menu") not in tabs_available:
        st.session_state["sidebar_menu"] = tabs_available[0]
    render_sidebar(session, tabs_available)

    active_page = st.session_state.get("sidebar_menu", tabs_available[0])
    needs_data = active_page in (PAGE_OVERVIEW, PAGE_STUDENTS, PAGE_PROFILE)
    frame = pd.DataFrame()

    if needs_data:
        if not runtime.is_live:
            st.error(
                "The dashboard is not live for this program: its field mapping is "
                "incomplete. An IT/Admin can fix it under Admin Config → Field mapping.\n\n"
                + "\n".join(f"- {problem}" for problem in runtime.mapping_errors)
            )
        else:
            try:
                labels = {pillar_key: runtime.pillar_label(pillar_key) for pillar_key, _ in PILLARS}
                with st.spinner("Loading student records…"):
                    frame = load_dashboard_frame(
                        runtime.program.program_code,
                        runtime.program.scope_column,
                        runtime.field_map,
                        runtime.status_bands,
                        overdue_limits(fetch_settings(runtime.program.program_code)),
                        runtime.enrollment_rule,
                        labels,
                    )
                if not frame.empty:
                    # Only reconcile status history when the actual status
                    # snapshot changes, avoiding a history query on every rerun.
                    snapshot_columns = [
                        column for column in (
                            "student_id", "student_number", *PILLAR_FIELD.values()
                        )
                        if column in frame.columns
                    ]
                    snapshot = frame[snapshot_columns]
                    if "student_id" in snapshot.columns:
                        snapshot = snapshot.sort_values("student_id", kind="stable")
                    snapshot_hash = hashlib.sha256(
                        pd.util.hash_pandas_object(snapshot, index=False).values.tobytes()
                    ).hexdigest()
                    history_key = f"_status_history_snapshot:{runtime.program.program_code}"
                    if st.session_state.get(history_key) != snapshot_hash:
                        record_database_status_changes(runtime.program.program_code, frame)
                        st.session_state[history_key] = snapshot_hash

                    # Keep the unfiltered source frame for term comparisons.
                    st.session_state["unfiltered_frame"] = frame
            except Exception as exc:
                log_sync(runtime.program.program_code, "failed", 0, str(exc), source="database read")
                st.error(f"Student data could not be read from the database.\n\n{exc}")

    # Shared selectors sit below the program header. Term scopes the dashboard,
    # while cohort is available on both the overview and student roster pages.
    selected_term = render_controls_bar(session, programs, runtime, frame, active_page)
    if selected_term != ALL_TERMS and "cohort" in frame.columns:
        frame = frame[frame["cohort"].astype(str) == selected_term]
    selected_cohort = st.session_state.get("cohort_filter", ALL_COHORTS)
    if active_page == PAGE_OVERVIEW and selected_cohort != ALL_COHORTS and "cohort" in frame.columns:
        frame = frame[frame["cohort"] == selected_cohort]

    # Dashboard Routing (Listens to the Sidebar instead of using Tabs)
    if active_page not in tabs_available:
        log_access(session.username, session.role, f"open page: {active_page}", "denied", "Page is not available to this role")
        st.warning("You do not have permission to view this page. The attempt has been logged.")
    elif active_page == PAGE_OVERVIEW:
        view_overview(runtime, session, frame, selected_term)
    elif active_page == PAGE_STUDENTS:
        view_students(runtime, session, frame)
    elif active_page == PAGE_ADMIN:
        render_admin_tab(runtime, session, frame)

    render_footer()

def render_sidebar(session: Session, tabs_available: list[str]) -> None:
    """US-01: the menu only lists the pages this role may open. It is drawn
    even when there is no data, so Log out is always reachable."""
    with st.sidebar:
        # 1. Mapua ETYSB Logo
        with st.container(key="sidebar_logo"):
            # Transparent-background copy of Mapua_Logo.png so the seal sits
            # directly on the sidebar instead of on a white square.
            logo_path = APP_DIR / "Mapua_Logo.png"
            try:
                st.image(str(logo_path), use_container_width=True)
            except Exception as exc:
                st.caption(f"Mapúa logo could not be loaded: {exc}")

        # 1.5 Thin line separator
        st.markdown("<hr style='margin: 12px 0 16px 0; border: none; border-top: 1px solid rgba(128, 128, 128, 0.2);'>", unsafe_allow_html=True)
        st.caption(f"Signed in as **{session.full_name}** · {role_label(session.role)}")

        # 2. Navigation buttons
        with st.container(key="sidebar_navigation"):
            for page_name in tabs_available:
                if st.button(
                    NAV_LABELS.get(page_name, page_name),
                    key=f"sidebar_nav_{page_name.lower().replace(' ', '_')}",
                    use_container_width=True,
                    type="primary" if st.session_state["sidebar_menu"] == page_name else "secondary",
                ):
                    st.session_state["sidebar_menu"] = page_name
                    st.session_state.pop("roster_filter", None)
                    st.rerun()

        # Push the account actions toward the bottom of the rail.
        st.markdown("<br><br>", unsafe_allow_html=True)

        # Re-run now and clear cached program/configuration lookups.
        if st.button("🔄 Refresh Data", use_container_width=True):
            refresh_data()
            log_access(session.username, session.role, "refresh data", "allowed", "")
            st.rerun()

        if st.button("🚪 Log out", type="primary", use_container_width=True):
            sign_out()
            st.session_state.clear()
            st.rerun()

# =============================================================================
# SECTION 9  COMMAND-LINE TOOLS (MySQL/Aiven Mode)
# =============================================================================

def cli_get_db_connection(args: argparse.Namespace):
    # The loader writes to the database, so it uses its own account from a
    # [mysql_loader] section, keeping the dashboard's [mysql] account
    # read-only (US-11). Falls back to [mysql] if no loader section exists.
    db_cfg: dict[str, Any] = {}
    for section in ("mysql_loader", "mysql"):
        try:
            db_cfg = dict(st.secrets[section])
            break
        except Exception:
            continue
    host = args.host or db_cfg.get("host")
    user = args.user or db_cfg.get("user")
    password = args.password or db_cfg.get("password")
    database = args.database or db_cfg.get("database")
    port = args.port or db_cfg.get("port") or 3306

    if not all([host, user, password, database]):
        print("Missing credentials.")
        sys.exit(2)

    return pymysql.connect(
        host=host, port=int(port), user=user, password=password, 
        database=database, cursorclass=pymysql.cursors.DictCursor, autocommit=True
    )

def cli_load_csv(args: argparse.Namespace) -> int:
    try:
        conn = cli_get_db_connection(args)
    except Exception as e:
        print(f"Database connection failed: {e}")
        return 2

    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT course_code FROM courses;")
            dynamic_courses = [row["course_code"].lower() for row in cursor.fetchall()]

            frame = pd.read_csv(args.csv, dtype={"student_number": "int64"})
            frame = frame.where(pd.notnull(frame), None)
            records = frame.to_dict(orient="records")

            cursor.execute("SELECT program_id FROM programs WHERE program_code = %s;", (args.program,))
            prog_row = cursor.fetchone()
            if not prog_row:
                print(f"Program code '{args.program}' not found.")
                return 1
            program_id = prog_row["program_id"]

            student_count = 0
            for r in records:
                student_num = int(r["student_number"])
                email = r.get("student_email") or r.get("email")
                
                cursor.execute("""
                    INSERT INTO students (student_number, email, first_name, last_name, program_id, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
                    ON DUPLICATE KEY UPDATE 
                        email=VALUES(email), first_name=VALUES(first_name), 
                        last_name=VALUES(last_name), updated_at=NOW();
                """, (student_num, email, r.get("first_name"), r.get("last_name"), program_id))
                
                cursor.execute("SELECT student_id FROM students WHERE student_number = %s;", (student_num,))
                student_id = cursor.fetchone()["student_id"]

                for course in dynamic_courses:
                    status = r.get(course) or r.get(course.upper()) or "not yet taken"
                    cursor.execute("""
                        INSERT INTO course_enrollment (student_id, course_code, status)
                        VALUES (%s, %s, %s)
                        ON DUPLICATE KEY UPDATE status=VALUES(status);
                    """, (student_id, course.upper(), status))
                    
                student_count += 1

            cursor.execute("INSERT INTO data_sync_log (sync_timestamp, status, records_processed) VALUES (NOW(), 'Success', %s);", (student_count,))
            print(f"Loaded {student_count} students mapped to {len(dynamic_courses)} dynamic courses.")
            return 0
            
    except Exception as exc:
        with conn.cursor() as cursor:
            cursor.execute("INSERT INTO data_sync_log (sync_timestamp, status, error_message, records_processed) VALUES (NOW(), 'Failed', %s, 0);", (str(exc),))
        print(f"Load failed: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()

def cli_schema(args: argparse.Namespace) -> int:
    print("Schema is managed via DBeaver using your external .sql file.")
    return 0

def cli_refresh(args: argparse.Namespace) -> int:
    """
    US-33: the scheduled nightly refresh. Windows Task Scheduler runs
    `python Dashboard.py refresh` every night; it reads every program from
    the database the same way the dashboard does and logs a success or a
    failure with its reason to the sync log (US-16), which raises the
    dashboard's warning banner after repeated failures.
    """
    programs = [p["program_code"] for p in fetch_programs()]
    if args.program:
        programs = [code for code in programs if code == args.program] or [args.program]
    if not programs:
        log_sync(args.program or "ALL", "failed", 0, "No programs could be read from the database.", source="scheduled refresh")
        print("Refresh failed: no programs could be read from the database.", file=sys.stderr)
        return 1
    failed = 0
    for code in programs:
        try:
            rows_read = fetch_students(code)
            log_sync(code, "success", rows_loaded=len(rows_read), source="scheduled refresh")
            print(f"{code}: read {len(rows_read)} students.")
        except Exception as exc:
            failed += 1
            log_sync(code, "failed", 0, str(exc), source="scheduled refresh")
            print(f"{code}: refresh failed: {exc}", file=sys.stderr)
    return 1 if failed else 0

def cli() -> int:
    parser = argparse.ArgumentParser(prog="dashboard.py")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("schema").set_defaults(func=cli_schema)
    refresher = sub.add_parser("refresh", help="Read the database now and log the result (run nightly).")
    refresher.add_argument("--program", default=None, help="Only refresh this program code.")
    refresher.set_defaults(func=cli_refresh)
    loader = sub.add_parser("load-csv")
    loader.add_argument("csv")
    # US-02: no program is assumed; say which one the CSV belongs to.
    loader.add_argument("--program", required=True)
    loader.add_argument("--host", default=None)
    loader.add_argument("--port", default=None)
    loader.add_argument("--user", default=None)
    loader.add_argument("--password", default=None)
    loader.add_argument("--database", default=None)
    loader.set_defaults(func=cli_load_csv)
    args = parser.parse_args()
    return args.func(args)

# =============================================================================
# SECTION 10  DATABASE SCHEMA
# =============================================================================
SCHEMA_SQL = ""

# =============================================================================
# SECTION 11  ENTRY POINT
# =============================================================================

cookie_manager = CookieController()

def auto_login(username: str) -> Session | None:
    """Rebuilds the session from a saved cookie without needing a password."""
    users = load_users()
    match = next((u for u in users if u["full_name"].strip().lower() == username.strip().lower() and u.get("is_active", 1)), None)
    if match:
        return Session(
            username=match["full_name"],
            full_name=match["full_name"],
            role=match.get("role") or ROLE_STAFF,
            permission_level=match.get("permission_level") or PERMISSION_VIEW,
            adviser_name=match.get("adviser_name") or "",
        )
    return None

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("schema", "load-csv", "refresh", "-h", "--help"):
        raise SystemExit(cli())
    run_dashboard()