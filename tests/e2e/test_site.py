"""Real-browser E2E of the published (static, encrypted) site, built offline from fixtures.

Run: E2E=1 uv run --group e2e pytest -m e2e   (after `uv run --group e2e playwright install chromium`)
Guards what unit tests can't: decryption in the browser, every tab rendering, no console errors,
and no data-source names leaking into the page.
"""

from __future__ import annotations

import asyncio
import functools
import http.server
import os
import re
import threading

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.skipif(os.environ.get("E2E") != "1", reason="set E2E=1 to run browser tests")]
PROVIDERS = re.compile(r"youtube|google|naver|네이버|\bnate\b|signal[._]bz|wikipedia|datalab", re.I)


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    from trend_engine.config import Settings
    from trend_engine.export import export_site
    from trend_engine.service import TrendService
    from trend_engine.store import Store

    root = tmp_path_factory.mktemp("e2e")
    os.environ["TREND_ENGINE_DATA_KEY"] = "22" * 32
    svc = TrendService(Settings(offline=True, db_path=":memory:", archive_dir=str(root / "archive")), Store(":memory:"))
    asyncio.run(export_site(svc, root / "site", ["KR", "US", "JP"], health_path=root / "health.json"))
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root / "site"))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/"  # localhost = secure context -> WebCrypto works
    httpd.shutdown()


@pytest.fixture
def page(site):
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page(viewport={"width": 1280, "height": 900})
        errors: list[str] = []
        pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.errors = errors
        yield pg
        browser.close()


def wait_rows(page, selector, n=1):
    page.wait_for_function(f"document.querySelectorAll({selector!r}).length >= {n}", timeout=15000)


def test_youth_tab_is_default_and_renders(page, site):
    page.goto(site)
    wait_rows(page, "#y-disc li")
    assert page.locator(".tab[aria-selected=true]").inner_text() == "10·20대"
    assert page.locator("#ygroups [data-g]").count() == 6
    page.click("#ygroups [data-g='20대 여성']")
    assert "20대 여성" in page.locator("#y-title").inner_text()
    page.click("#yperiod [data-p=month]")
    page.wait_for_function("document.querySelector('#y-title2').textContent.includes('30일')")
    assert "#youth/20대 여성/month" in page.evaluate("decodeURIComponent(location.hash)")
    assert not page.errors, page.errors


def test_diffusion_tab(page, site):
    page.goto(site + "#diffusion")
    wait_rows(page, "#dif-now .dif")
    wait_rows(page, "#dif-cases .dif", 7)
    assert page.locator("#dif-now .dif svg").count() >= 6
    assert page.locator("#dif-acc").inner_text().strip()
    assert not page.errors, page.errors


def test_country_tab_periods_and_detail(page, site):
    page.goto(site + "#country/KR/live")
    wait_rows(page, "#rank li[data-i]", 10)
    assert page.locator("#regions [data-code]").count() == 3
    page.click("#rank li[data-i='0']")
    page.wait_for_selector("#detail h3")
    page.click("#cperiod [data-p=week]")
    page.wait_for_function("document.querySelector('#rank-title').textContent.includes('7일')")
    page.click("#regions [data-code='US']")
    page.wait_for_function("REPORT && REPORT.region === 'US'")
    assert not page.errors, page.errors


def test_all_ages_tab(page, site):
    page.goto(site + "#age/20대/week")
    page.wait_for_selector("#heat table")
    heads = page.locator("#heat thead th").all_inner_texts()[1:]
    assert heads == ["10대", "20대", "30대", "40대", "50대", "60대+", "남성", "여성"]
    assert not page.errors, page.errors


def test_no_source_names_leak_and_mobile_fits(page, site):
    for route in ("", "#diffusion", "#country/KR/live", "#age/20대/week"):
        page.goto(site + route)
        page.wait_for_timeout(600)
        html = page.content()
        assert not PROVIDERS.search(html), (route, PROVIDERS.search(html).group(0))
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(site)
    wait_rows(page, "#y-disc li")
    assert page.evaluate("document.documentElement.scrollWidth") <= 391
