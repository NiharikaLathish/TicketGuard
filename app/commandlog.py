"""In-memory log of the database commands the app runs, shown on the live demo page (/demo).

Only the most recent entries are kept. It is a teaching aid, not an audit log.
"""
import threading
from collections import deque
from datetime import datetime, timezone

_lock = threading.Lock()
_entries: deque = deque(maxlen=500)
_last_id = 0


def record(store: str, text: str) -> None:
    """Add one command. store is one of: cassandra, neo4j, sync."""
    global _last_id
    with _lock:
        _last_id += 1
        _entries.append({"id": _last_id, "store": store, "text": text,
                         "at": datetime.now(timezone.utc).isoformat(timespec="milliseconds")})


def since(after: int = 0, limit: int = 200) -> dict:
    """Entries newer than `after` (at most the last `limit`), plus the id of the newest entry."""
    with _lock:
        rows = [e for e in _entries if e["id"] > after]
        last = _last_id
    return {"last_id": last, "commands": rows[-limit:] if limit > 0 else []}
