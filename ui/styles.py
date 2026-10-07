import streamlit as st

# Local imports
from config.settings import BAND_COLORS, BAND_GLYPHS

MAPUA_RED = "#E3182D"
MAPUA_GOLD = "#FFC20E"
DARK_GRAY = "#58595B"
LIGHT_GRAY = "#A5A7A9"
BG_COLOR = "#F0F2F6"
OK_GREEN = "#0C7B49"
OK_GREEN_BG = "#E3F5EC"
WARN_GOLD_TEXT = "#9A6B00"
WARN_GOLD_BG = "#FCF1D8"
DANGER_RED_TEXT = "#B3261E"
DANGER_RED_BG = "#FBE8E7"
NEUTRAL_BG = "#EEF1F4"

BAND_PILL_STYLE: dict[str, dict[str, str]] = {
    "green": {"color": OK_GREEN, "bg": OK_GREEN_BG, "icon": "\u2714"},
    "amber": {"color": WARN_GOLD_TEXT, "bg": WARN_GOLD_BG, "icon": "\u25D0"},
    "red": {"color": DANGER_RED_TEXT, "bg": DANGER_RED_BG, "icon": "\u2716"},
    "grey": {"color": DARK_GRAY, "bg": NEUTRAL_BG, "icon": "\u2014"},
}

OVERALL_STYLE: dict[str, dict[str, str]] = {
    "Needs Attention": {"color": DANGER_RED_TEXT, "bg": DANGER_RED_BG, "icon": "\u2716"},
    "Completed": {"color": OK_GREEN, "bg": OK_GREEN_BG, "icon": "\u2714"},
    "In Progress": {"color": WARN_GOLD_TEXT, "bg": WARN_GOLD_BG, "icon": "\u25D0"},
}

DEFAULT_KPI_THRESHOLDS: dict[str, int] = {"green_min": 80, "yellow_min": 50}

FONT_LINK = (
    "https://fonts.googleapis.com/css2?"
    "family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@500&display=swap"
)

CSS = """
<style>
@import url('__FONT__');

html, body, .stMarkdown, .stDataFrame {
  font-family: 'IBM Plex Sans', system-ui, -apple-system, 'Segoe UI', sans-serif;
}
:root {
  --ink: #12223A; --ink-soft: #55637A; --rule: #DCE3EB;
  --accent: #1F6F6B; --surface: #FFFFFF;
}

.masthead {
  display: flex; align-items: baseline; justify-content: space-between;
  gap: 1.5rem; border-bottom: 2px solid var(--ink);
  padding-bottom: .55rem; margin-bottom: .35rem;
}
.masthead h1 {
  font-size: 1.45rem; font-weight: 600; letter-spacing: -.01em;
  color: var(--ink); margin: 0; line-height: 1.2;
}
.masthead .program { color: var(--ink-soft); font-size: .86rem; }
.freshness {
  font-family: 'IBM Plex Mono', ui-monospace, monospace;
  font-size: .74rem; color: var(--ink-soft);
  margin: 0 0 1.4rem 0; display: block;
}
.freshness b { color: var(--ink); font-weight: 500; }

.kpi {
  border: 1px solid var(--rule); border-top: 3px solid var(--accent);
  background: var(--surface); padding: 1rem 1.1rem .9rem 1.1rem; height: 100%;
}
.kpi .value {
  font-size: 2.5rem; font-weight: 600; color: var(--ink);
  line-height: 1; font-variant-numeric: tabular-nums;
}
.kpi .label { font-size: .84rem; color: var(--ink); margin-top: .45rem; }
.kpi .term { font-size: .74rem; color: var(--ink-soft); margin-top: .15rem; }

.status-badge {
  display: inline-flex; align-items: center; gap: .4rem;
  border: 1px solid var(--badge); color: var(--badge);
  border-radius: 2px; padding: .12rem .5rem; font-size: .82rem; font-weight: 500;
}
.status-glyph { font-size: .7rem; line-height: 1; }

.pillar {
  border: 1px solid var(--rule); background: var(--surface);
  padding: .9rem 1rem; height: 100%;
}
.pillar .name { font-size: .8rem; color: var(--ink-soft); margin-bottom: .5rem; }
.pillar .stamp {
  font-family: 'IBM Plex Mono', ui-monospace, monospace;
  font-size: .7rem; color: var(--ink-soft); margin-top: .6rem;
}
.identity {
  border-left: 3px solid var(--accent); padding-left: .9rem; margin-bottom: 1rem;
}
.identity .name { font-size: 1.2rem; font-weight: 600; color: var(--ink); }
.identity .meta { font-size: .82rem; color: var(--ink-soft); }
.legend { font-size: .76rem; color: var(--ink-soft); margin-top: .6rem; }
</style>
""".replace("__FONT__", FONT_LINK)

def page_header(title: str, runtime: RuntimeConfig, subtitle: str = "") -> None:
    program = runtime.program
    st.markdown(
        f'<div class="masthead"><h1>{title}</h1>'
        f'<span class="program">{program.program_name} &nbsp;&middot;&nbsp; '
        f'{program.current_term}</span></div>',
        unsafe_allow_html=True,
    )
    stamp = humanise(last_successful_sync(program.program_code))
    extra = f" &nbsp;&middot;&nbsp; {subtitle}" if subtitle else ""
    st.markdown(
        f"<span class='freshness'>Last scheduled database check <b>{stamp}</b>{extra}</span>",
        unsafe_allow_html=True,
    )

def sync_banner(program_code: str) -> None:
    try:
        failures = consecutive_failures(program_code)
    except Exception:
        return
    if failures >= SYNC_FAILURE_BANNER_THRESHOLD:
        st.warning(
            f"{failures} data syncs have failed since the last success. Figures "
            "below may be stale. An IT/Admin can read the reason on the "
            "Integration logs screen.",
            icon="\u26a0\ufe0f",
        )

def kpi(value: str, label: str, term: str = "") -> None:
    st.markdown(
        f'<div class="kpi"><div class="value">{value}</div>'
        f'<div class="label">{label}</div><div class="term">{term}</div></div>',
        unsafe_allow_html=True,
    )

def legend(field_name: str, bands: dict) -> None:
    parts = [
        f"<span style='color:{BAND_COLORS[band]}'>{BAND_GLYPHS[band]}</span> {status}"
        for status, band in bands.get(field_name, {}).items()
    ]
    st.markdown("<div class='legend'>" + " &nbsp; ".join(parts) + "</div>",
                unsafe_allow_html=True)

def inject_style() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown(f"""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
        @import url('https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@24,400,0,0');

        .stApp {{
            font-family: 'Inter', sans-serif;
        }}
        ::-webkit-scrollbar {{
            width: 10px;
        }}
        ::-webkit-scrollbar-track {{
            background: transparent;
        }}
        ::-webkit-scrollbar-thumb {{
            background-color: var(--secondary-background-color);
            border-radius: 10px;
        }}
        
        .block-container, [data-testid="block-container"], [data-testid="stAppViewBlockContainer"] {{
            padding-top: 1.5rem !important; 
            padding-bottom: 2.5rem !important; 
            padding-left: 1.5rem !important; 
            padding-right: 1.5rem !important;
            max-width: 100% !important;
        }}
        /* The roster dataframe must fill the roster card, including its unused right side. */
        .st-key-student_roster_dataframe,
        .st-key-student_roster_dataframe > div,
        .st-key-student_roster_dataframe [data-testid="stDataFrame"],
        .st-key-student_roster_dataframe [data-testid="stDataFrameResizable"] {{
            width: 100% !important;
            max-width: 100% !important;
            min-width: 0 !important;
        }}
        .st-key-student_roster_dataframe {{
            box-sizing: border-box !important;
            border: 1px solid color-mix(in srgb, var(--text-color) 14%, var(--secondary-background-color)) !important;
            border-top: 3px solid {MAPUA_RED} !important;
            border-radius: 10px !important;
            padding: 4px !important;
            background: var(--secondary-background-color) !important;
        }}
        .st-key-student_roster_dataframe [data-testid="stDataFrame"],
        .st-key-student_roster_dataframe [data-testid="stDataFrameResizable"] {{
            border-radius: 7px !important;
        }}
        .student-table-hint {{
            display: flex;
            align-items: center;
            gap: 8px;
            margin: 10px 2px 8px;
            color: color-mix(in srgb, var(--text-color) 68%, transparent);
            font-size: 12px;
            line-height: 1.4;
        }}
        .student-table-hint::before {{
            content: "";
            width: 4px;
            height: 14px;
            flex: 0 0 4px;
            border-radius: 4px;
            background: {MAPUA_RED};
        }}
        .profile-hero-card {{
            position: relative;
            overflow: hidden;
            padding: 22px 24px;
            border: 1px solid color-mix(in srgb, var(--text-color) 12%, transparent);
            border-top: 4px solid {MAPUA_RED};
            border-radius: 16px;
            background: linear-gradient(120deg,
                color-mix(in srgb, {MAPUA_RED} 7%, var(--secondary-background-color)),
                var(--secondary-background-color) 62%);
        }}
        .profile-kicker {{
            margin-bottom: 7px;
            color: {MAPUA_RED};
            font-size: 10px;
            font-weight: 800;
            letter-spacing: .13em;
            text-transform: uppercase;
        }}
        .profile-student-name {{
            margin: 0 0 14px;
            color: var(--text-color);
            font-size: clamp(22px, 2.3vw, 30px);
            font-weight: 800;
            line-height: 1.15;
        }}
        .profile-meta-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(175px, 1fr));
            gap: 9px 18px;
        }}
        .profile-meta-item {{ min-width: 0; }}
        .profile-meta-label {{
            display: block;
            margin-bottom: 2px;
            color: color-mix(in srgb, var(--text-color) 58%, transparent);
            font-size: 10px;
            font-weight: 700;
            letter-spacing: .07em;
            text-transform: uppercase;
        }}
        .profile-meta-value {{
            display: block;
            overflow-wrap: anywhere;
            color: var(--text-color);
            font-size: 13px;
            font-weight: 600;
        }}
        .profile-section-title {{
            margin: 20px 0 10px;
            color: var(--text-color);
            font-size: 16px;
            font-weight: 750;
        }}
        .profile-status-card {{
            height: 100%;
            min-height: 124px;
            padding: 16px;
            border: 1px solid color-mix(in srgb, var(--text-color) 12%, transparent);
            border-radius: 14px;
            background: var(--secondary-background-color);
            box-shadow: 0 3px 12px rgba(25, 30, 40, .045);
        }}
        .profile-status-label {{
            margin-bottom: 12px;
            color: color-mix(in srgb, var(--text-color) 66%, transparent);
            font-size: 11px;
            font-weight: 750;
            letter-spacing: .04em;
            text-transform: uppercase;
        }}
        .profile-status-value {{ font-size: 14px; font-weight: 750; }}
        .profile-status-date {{
            margin-top: 12px;
            color: color-mix(in srgb, var(--text-color) 58%, transparent);
            font-size: 11px;
            line-height: 1.45;
        }}
        .profile-fact-card {{
            min-height: 88px;
            padding: 13px 15px;
            border: 1px solid color-mix(in srgb, var(--text-color) 12%, transparent);
            border-radius: 12px;
            background: var(--secondary-background-color);
        }}
        .profile-fact-label {{
            margin-bottom: 7px;
            color: color-mix(in srgb, var(--text-color) 62%, transparent);
            font-size: 10px;
            font-weight: 750;
            letter-spacing: .07em;
            text-transform: uppercase;
        }}
        .profile-fact-value {{
            color: var(--text-color);
            font-size: 18px;
            font-weight: 750;
            overflow-wrap: anywhere;
        }}
        .profile-remarks {{
            padding: 14px 16px;
            border-left: 3px solid {MAPUA_GOLD};
            border-radius: 0 10px 10px 0;
            background: color-mix(in srgb, {MAPUA_GOLD} 9%, var(--secondary-background-color));
            color: var(--text-color);
            font-size: 13px;
            line-height: 1.6;
            white-space: pre-wrap;
            overflow-wrap: anywhere;
        }}
        .profile-empty-state {{
            padding: 18px;
            border: 1px dashed color-mix(in srgb, var(--text-color) 22%, transparent);
            border-radius: 10px;
            color: color-mix(in srgb, var(--text-color) 62%, transparent);
            font-size: 13px;
            text-align: center;
        }}
        h1, h2, h3, h4, h5, h6, p {{ font-family: 'Inter', sans-serif; }}
        .stIconMaterial, .material-symbols-rounded {{ font-family: 'Material Symbols Rounded' !important; }}

        .header-topbar {{
            height: 5px; background-color: {MAPUA_RED}; border-radius: 4px; margin-bottom: 0px;
        }}
        
        /* Allow Streamlit native theme for backgrounds */
        [data-testid="stVerticalBlockBorderWrapper"],
        [data-testid="stVerticalBlockBorderWrapper"] > div,
        [data-testid="stContainer"],
        [data-testid="stForm"],
        div:has(> .section-card-title),
        div:has(> div > .section-card-title),
        div:has(> div > div > .section-card-title) {{
            background-color: var(--secondary-background-color) !important;
            background: var(--secondary-background-color) !important;
            border-radius: 12px !important;
        }}

        div[data-testid="stVerticalBlock"] {{
            background-color: transparent !important;
            background: transparent !important;
        }}

        html body div[data-testid="stVerticalBlockBorderWrapper"]:has(.header-title-block) {{
            background: var(--secondary-background-color) !important;
            border: 1px solid var(--secondary-background-color) !important;
        }}
        
        html body div[data-testid="stVerticalBlockBorderWrapper"]:has(.header-title-block) > div,
        html body div[data-testid="stVerticalBlockBorderWrapper"]:has(.header-title-block) div[data-testid="stVerticalBlock"] {{
            background: transparent !important;
            background-color: transparent !important;
        }}
        
        div:has(> .layout-spacer), div:has(> div > .layout-spacer) {{
            background: transparent !important;
            box-shadow: none !important; border: none !important; border-radius: 0 !important;
        }}

        .header-title-block p {{
            font-size: 11px; letter-spacing: 0.08em; color: {LIGHT_GRAY};
            margin: 0; line-height: 1.2; text-transform: uppercase; font-weight: 600;
        }}
        .header-title-block h1 {{
            font-size: 21px; font-weight: 800; line-height: 1.15; margin: 1px 0 0 0; color: var(--text-color);
        }}
        .st-key-top_header_card [data-testid="stHorizontalBlock"] {{ align-items: center !important; }}
        .st-key-top_header_card [data-testid="stVerticalBlockBorderWrapper"] > div {{
            padding: .6rem 1.25rem !important;
        }}
        .header-context {{ width: 100%; max-width: 100%; padding: .15rem 0; }}
        .header-context-row {{
            display: flex; align-items: baseline; justify-content: flex-end;
            gap: .55rem; text-align: right; white-space: nowrap;
        }}
        .header-context-row + .header-context-row {{ margin-top: .5rem; }}
        .header-context-label {{
            color: #858B95; font-size: .64rem; font-weight: 700;
            letter-spacing: .08em; text-transform: uppercase; white-space: nowrap;
        }}
        .header-context-value {{
            color: var(--text-color); font-size: .82rem; font-weight: 700;
            line-height: 1.35;
        }}
        .header-context-program {{ transform: translateY(-.65rem); }}
        .header-context-program .header-context-value {{ white-space: nowrap; }}
        .header-context-term .header-context-value {{
            justify-self: end; background: #FFF5D6; color: #795B00;
            border-radius: 999px; padding: .22rem .6rem;
        }}
        @media (max-width: 700px) {{
            .st-key-top_header_card [data-testid="stHorizontalBlock"] {{ align-items: flex-start !important; }}
            .header-context-row {{ justify-content: flex-start; flex-wrap: wrap; white-space: normal; }}
            .header-context-program {{ transform: none; }}
            .header-context-program .header-context-value {{ white-space: normal; }}
            .header-context-label, .header-context-value {{ text-align: left; }}
        }}

        .stTabs [data-baseweb="tab-list"] {{
            background-color: var(--secondary-background-color); padding: 4px; border-radius: 8px; gap: 4px;
            border-bottom: none; width: fit-content; margin-bottom: 8px; margin-left: 0.8rem;
        }}
        .stTabs [data-baseweb="tab"] {{
            border-radius: 6px; padding: 6px 18px; background-color: transparent; border: none;
            color: var(--text-color); font-size: 14px; font-weight: 600; transition: all 0.15s ease-in-out;
        }}
        .stTabs [data-baseweb="tab"]:hover {{ color: {MAPUA_RED}; }}
        .stTabs [aria-selected="true"] {{
            background-color: {MAPUA_RED} !important; color: #FFFFFF !important;
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.08);
        }}
        .stTabs [data-baseweb="tab-border"], .stTabs [data-baseweb="tab-highlight"] {{ display: none; }}

        .dashboard-card, .metric-card {{
            background-color: var(--secondary-background-color); border: 1px solid var(--secondary-background-color); 
            border-radius: 12px; box-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.05);
        }}
        .dashboard-card {{ padding: 24px; margin-bottom: 16px; min-height: 160px; }}
        .metric-card {{ padding: 15px 16px; min-height: 112px; }}
        
        .metric-label {{
            font-size: 10px; letter-spacing: 0.06em; text-transform: uppercase;
            font-weight: 700; color: #888C94; margin-bottom: 5px;
        }}
        .metric-value {{
            font-size: 30px; font-weight: 800; color: var(--text-color); line-height: 1.08;
        }}
        .metric-value.accent-red {{ color: {MAPUA_RED}; }}
        .metric-value.accent-gold {{ color: #B08628; }}
        .metric-value.accent-green {{ color: {OK_GREEN}; }}
        .metric-sub {{ font-size: 11px; color: #888C94; margin-top: 4px; }}

        .section-card-title {{ font-size: 16px; font-weight: 700; color: var(--text-color); margin: 0; }}
        .pill-badge {{ background-color: #FDECEC; color: {MAPUA_RED}; font-size: 12px; font-weight: 700; padding: 6px 14px; border-radius: 9999px; display: inline-block; }}
        .status-pill {{ display: inline-block; padding: 3px 12px; border-radius: 6px; font-weight: 600; font-size: 0.82rem; line-height: 1.3; text-align: center; }}
        
        .activity-item {{ display: flex; justify-content: space-between; align-items: center; padding: 10px 0; border-bottom: 1px solid var(--secondary-background-color); }}
        .activity-item:last-child {{ border-bottom: none; }}
        .activity-dot {{ height: 9px; width: 9px; border-radius: 50%; display: inline-block; margin-right: 10px; }}
        .activity-name {{ font-size: 14px; font-weight: 700; color: var(--text-color); }}
        .activity-sub {{ font-size: 12px; color: {LIGHT_GRAY}; margin-left: 19px; }}
        .activity-time {{ font-size: 12px; color: {LIGHT_GRAY}; white-space: nowrap; padding-left: 12px; }}
        
        .dashboard-footer {{ color: {LIGHT_GRAY}; font-size: 12px; margin-top: 32px; padding-top: 16px; border-top: 1px solid var(--secondary-background-color); }}
        .stSelectbox label {{ color: var(--text-color) !important; font-weight: 600 !important; font-size: 13px !important; }}
        thead tr th {{ background-color: var(--secondary-background-color) !important; color: var(--text-color) !important; }}
        .streamlit-expanderHeader svg, [data-testid="stExpanderToggleIcon"] {{ display: none !important; }}
    </style>
    """, unsafe_allow_html=True)
