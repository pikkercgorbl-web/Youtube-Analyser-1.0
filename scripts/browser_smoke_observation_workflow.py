#!/usr/bin/env python3
"""
Interactive browser smoke (Playwright) on test DB backend.
Starts ephemeral backend :8766 + Next dev :3002, exercises UI buttons/forms.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
FAMILY_KEY = "family:e2e:readiness"


def _test_db_url() -> str:
    url = os.environ.get("SAVED_TOPICS_POSTGRES_TEST_URL", "").strip()
    if not url or "test" not in url.lower():
        raise SystemExit("Set SAVED_TOPICS_POSTGRES_TEST_URL")
    prod = os.environ.get("DATABASE_URL", "")
    if prod and prod.rstrip("/") == url.rstrip("/"):
        raise SystemExit("Refusing: test URL equals DATABASE_URL")
    return url


def _wait_url(url: str, timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status < 500:
                    return
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.5)
    raise TimeoutError(f"Timeout waiting for {url}")


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright", "-q"])
        from playwright.sync_api import sync_playwright

    test_url = _test_db_url()
    env = os.environ.copy()
    env["DATABASE_URL"] = test_url
    env.pop("SAVED_TOPICS_POSTGRES_TEST_URL", None)

    subprocess.check_call([sys.executable, str(ROOT / "scripts" / "seed_test_db_attention_family.py")], env=env)

    backend = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8766"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    front_env = os.environ.copy()
    front_env["NEXT_PUBLIC_API_URL"] = "http://127.0.0.1:8766"
    frontend = subprocess.Popen(
        "npm run dev -- -p 3002",
        cwd=FRONTEND,
        env=front_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        shell=True,
    )
    results: dict[str, object] = {"steps": [], "ok": True}
    try:
        _wait_url("http://127.0.0.1:8766/docs")
        _wait_url("http://127.0.0.1:3002/opportunities", timeout=120)

        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(channel="msedge", headless=True)
            except Exception:
                browser = p.chromium.launch(channel="chrome", headless=True)
            page = browser.new_page()
            page.goto("http://127.0.0.1:3002/opportunities", wait_until="networkidle", timeout=120_000)
            page.get_by_test_id("save-pattern").first.click(timeout=30_000)
            page.wait_for_timeout(1500)
            saved = page.get_by_test_id("save-pattern-saved").first
            saved.wait_for(timeout=15_000)
            href = saved.locator("xpath=ancestor-or-self::a").first.get_attribute("href") or saved.evaluate(
                "el => el.closest('a')?.getAttribute('href')",
            )
            results["steps"].append({"opportunities_save": True, "href": href})

            page.goto("http://127.0.0.1:3002/saved-topics", wait_until="networkidle")
            page.get_by_role("link", name="Карточка").first.wait_for(timeout=15_000)

            detail_url = href if href and href.startswith("/") else None
            if not detail_url:
                detail_url = page.get_by_role("link", name="Карточка").first.get_attribute("href")
            assert detail_url
            page.goto(f"http://127.0.0.1:3002{detail_url}", wait_until="networkidle")

            page.locator("select").filter(has_text="Наблюдаю").first.select_option("WANT_TO_TEST")
            page.get_by_role("button", name="Сохранить изменения").click()
            page.wait_for_timeout(1000)

            page.get_by_role("button", name="Добавить оценку").click()
            page.wait_for_timeout(1000)

            page.goto("http://127.0.0.1:3002/validation", wait_until="networkidle")
            page.get_by_text("тем сохранено за период").wait_for(timeout=15_000)

            page.goto(f"http://127.0.0.1:3002{detail_url}", wait_until="networkidle")
            page.get_by_role("button", name="В архив").click()
            page.wait_for_timeout(800)
            page.get_by_role("button", name="Восстановить").click()
            page.wait_for_timeout(800)

            browser.close()
        results["steps"].append({"detail_forms": True, "validation": True, "archive_restore": True})
    except Exception as exc:
        results["ok"] = False
        results["error"] = str(exc)
        if frontend.stdout:
            tail = frontend.stdout.read()[-4000:] if hasattr(frontend.stdout, "read") else ""
            results["frontend_log_tail"] = tail
    finally:
        frontend.terminate()
        backend.terminate()
        try:
            frontend.wait(timeout=5)
        except subprocess.TimeoutExpired:
            frontend.kill()
        try:
            backend.wait(timeout=5)
        except subprocess.TimeoutExpired:
            backend.kill()

    print(json.dumps(results, indent=2, ensure_ascii=False))
    return 0 if results.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
