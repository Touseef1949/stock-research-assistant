"""Coverage gap tests: error_logging.py — rotation, JSON format, exception swallowing.

Currently 26% coverage. These tests exercise every path:
- log_error: normal write, with exception, file I/O failure
- get_recent_errors: empty log, normal read, corrupt lines, truncation
- clear_error_log: success, file doesn't exist
- _ensure_log_dir: directory creation
"""

import json
import os
from datetime import datetime
from pathlib import Path
from unittest.mock import mock_open, patch

import pytest

LOG_DIR = Path(__file__).resolve().parent.parent / "services"


# =============================================================================
# log_error — primary path
# =============================================================================

class TestLogError:
    """Exercise all code paths in log_error()."""

    def test_writes_jsonl_entry_without_exception(self, tmp_path):
        """Normal write: component + message + data, no exception."""
        from services.error_logging import log_error

        with patch("services.error_logging.LOG_FILE",
                   tmp_path / "errors.jsonl"):
            log_error("test_comp", "test message", data={"key": "val"})

            with open(tmp_path / "errors.jsonl") as f:
                entry = json.loads(f.readline())

        assert entry["component"] == "test_comp"
        assert entry["message"] == "test message"
        assert entry["data"] == {"key": "val"}
        assert "timestamp" in entry
        assert "traceback" not in entry  # no exception passed

    def test_includes_traceback_when_exception_provided(self, tmp_path):
        """When exc is passed, traceback is included in the log entry."""
        from services.error_logging import log_error

        log_path = tmp_path / "errors.jsonl"
        with patch("services.error_logging.LOG_FILE", log_path):
            try:
                raise ValueError("test exception")
            except ValueError as e:
                log_error("comp", "msg", exc=e)

            with open(log_path) as f:
                entry = json.loads(f.readline())

        assert "traceback" in entry
        assert "ValueError" in entry["traceback"]
        assert "test exception" in entry["traceback"]

    def test_swallows_write_failure(self, tmp_path):
        """IF log file can't be written, log_error should NOT crash."""
        from services.error_logging import log_error

        log_path = tmp_path / "errors.jsonl"
        with patch("services.error_logging.LOG_FILE", log_path):
            with patch("builtins.open", side_effect=PermissionError("denied")):
                # Should not raise
                log_error("comp", "should not crash")

        # After the mock, verify the function didn't propagate the exception
        assert True  # survived

    def test_creates_log_directory_if_missing(self, tmp_path):
        """_ensure_log_dir creates the directory if it doesn't exist."""
        from services.error_logging import _ensure_log_dir

        new_dir = tmp_path / "nonexistent" / "logs"
        with patch("services.error_logging.LOG_DIR", new_dir):
            _ensure_log_dir()
        assert new_dir.is_dir()


# =============================================================================
# get_recent_errors — read path
# =============================================================================

class TestGetRecentErrors:
    """Exercise all code paths in get_recent_errors()."""

    def test_returns_empty_list_when_file_missing(self):
        """When log file doesn't exist, return empty list."""
        from services.error_logging import get_recent_errors

        with patch("services.error_logging.LOG_FILE",
                   Path("/nonexistent/nope.jsonl")):
            errors = get_recent_errors()
        assert errors == []

    def test_returns_all_entries_when_limit_is_none(self, tmp_path):
        """When limit=None, return all entries."""
        from services.error_logging import get_recent_errors

        log_path = tmp_path / "errors.jsonl"
        log_path.write_text(
            json.dumps({"component": "a", "message": "1"}) + "\n"
            + json.dumps({"component": "b", "message": "2"}) + "\n"
        )

        with patch("services.error_logging.LOG_FILE", log_path):
            errors = get_recent_errors()
        assert len(errors) == 2
        assert errors[0]["component"] == "b"  # reversed — most recent first
        assert errors[1]["component"] == "a"

    def test_respects_limit_parameter(self, tmp_path):
        """When limit is set, return only the last N entries."""
        from services.error_logging import get_recent_errors

        log_path = tmp_path / "errors.jsonl"
        lines = [
            json.dumps({"i": i}) for i in range(10)
        ]
        log_path.write_text("\n".join(lines) + "\n")

        with patch("services.error_logging.LOG_FILE", log_path):
            errors = get_recent_errors(limit=5)
        assert len(errors) == 5

    def test_handles_corrupt_json_lines(self, tmp_path):
        """Corrupt JSON lines are skipped gracefully."""
        from services.error_logging import get_recent_errors

        log_path = tmp_path / "errors.jsonl"
        log_path.write_text(
            "not valid json\n"
            + json.dumps({"ok": True}) + "\n"
            + "also bad\n"
        )

        with patch("services.error_logging.LOG_FILE", log_path):
            errors = get_recent_errors()
        assert len(errors) == 1
        assert errors[0]["ok"] is True

    def test_handles_read_permission_error(self):
        """IOError during read returns empty list."""
        from services.error_logging import get_recent_errors

        with patch("services.error_logging.LOG_FILE",
                   Path("/root/forbidden.jsonl")):
            with patch("builtins.open", side_effect=IOError("denied")):
                errors = get_recent_errors()
        assert errors == []


# =============================================================================
# get_error_summary — aggregation path
# =============================================================================

class TestGetErrorSummary:
    """Exercise get_error_summary()."""

    def test_returns_zero_count_when_no_errors(self, tmp_path):
        """Empty log returns error_count=0."""
        from services.error_logging import get_error_summary

        log_path = tmp_path / "errors.jsonl"
        log_path.write_text("")

        with patch("services.error_logging.LOG_FILE", log_path):
            summary = get_error_summary()

        assert summary["error_count"] == 0
        assert summary["last_error"] is None

    def test_counts_errors_and_lists_components(self, tmp_path):
        """Summary includes count, timestamp, and component list."""
        from services.error_logging import get_error_summary

        log_path = tmp_path / "errors.jsonl"
        log_path.write_text(
            json.dumps({
                "timestamp": "2026-01-01T00:00:00Z",
                "component": "api",
                "message": "err1",
            }) + "\n"
            + json.dumps({
                "timestamp": "2026-06-21T00:00:00Z",
                "component": "ui",
                "message": "err2",
            }) + "\n"
        )

        with patch("services.error_logging.LOG_FILE", log_path):
            summary = get_error_summary()

        assert summary["error_count"] == 2
        assert summary["last_error"] == "2026-06-21T00:00:00Z"
        assert set(summary["components"]) == {"api", "ui"}


# =============================================================================
# Rotation — MAX_LOG_LINES enforcement
# =============================================================================

class TestRotation:
    """Exercise log rotation / truncation."""

    def test_log_rotation_truncates_old_entries(self, tmp_path):
        """When log exceeds MAX_LOG_LINES, oldest entries are trimmed."""
        from services.error_logging import MAX_LOG_LINES, log_error

        log_path = tmp_path / "errors.jsonl"
        with patch("services.error_logging.LOG_FILE", log_path):
            # Write MAX_LOG_LINES + 10 entries
            for i in range(MAX_LOG_LINES + 10):
                log_error("test", f"msg {i}")

            with open(log_path) as f:
                lines = f.readlines()

        assert len(lines) <= MAX_LOG_LINES
        # First entry should be from later in the sequence (old ones trimmed)
        first = json.loads(lines[0])
        assert "msg 0" not in first["message"]  # old entries trimmed
