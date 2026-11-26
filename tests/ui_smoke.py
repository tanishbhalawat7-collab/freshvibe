"""Headless browser smoke test: loads every page, captures console errors and
screenshots. Requires: pip install playwright && a Chrome/Chromium install.

    python tests/ui_smoke.py http://localhost:8000 out_dir
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else "screenshots")
OUT.mkdir(exist_ok=True)
PAGES = ["dashboard", "scan", "tracker", "barcode", "inventory", "add", "camera", "settings", "diagnostics"]

errors = []
with sync_playwright() as p:
    exe = next((c for c in ("/usr/bin/google-chrome", "/usr/bin/chromium") if Path(c).exists()), None)
    browser = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 960})
    page.on("console", lambda m: m.type == "error" and errors.append(f"{page.url}: {m.text}"))
    page.on("pageerror", lambda e: errors.append(f"{page.url}: {e}"))
    for name in PAGES:
        page.goto(f"{BASE}/#/{name}")
        page.wait_for_timeout(2500 if name in ("diagnostics", "camera") else 1200)
        page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
    # run a real scan through the UI
    page.goto(f"{BASE}/#/scan")
    page.wait_for_timeout(800)
    page.click("#scan-cam")
    page.wait_for_selector("#result .steps", timeout=60000)
    page.wait_for_timeout(500)
    page.screenshot(path=str(OUT / "scan_result.png"), full_page=True)
    # mobile layout
    m = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True)
    m.on("pageerror", lambda e: errors.append(f"mobile: {e}"))
    m.goto(f"{BASE}/#/dashboard")
    m.wait_for_timeout(1200)
    m.screenshot(path=str(OUT / "mobile_dashboard.png"), full_page=True)
    browser.close()

print("console/page errors:", len(errors))
for e in errors:
    print("  ", e)
sys.exit(1 if errors else 0)
