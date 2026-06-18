"""Production error logging for Stock Research Assistant.

Writes structured JSONL logs to a local file. On HF Spaces, the file
is ephemeral (resets on restart) but provides per-session diagnostics.
For persistent logging, pair with an external service (Sentry, Logtail, etc.).

Usage:
    from services.error_logging import log_error, get_recent_errors

    try:
        ...
    except Exception:
        log_error("analysis_pipeline", str(exc), data={"symbol": symbol})

    # Read recent errors for health check
    errors = get_recent_errors(limit=10)
"""

from __future__ import annotations

import json
import traceback
from datetime import datetime, timezone
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_FILE = LOG_DIR / "errors.jsonl"
MAX_LOG_LINES = 500


def _ensure_log_dir() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def log_error(
    component: str,
    message: str,
    data: dict | None = None,
    exc: Exception | None = None,
) -> None:
    """Write a structured error entry to the JSONL log."""
    _ensure_log_dir()

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "component": component,
        "message": message,
        "data": data or {},
    }

    if exc is not None:
        entry["traceback"] = "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        )

    try:
        with open(LOG_FILE, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception:
        pass  # Never crash the app because of logging

    _trim_log_if_needed()


def get_recent_errors(limit: int = 20) -> list[dict]:
    """Return the most recent error entries from the log."""
    _ensure_log_dir()

    if not LOG_FILE.exists():
        return []

    try:
        lines = LOG_FILE.read_text().strip().splitlines()
        entries = []
        for line in lines[-limit:]:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return list(reversed(entries))
    except Exception:
        return []


def _trim_log_if_needed() -> None:
    """Keep only the last MAX_LOG_LINES entries."""
    try:
        if not LOG_FILE.exists():
            return
        lines = LOG_FILE.read_text().strip().splitlines()
        if len(lines) > MAX_LOG_LINES:
            LOG_FILE.write_text("\n".join(lines[-MAX_LOG_LINES:]) + "\n")
    except Exception:
        pass


def get_error_summary() -> dict:
    """Return a summary for health monitoring: count + last error timestamp."""
    errors = get_recent_errors(limit=50)
    if not errors:
        return {"error_count": 0, "last_error": None}

    return {
        "error_count": len(errors),
        "last_error": errors[0]["timestamp"] if errors else None,
        "components": list(set(e.get("component", "unknown") for e in errors)),
    }
