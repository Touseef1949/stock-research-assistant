#!/usr/bin/env python3
"""Production health monitor for Stock Research Assistant.

Checks HF Space availability, error log, and response time.
Exit code 0 = healthy, 1 = unhealthy (cron will notify).
"""

import json
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

HF_SPACE_URL = "https://tshaik1990-stock-research-assistant.hf.space"
HEALTH_ENDPOINT = f"{HF_SPACE_URL}/_stcore/health"
TIMEOUT_SECONDS = 15
RETRIES = 2

PROJECT_DIR = Path(__file__).resolve().parent.parent
LOG_FILE = PROJECT_DIR / "logs" / "errors.jsonl"


def check_endpoint(url: str, timeout: int = 15) -> tuple[bool, float, str]:
    """Check if an HTTP endpoint returns 200. Returns (healthy, latency_sec, detail)."""
    for attempt in range(RETRIES + 1):
        try:
            start = time.monotonic()
            req = urllib.request.Request(url, headers={"User-Agent": "SRA-HealthMonitor/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                latency = time.monotonic() - start
                if resp.status == 200:
                    return True, latency, "OK"
                return False, latency, f"HTTP {resp.status}"
        except urllib.error.HTTPError as e:
            return False, 0.0, f"HTTP {e.code}"
        except Exception as e:
            if attempt == RETRIES:
                return False, 0.0, str(e)
            time.sleep(2)
    return False, 0.0, "unknown"


def check_error_log() -> dict:
    """Count recent errors (>7 days = stale)."""
    if not LOG_FILE.exists():
        return {"count": 0, "fresh_errors": 0}

    try:
        cutoff = datetime.now(timezone.utc).timestamp() - 7 * 86400
        fresh = 0
        total = 0
        for line in LOG_FILE.read_text().strip().splitlines():
            try:
                entry = json.loads(line)
                total += 1
                ts = entry.get("timestamp", "")
                if ts:
                    entry_time = datetime.fromisoformat(ts).timestamp()
                    if entry_time > cutoff:
                        fresh += 1
            except (json.JSONDecodeError, ValueError):
                continue
        return {"count": total, "fresh_errors": fresh}
    except Exception:
        return {"count": -1, "fresh_errors": -1}


def main() -> int:
    print(f"=== SRA Health Check — {datetime.now(timezone.utc).isoformat()} ===")

    # 1. Endpoint check
    healthy, latency, detail = check_endpoint(HEALTH_ENDPOINT)
    if healthy:
        print(f"✅ HF Space healthy ({latency:.2f}s)")
    else:
        print(f"❌ HF Space DOWN: {detail}")

    # 2. Error log check
    errors = check_error_log()
    if errors["fresh_errors"] > 10:
        print(f"⚠️  {errors['fresh_errors']} recent errors (threshold: 10)")
    elif errors["fresh_errors"] > 0:
        print(f"ℹ️  {errors['fresh_errors']} recent errors in log")
    else:
        print(f"✅ Error log clean")

    # 3. Overall verdict
    if not healthy:
        print("\n❌ HEALTH CHECK FAILED — Space is unreachable")
        return 1
    if errors["fresh_errors"] > 10:
        print("\n⚠️  HEALTH WARNING — High error rate")
        return 1

    print("\n✅ All checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
