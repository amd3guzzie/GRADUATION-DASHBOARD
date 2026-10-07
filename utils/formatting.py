import datetime as dt
import re
from typing import Any

def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()

def humanise(timestamp: str | None) -> str:
    if not timestamp:
        return "never"
    try:
        moment = dt.datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=dt.timezone.utc)
        return moment.astimezone().strftime("%d %b %Y, %H:%M %Z")
    except ValueError:
        return str(timestamp)

def rows(response: Any) -> list[dict[str, Any]]:
    data = getattr(response, "data", None)
    return list(data) if data else []

def chunked(items: list, size: int = 400):
    for start in range(0, len(items), size):
        yield items[start : start + size]

def term_sort_key(name: Any) -> list:
    # Sorts "Term 2" before "Term 10" (plain sorting would put 10 first).
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", str(name))]

def sorted_terms(values) -> list[str]:
    return sorted({str(v) for v in values if v is not None and str(v).strip() and str(v) != "nan"}, key=term_sort_key)