"""Report persistence and JSON serialization service.

This module is intentionally independent from Streamlit so future production
apps can reuse and test report-history behavior without importing the UI entrypoint.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from core.models import AgentResult
from logic import clamp_score

DownloadBuilder = Callable[[dict[str, Any], dict[str, Any]], tuple[bytes, str, str]]


def report_file_symbol(symbol: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", str(symbol or "stock")).strip("_")
    return cleaned or "stock"


def report_path_for(reports_dir: Path, symbol: str, timestamp: str) -> Path:
    return reports_dir / f"{report_file_symbol(symbol)}_{timestamp}.json"


def timestamp_from_report_path(path: Path) -> str:
    try:
        _, date_part, time_part = path.stem.rsplit("_", 2)
        return f"{date_part}_{time_part}"
    except ValueError:
        return ""


def json_safe(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, AgentResult):
        return {
            "name": value.name,
            "content": value.content,
            "score": value.score,
            "source": value.source,
        }
    if isinstance(value, pd.DataFrame):
        frame = value.reset_index()
        return {
            "__type": "dataframe",
            "records": json_safe(frame.to_dict(orient="records")),
        }
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return None if pd.isna(value) else value
    if hasattr(value, "item"):
        try:
            return json_safe(value.item())
        except Exception:
            return str(value)
    try:
        if pd.isna(value):
            return None
    except Exception:
        return str(value)
    return str(value)


def restore_dataframe(value: Any) -> pd.DataFrame:
    if isinstance(value, dict) and value.get("__type") == "dataframe":
        frame = pd.DataFrame(value.get("records") or [])
    else:
        frame = pd.DataFrame(value)
    for column in ("Date", "Datetime", "index"):
        if column in frame.columns:
            parsed = pd.to_datetime(frame[column], errors="coerce")
            if parsed.notna().any():
                frame[column] = parsed
            frame = frame.set_index(column)
            break
    return frame


def restore_report_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    data = dict(payload.get("data") or {})
    result = dict(payload.get("result") or {})
    if "history" in data:
        data["history"] = restore_dataframe(data["history"])
    outputs = result.get("agent_outputs")
    if isinstance(outputs, dict):
        restored_outputs = {}
        for name, output in outputs.items():
            if isinstance(output, AgentResult):
                restored_outputs[name] = output
            elif isinstance(output, dict):
                restored_outputs[name] = AgentResult(
                    name=str(output.get("name") or name),
                    content=str(output.get("content") or "No agent notes were returned."),
                    score=clamp_score(output.get("score", 5.0)),
                    source=str(output.get("source") or "agent"),
                )
            else:
                restored_outputs[name] = output
        result["agent_outputs"] = restored_outputs
    return data, result


def read_report_file(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def enforce_report_cap(reports_dir: Path, max_report_files: int) -> None:
    try:
        files = sorted(reports_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    except Exception:
        return
    for path in files[max_report_files:]:
        try:
            path.unlink()
        except Exception:
            continue


def save_report(
    data: dict[str, Any],
    result: dict[str, Any],
    email: str = "",
    *,
    reports_dir: Path,
    max_report_files: int,
    now: Callable[[], datetime] = datetime.now,
) -> dict[str, str] | None:
    try:
        reports_dir.mkdir(parents=True, exist_ok=True)
        symbol = str(data.get("base_symbol") or data.get("symbol") or "stock")
        timestamp = now().strftime("%Y%m%d_%H%M%S")
        clean_email = str(email or "").strip().lower()
        payload = {
            "symbol": symbol,
            "name": str(data.get("name") or symbol),
            "verdict": str(result.get("verdict") or "Unavailable"),
            "score": float(result.get("composite") or 0),
            "time": str(result.get("generated_at") or data.get("as_of") or ""),
            "timestamp": timestamp,
            "email": clean_email,
            "data": json_safe(data),
            "result": json_safe(result),
        }
        path = report_path_for(reports_dir, symbol, timestamp)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        enforce_report_cap(reports_dir, max_report_files)
        return {"timestamp": timestamp, "path": str(path)}
    except Exception:
        return None


def load_history_items(reports_dir: Path, email: str, max_report_files: int) -> list[dict[str, Any]] | None:
    clean_email = str(email or "").strip().lower()
    if not clean_email:
        return []
    try:
        reports_dir.mkdir(parents=True, exist_ok=True)
        files = sorted(reports_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    except Exception:
        return None

    history: list[dict[str, Any]] = []
    for path in files[:max_report_files]:
        payload = read_report_file(path)
        if not payload:
            continue
        payload_email = str(payload.get("email") or "").strip().lower()
        if payload_email != clean_email:
            continue
        symbol = str(payload.get("symbol") or "").strip()
        timestamp = str(payload.get("timestamp") or timestamp_from_report_path(path)).strip()
        if not symbol or not timestamp:
            continue
        history.append(
            {
                "symbol": symbol,
                "name": str(payload.get("name") or symbol),
                "verdict": str(payload.get("verdict") or "Unavailable"),
                "score": float(payload.get("score") or 0),
                "time": str(payload.get("time") or ""),
                "timestamp": timestamp,
                "path": str(path),
                "email": payload_email,
            }
        )
    enforce_report_cap(reports_dir, max_report_files)
    return history


def load_report_payload(reports_dir: Path, symbol: str, timestamp: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    payload = read_report_file(report_path_for(reports_dir, symbol, timestamp))
    if not payload:
        return None
    data, result = restore_report_payload(payload)
    if not data or not result:
        return None
    return data, result


def report_payload_from_history(
    item: dict[str, Any],
    *,
    reports_dir: Path,
    download_builder: DownloadBuilder,
) -> tuple[bytes, str, str] | None:
    payload = read_report_file(report_path_for(reports_dir, str(item.get("symbol", "")), str(item.get("timestamp", ""))))
    if not payload:
        return None
    data, result = restore_report_payload(payload)
    try:
        return download_builder(data, result)
    except Exception:
        return None
