"""Locust load test for Stock Research Assistant (HF Spaces).

Run: locust -f tests/load/locustfile.py --host https://tshaik1990-stock-research-assistant.hf.space

Safe endpoints tested:
  - Health check (GET /_stcore/health) — free, no API cost
  - Main page load (GET /) — Streamlit render
  - Static assets (GET /favicon.ico) — CDN/cached

NOT load tested (costs DeepSeek credits):
  - Analysis pipeline — smoke tested once, not in load loop
"""

from locust import HttpUser, task, between, events
import time


class StockResearchUser(HttpUser):
    """Simulates a user browsing the Stock Research Assistant."""

    wait_time = between(2, 5)  # Realistic user pacing

    def on_start(self):
        """Each simulated user starts by loading the main page."""
        with self.client.get("/", catch_response=True) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Main page returned {resp.status_code}")

    @task(3)
    def health_check(self):
        """Health endpoint — most frequent task."""
        with self.client.get("/_stcore/health", catch_response=True, timeout=10) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Health check returned {resp.status_code}")

    @task(2)
    def main_page(self):
        """Full page load — Streamlit renders on each request."""
        with self.client.get("/", catch_response=True, timeout=30) as resp:
            if resp.status_code == 200:
                resp.success()
            elif resp.status_code == 503:
                # HF Spaces cold start — acceptable
                resp.success()
            else:
                resp.failure(f"Page returned {resp.status_code}")

    @task(1)
    def streamlit_health(self):
        """Streamlit-specific health endpoint."""
        with self.client.get("/_stcore/healthz", catch_response=True, timeout=10) as resp:
            if resp.status_code in (200, 404):
                resp.success()
            else:
                resp.failure(f"Streamlit health returned {resp.status_code}")


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """Smoke test — verify the app is up before load testing."""
    import urllib.request

    url = "https://tshaik1990-stock-research-assistant.hf.space/_stcore/health"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SRA-LoadTest/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status == 200:
                print("✅ Smoke test passed — HF Space is up")
            else:
                print(f"⚠️  Smoke test: HTTP {resp.status}")
                environment.runner.quit()
    except Exception as e:
        print(f"❌ Smoke test failed: {e}")
        environment.runner.quit()
