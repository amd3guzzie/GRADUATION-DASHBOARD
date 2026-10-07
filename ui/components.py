import datetime as dt
from html import escape
from typing import Any

import pandas as pd
import streamlit as st

# Local imports
from config.settings import RuntimeConfig, BAND_COLORS, BAND_GLYPHS, UNKNOWN
from ui.styles import BAND_PILL_STYLE, OVERALL_STYLE, OK_GREEN, MAPUA_GOLD, MAPUA_RED, DARK_GRAY, NEUTRAL_BG, OK_GREEN_BG, DANGER_RED_BG, DANGER_RED_TEXT
from utils.formatting import humanise
from db.queries import last_successful_sync, consecutive_failures, fetch_sync_logs, fetch_recent_status_changes, fetch_access_logs

def status_pill_html(field_name: str, status: str, bands: dict) -> str:
    band = band_for(field_name, status or UNKNOWN, bands)
    style = BAND_PILL_STYLE[band]
    return (f'<span class="status-pill" style="background:{style["bg"]};color:{style["color"]};">'
            f'{style["icon"]} {status or UNKNOWN}</span>')

def overall_status_html(label: str) -> str:
    if str(label).startswith("Needs Attention"):
        style = OVERALL_STYLE["Needs Attention"]
    else:
        style = OVERALL_STYLE.get(label, {"color": DARK_GRAY, "bg": NEUTRAL_BG, "icon": "\u2022"})
    return (f'<span class="status-pill" style="background:{style["bg"]};color:{style["color"]};">'
            f'{style["icon"]} {label}</span>')

def source_tag_html(connected: bool) -> str:
    if connected:
        return (f'<span class="source-tag" style="background:{OK_GREEN_BG};color:{OK_GREEN};">'
                f'\u25CF Connected \u2014 Live Database</span>')
    return (f'<span class="source-tag" style="background:{DANGER_RED_BG};color:{DANGER_RED_TEXT};">'
            f'\u25CF Disconnected</span>')

def kpi_traffic_style(pct: float, thresholds: dict) -> dict:
    if pct >= thresholds["green_min"]:
        return {"accent": "accent-green", "label": "On Track"}
    if pct >= thresholds["yellow_min"]:
        return {"accent": "accent-gold", "label": "Watch"}
    return {"accent": "accent-red", "label": "At Risk"}

def format_ts_short(iso_ts: str | None) -> str:
    if not iso_ts:
        return "\u2014"
    try:
        moment = dt.datetime.fromisoformat(str(iso_ts).replace("Z", "+00:00"))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=dt.timezone.utc)
        return moment.astimezone().strftime("%b %d, %I:%M %p")
    except Exception:
        return "\u2014"

def metric_card_html(label: str, value: str, sub: str, accent: str = "") -> str:
    return f"""
    <div class="metric-card">
        <div class="metric-label">{label}</div>
        <div class="metric-value {accent}">{value}</div>
        <div class="metric-sub">{sub}</div>
    </div>
    """

def _or_dash(value) -> str:
    if value is None:
        return "\u2014"
    try:
        if pd.isna(value):
            return "\u2014"
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text if text else "\u2014"

def recent_activity_feed(program_code: str, limit: int = 6) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    try:
        for entry in fetch_sync_logs(program_code, limit=10):
            ok = entry.get("status") == "success"
            events.append({
                "ts": entry.get("finished_at"),
                "color": OK_GREEN if ok else MAPUA_RED,
                "title": "Data sync succeeded" if ok else "Data sync failed",
                "sub": entry.get("error_message") or
                       f"{entry.get('rows_loaded', 0)} rows \u00b7 {entry.get('source') or 'sync'}",
            })
    except Exception:
        pass

    try:
        for change in fetch_recent_status_changes(program_code, limit=10):
            events.append({
                "ts": change.get("changed_at"),
                "color": MAPUA_GOLD,
                "title": f"{str(change.get('pillar', '')).replace('_', ' ').title()} changed "
                         f"\u2014 student {change.get('student_number')}",
                "sub": f"{change.get('old_status') or UNKNOWN} \u2192 {change.get('new_status')} "
                       f"\u00b7 by {change.get('changed_by')}",
            })
    except Exception:
        pass

    try:
        for attempt in fetch_access_logs(limit=20):
            if attempt.get("outcome") == "denied":
                events.append({
                    "ts": attempt.get("logged_at"),
                    "color": MAPUA_RED,
                    "title": "Access blocked",
                    "sub": f"{attempt.get('username')} ({attempt.get('role')}) "
                           f"\u2014 {attempt.get('action')}",
                })
    except Exception:
        pass

    events.sort(key=lambda e: e.get("ts") or "", reverse=True)
    return events[:limit]

def render_activity_panel(program_code: str) -> None:
    events = recent_activity_feed(program_code, 6)
    if not events:
        st.markdown(
            f"""<div style="padding: 24px 0; text-align: center; color: {LIGHT_GRAY}; font-size: 13px;">
            No recent activity logged.</div>""",
            unsafe_allow_html=True,
        )
        return
    html = ""
    for ev in events:
        html += f"""
        <div class="activity-item">
            <div>
                <span class="activity-dot" style="background:{ev['color']};"></span>
                <span class="activity-name">{ev['title']}</span>
                <div class="activity-sub">{ev['sub']}</div>
            </div>
            <div class="activity-time">{format_ts_short(ev['ts'])}</div>
        </div>
        """
    st.markdown(html, unsafe_allow_html=True)