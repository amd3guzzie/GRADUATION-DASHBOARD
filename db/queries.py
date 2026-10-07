import json
from typing import Any

import pandas as pd
import streamlit as st

# Local imports
from config.settings import Session, UNKNOWN, PILLARS, PILLAR_FIELD, ROLE_ADMIN, ROLE_STAFF, PERMISSION_VIEW, PERMISSION_EDIT
from db.connection import get_db_connection
from utils.formatting import now_iso, chunked

def fetch_programs() -> list[dict[str, Any]]:
    registry_fallback = False
    try:
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT
                        p.program_code,
                        p.program_name,
                        c.cohort_name AS current_term
                    FROM programs p
                    LEFT JOIN cohorts c ON p.program_id = c.program_id AND c.is_current = TRUE
                """)
                db_programs = cursor.fetchall()
        finally:
            conn.close()
    except Exception as exc:
        print(f"Database error: {exc}")
        db_programs = []
        registry_fallback = True

    formatted_programs = []
    for row in (db_programs or []):
        formatted_programs.append({
            "program_code": row["program_code"],
            "program_name": row["program_name"],
            "current_term": row["current_term"] or "",
            "is_active": True,
            "scope_column": "program_code"
        })

    known = {p["program_code"] for p in formatted_programs}
    if registry_fallback:
        for code, info in fetch_program_registry().items():
            if code not in known:
                formatted_programs.append({
                    "program_code": code,
                    "program_name": info.get("program_name") or code,
                    "current_term": info.get("current_term") or "",
                    "is_active": True,
                    "scope_column": "program_code",
                })
    return formatted_programs

def fetch_students(program_code: str, scope_column: str = "program_code") -> list[dict[str, Any]]:
    """Read the latest student records whenever the dashboard reruns."""
    in_program = """
        INNER JOIN students s ON s.student_id = t.student_id
        INNER JOIN programs p ON p.program_id = s.program_id
        WHERE p.program_code = %s
    """
    conn = get_db_connection()
    try:
        queries = ["""
            SELECT s.*, c.cohort_name
            FROM students s
            LEFT JOIN cohorts c ON c.cohort_id = s.cohort_id
            INNER JOIN programs p ON s.program_id = p.program_id
            WHERE p.program_code = %s
        """]
        queries.extend([
            "SELECT t.* FROM course_enrollment t" + in_program,
            "SELECT t.student_id, t.status, t.last_updated FROM coursework_status t" + in_program,
            "SELECT t.student_id, t.status, t.last_updated FROM comprehensive_exam_status t" + in_program,
            "SELECT t.student_id, t.status, t.adviser_name, t.defended, t.completed, t.last_updated "
            "FROM capstone_status t" + in_program,
            "SELECT t.student_id, t.graduate_on_time, t.graduate_date, t.remarks "
            "FROM graduation t" + in_program,
        ])
        try:
            with conn.cursor() as cursor:
                # Send the six reads together: one network round trip instead of six.
                cursor.execute(";".join(queries), (program_code,) * len(queries))
                result_sets = [cursor.fetchall()]
                for _ in queries[1:]:
                    cursor.nextset()
                    result_sets.append(cursor.fetchall())
            students_data, courses_data, coursework_data, comp_exam_data, capstone_data, graduation_data = result_sets
        except Exception:
            # Some managed MySQL services disable multi-statements. Keep the
            # regular read path available there, even though it needs more trips.
            conn.close()
            conn = get_db_connection()
            with conn.cursor() as cursor:
                result_sets = []
                for query in queries:
                    cursor.execute(query, (program_code,))
                    result_sets.append(cursor.fetchall())
            students_data, courses_data, coursework_data, comp_exam_data, capstone_data, graduation_data = result_sets
    finally:
        conn.close()

    courses_by_student: dict[Any, list[dict]] = {}
    for c in (courses_data or []):
        courses_by_student.setdefault(c.get("student_id"), []).append(dict(c))

    coursework_by_student = {r.get("student_id"): r for r in (coursework_data or [])}
    comp_exam_by_student = {r.get("student_id"): r for r in (comp_exam_data or [])}
    capstone_by_student = {r.get("student_id"): r for r in (capstone_data or [])}
    graduation_by_student = {r.get("student_id"): r for r in (graduation_data or [])}

    rows = []
    for r in (students_data or []):
        row = dict(r)
        s_id = row.get("student_id")

        row["student_email"] = row.get("email")
        row["cohort"] = row.get("cohort_name")

        cw = coursework_by_student.get(s_id) or {}
        row["coursework_status"] = cw.get("status")
        row["coursework_last_updated"] = cw.get("last_updated")

        cap = capstone_by_student.get(s_id) or {}
        row["advisers"] = [{"full_name": cap.get("adviser_name")}]

        grad = graduation_by_student.get(s_id) or {}
        row["graduate_on_time"] = grad.get("graduate_on_time")
        row["graduate_date_term_sy"] = grad.get("graduate_date")
        row["remarks"] = grad.get("remarks")

        ce = comp_exam_by_student.get(s_id) or {}
        row["student_milestones"] = [
            {"milestone_type": "comprehensive_exam", "status": ce.get("status"), "updated_at": ce.get("last_updated")},
            {"milestone_type": "capstone", "status": cap.get("status"), "updated_at": cap.get("last_updated")},
        ]

        row["student_course_enrollments"] = courses_by_student.get(s_id, [])
        rows.append(row)

    return rows


# --- MYSQL CONFIGURATION TABLES REPLACING JSON FILES ---

@st.cache_data(ttl=60, show_spinner=False)
def fetch_program_config(program_code: str) -> tuple[dict[str, Any], dict[str, Any]]:
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT dashboard_field, mapping_spec FROM field_mappings WHERE program_code = %s; "
                "SELECT config_key, config_value FROM dashboard_config WHERE program_code = %s",
                (program_code, program_code),
            )
            field_map = {row["dashboard_field"]: json.loads(row["mapping_spec"]) for row in cursor.fetchall()}
            cursor.nextset()
            settings = {row["config_key"]: json.loads(row["config_value"]) for row in cursor.fetchall()}
            return field_map, settings
    except Exception:
        return {}, {}
    finally:
        if conn is not None:
            conn.close()

def fetch_field_map(program_code: str) -> dict[str, Any]:
    return fetch_program_config(program_code)[0]

def save_field_map(program_code: str, dashboard_field: str, spec: dict, actor: str) -> None:
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO field_mappings (program_code, dashboard_field, mapping_spec)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE mapping_spec = VALUES(mapping_spec)
            """, (program_code, dashboard_field, json.dumps(spec)))
        conn.close()
        fetch_program_config.clear()
    except Exception as exc:
        print(f"Failed to save field map: {exc}")

def fetch_settings(program_code: str) -> dict[str, Any]:
    return fetch_program_config(program_code)[1]

def save_setting(program_code: str, key: str, value: Any, actor: str) -> None:
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO dashboard_config (program_code, config_key, config_value)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE config_value = VALUES(config_value)
            """, (program_code, key, json.dumps(value)))
        conn.close()
        fetch_program_config.clear()
    except Exception as exc:
        print(f"Failed to save setting: {exc}")

@st.cache_data(ttl=60, show_spinner=False)
def fetch_program_registry() -> dict[str, Any]:
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT program_code, program_name, current_term FROM programs")
            return {row["program_code"]: {"program_name": row["program_name"], "current_term": row["current_term"]} for row in cursor.fetchall()}
    except Exception:
        return {}

def save_program_record(program_code: str, program_name: str, current_term: str, actor: str) -> None:
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO programs (program_code, program_name)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE program_name = VALUES(program_name)
            """, (program_code, program_name))
        conn.close()
    except Exception as exc:
        print(f"Failed to save program record: {exc}")


# --- MYSQL STATUS HISTORY & LOGS TABLES REPLACING JSON FILES ---

def record_database_status_changes(program_code: str, frame: pd.DataFrame) -> int:
    if frame.empty:
        return 0
    changes_count = 0
    status_rows: list[tuple[Any, str, str, str]] = []

    def history_id_key(value: Any) -> str:
        try:
            numeric = float(value)
            if numeric.is_integer():
                return str(int(numeric))
        except (TypeError, ValueError):
            pass
        return str(value)

    for record in frame.to_dict(orient="records"):
        student_id = record.get("student_id")
        if pd.isna(student_id):
            continue
        student_number = str(record.get("student_number") or student_id)
        for pillar_key, _ in PILLARS:
            value = record.get(PILLAR_FIELD[pillar_key])
            new_status = UNKNOWN if pd.isna(value) or not str(value).strip() else str(value)
            status_rows.append((student_id, student_number, pillar_key, new_status))

    if not status_rows:
        return 0

    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            latest_status: dict[tuple[Any, str], str] = {}
            student_ids = list(dict.fromkeys(item[0] for item in status_rows))
            for student_id_chunk in chunked(student_ids, size=500):
                placeholders = ",".join(["%s"] * len(student_id_chunk))
                cursor.execute(
                    "SELECT student_id, pillar, new_status FROM status_history "
                    f"WHERE program_code = %s AND student_id IN ({placeholders}) "
                    "ORDER BY changed_at DESC",
                    (program_code, *student_id_chunk),
                )
                for item in cursor.fetchall():
                    latest_status.setdefault(
                        (history_id_key(item["student_id"]), item["pillar"]), item["new_status"]
                    )

            inserts = []
            for student_id, student_number, pillar_key, new_status in status_rows:
                old_status = latest_status.get((history_id_key(student_id), pillar_key))
                if old_status is None:
                    inserts.append((student_id, student_number, program_code, pillar_key, None, new_status, "initial sync"))
                elif old_status != new_status:
                    inserts.append((student_id, student_number, program_code, pillar_key, old_status, new_status, "student records system"))
                    changes_count += 1

            if inserts:
                cursor.executemany("""
                    INSERT INTO status_history
                        (student_id, student_number, program_code, pillar, old_status, new_status, changed_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, inserts)
    except Exception as exc:
        print(f"Could not update status history in MySQL: {exc}")
        return -1
    finally:
        if conn is not None:
            conn.close()
    return changes_count

@st.cache_data(ttl=30, show_spinner=False)
def fetch_status_history(student_number: int) -> list[dict[str, Any]]:
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT changed_at, pillar, old_status, new_status, changed_by
                FROM status_history
                WHERE student_number = %s
                ORDER BY changed_at DESC LIMIT 50
            """, (str(student_number),))
            return cursor.fetchall()
    except Exception:
        return []

@st.cache_data(ttl=20, show_spinner=False)
def fetch_recent_status_changes(program_code: str, limit: int = 20) -> list[dict[str, Any]]:
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT changed_at, student_number, pillar, old_status, new_status, changed_by
                FROM status_history
                WHERE program_code = %s
                ORDER BY changed_at DESC LIMIT %s
            """, (program_code, limit))
            return cursor.fetchall()
    except Exception:
        return []

def log_sync(program_code: str, status: str, rows_loaded: int = 0, error_message: str = "", source: str = "dashboard") -> None:
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO data_sync_log (program_code, status, records_processed, error_message, sync_timestamp)
                VALUES (%s, %s, %s, %s, NOW())
            """, (program_code, status.capitalize(), rows_loaded, error_message[:1000]))
        conn.close()
        fetch_sync_logs.clear()
        last_successful_sync.clear()
    except Exception as exc:
        print(f"Failed to log sync to database: {exc}")

@st.cache_data(ttl=20, show_spinner=False)
def fetch_sync_logs(program_code: str, limit: int = 200) -> list[dict[str, Any]]:
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT sync_timestamp AS finished_at, status, records_processed AS rows_loaded, error_message, 'database' AS source
                FROM data_sync_log
                WHERE program_code = %s OR program_code IS NULL
                ORDER BY sync_timestamp DESC LIMIT %s
            """, (program_code, limit))
            results = cursor.fetchall()
            for r in results:
                r["status"] = str(r["status"]).lower()
            return results
    except Exception:
        return []

@st.cache_data(ttl=20, show_spinner=False)
def last_successful_sync(program_code: str) -> str | None:
    logs = fetch_sync_logs(program_code)
    for log in logs:
        if log.get("status") == "success":
            return log.get("finished_at")
    return None

def consecutive_failures(program_code: str) -> int:
    count = 0
    for entry in fetch_sync_logs(program_code, limit=25):
        if entry.get("status") == "success":
            break
        count += 1
    return count

def refresh_data() -> None:
    for cached in (fetch_program_registry, fetch_program_config, fetch_sync_logs, last_successful_sync, fetch_status_history, fetch_recent_status_changes, connection_check):
        cached.clear()


# --- MYSQL USERS & ACCESS LOG TABLES REPLACING JSON FILES ---

@st.cache_data(ttl=300, show_spinner=False) # Caches the data for 5 minutes!
def load_users() -> list[dict[str, Any]]:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM users")
            return cursor.fetchall()
    finally:
        conn.close() # This safely shuts the tunnel after fetching

def load_demo_accounts() -> list[dict[str, Any]]:
    """Return only the public showcase fields for active accounts."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT full_name, role, permission_level FROM users "
                "WHERE is_active = 1 ORDER BY role, full_name"
            )
            return cursor.fetchall()
    finally:
        conn.close()

@st.cache_data(ttl=300, show_spinner=False)
def load_access_log() -> list[dict[str, Any]]:
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT logged_at, username, role, action, outcome, detail FROM access_log ORDER BY logged_at DESC LIMIT 300")
            return cursor.fetchall()
    finally:
        conn.close()

def log_access(username: str, role: str, action: str, outcome: str, detail: str = "") -> None:
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO access_log (logged_at, username, role, action, outcome, detail) VALUES (%s, %s, %s, %s, %s, %s)",
                (now_iso(), username, role, action, outcome, detail[:500])
            )
        conn.close()
    except Exception:
        st.session_state["_log_write_failures"] = st.session_state.get("_log_write_failures", 0) + 1

def fetch_access_logs(limit: int = 300) -> list[dict[str, Any]]:
    return load_access_log()[:limit]

def authenticate(username: str, password: str, role: str) -> Session | None:
    users = load_users()
    
    # 1. Match against the 'full_name' column (e.g., "John Reyes")
    match = next(
        (
            u for u in users
            if u["role"] == role
            and u["full_name"].strip().lower() == username.strip().lower()
        ),
        None,
    )
    
    # 2. Check if user exists and is active
    if not match or not match.get("is_active", 1):
        log_access(username.strip() or "(blank)", role, "sign in", "denied", "Unknown or deactivated account")
        return None
        
    # 3. Strictly check against the dynamic database password (no hardcoded fallback)
    if match.get("password") != password:
        log_access(match["full_name"], match.get("role", "-"), "sign in", "denied", "Wrong password")
        return None

    # 4. Map the database columns to the Streamlit Session object
    session = Session(
        username=match["full_name"],  
        full_name=match["full_name"],
        role=match.get("role") or ROLE_STAFF,
        permission_level=match.get("permission_level") or PERMISSION_VIEW,
        adviser_name=match.get("adviser_name") or "",
    )
    
    log_access(session.username, session.role, "sign in", "allowed", "")
    return session

def upsert_user(actor: Session, full_name: str, email: str, role: str,
                permission_level: str, password: str | None = None, is_active: bool = True,
                adviser_name: str = "") -> tuple[bool, str]:
    if not actor.is_admin:
        log_access(actor.username, actor.role, f"change account: {full_name}", "denied", "Only IT/Admin may change roles")
        return False, "Only an IT/Admin account can edit users."

    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # Check if user already exists to keep their old password if a new one isn't provided
            cursor.execute("SELECT password FROM users WHERE full_name = %s", (full_name.strip(),))
            existing = cursor.fetchone()
            
            pwd_to_save = password if password else (existing["password"] if existing else "Password123")

            cursor.execute("""
                INSERT INTO users (full_name, email, role, permission_level, password, is_active, adviser_name)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    email = VALUES(email),
                    role = VALUES(role),
                    permission_level = VALUES(permission_level),
                    password = VALUES(password),
                    is_active = VALUES(is_active),
                    adviser_name = VALUES(adviser_name)
            """, (full_name.strip(), email.strip(), role, permission_level, pwd_to_save, is_active, adviser_name.strip()))
        conn.close()
        log_access(actor.username, actor.role, f"change account: {full_name}", "allowed", "User profile updated")
        return True, f"Saved {full_name}."
    except Exception as exc:
        return False, f"The account was not saved: {exc}"

# --- MISSING UI & SESSION HELPER FUNCTIONS ---

def require_edit() -> bool:
    """Checks if the currently logged-in user has permission to edit."""
    session = st.session_state.get("session")
    if not session or not session.can_edit:
        st.warning("This action requires edit permissions. Your account is view-only.")
        return False
    return True

def list_users() -> list[dict[str, Any]]:
    """Fetches the list of users from the database for admin management."""
    return load_users()

def current_session() -> Any:
    """Retrieves the current user session from Streamlit's session state."""
    return st.session_state.get("session")

def sign_out() -> None:
    """Logs out the current user, writes an audit log, and clears the session."""
    session = st.session_state.get("session")
    if session:
        log_access(session.username, session.role, "sign out", "allowed", "")
        if "session" in st.session_state:
            del st.session_state["session"]
        # Destroy the cookie so they don't auto-login again
        cookie_manager.remove('dashboard_user')
    st.rerun()