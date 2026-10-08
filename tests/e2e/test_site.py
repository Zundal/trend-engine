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
# Source *identifiers* must never reach the page. Brand words inside content are fine — an app named
# "Google Chrome" or a headline mentioning 네이버페이 is data, not a label saying where data came from.
PROVIDERS = re.compile(r"google_trends|google_news|signal[._]bz|apple_charts|wikipedia\.org|youtube\.com|datalab|source_status|publisher", re.I)


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
        # The page asks for a web font; answer locally so the browser test never needs the network.
        pg.route(re.compile(r"^https://fonts\.(googleapis|gstatic)\.com/"),
                 lambda route: route.fulfill(status=200, content_type="text/css", body=""))
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
    wait_rows(page, "#y-disc li[data-cat]")
    assert page.locator(".tab[aria-current=page] b").inner_text() == "10·20대"
    assert "KST 업데이트" in page.locator("#gen").inner_text()  # static build stamps one time for every tab
    assert page.locator("#ygroups [data-g]").count() == 6
    # the lead card: the top keyword, then every measured row with its multiple
    top = page.locator("#y-top .top1-k").inner_text().strip()
    assert top and top == page.locator("#y-disc li[data-cat] .k b").first.inner_text().strip()
    assert page.locator("#y-disc li[data-cat] .x").first.inner_text().endswith("×")
    assert page.locator("#y-vs > div").count() == 3  # 10대만 / 둘 다 / 20대만
    page.click("#ygroups [data-g='20대 여성']")
    assert "20대 여성" in page.locator("#y-title").inner_text()
    page.click("#yperiod [data-p=month]")
    page.wait_for_function("document.querySelector('#y-title2').textContent.includes('30일')")
    assert "#youth/20대 여성/month" in page.evaluate("decodeURIComponent(location.hash)")
    assert not page.errors, page.errors


def test_diffusion_tab(page, site):
    page.goto(site + "#diffusion")
    wait_rows(page, "#dif-now .dif")
    assert page.locator("#d-stages .stage").count() == 3  # 확산 대기 / 확산 중 / 윗세대 상승
    assert page.locator("#d-others b").all_inner_texts() == ["전 연령 동시", "상시 관심", "지나감"]
    # a keyword is always opened in the age x week heatmap: one row per age + the date axis
    assert page.locator("#det-h").inner_text().strip()
    assert page.locator("#d-detail .hrow:not(.haxis)").count() == 6
    assert page.locator("#dif-now .dif svg").count() >= 6
    assert page.locator("#dif-acc").inner_text().strip()
    # past cases open in the same heatmap
    wait_rows(page, "#dif-cases [data-case]", 7)
    case = page.locator("#dif-cases [data-case]").first
    name = case.inner_text().strip()
    case.click()
    assert name in page.locator("#det-h").inner_text()
    assert "과거 사례" in page.locator("#d-detail .det-h").inner_text()
    assert case.get_attribute("aria-pressed") == "true"
    # ...and a tracked keyword takes it back
    row = page.locator("#dif-now .dif-k").first
    row.click()
    assert row.inner_text().strip() in page.locator("#det-h").inner_text()
    assert not page.errors, page.errors


def test_country_tab_periods_and_detail(page, site):
    page.goto(site + "#country/KR/live")
    wait_rows(page, "#rank li[data-i]", 10)
    assert page.locator("#regions [data-code]").count() == 3
    page.wait_for_selector("#detail h2")  # the first row is open without a click
    first = page.locator("#detail h2").inner_text()
    page.click("#rank li[data-i='1']")
    page.wait_for_function("t => document.querySelector('#detail h2').textContent !== t", arg=first)
    assert page.locator("#rank li[data-i='1'] .row").get_attribute("aria-pressed") == "true"
    page.click("#cperiod [data-p=week]")
    page.wait_for_function("document.querySelector('#rank-title').textContent.includes('7일')")
    page.click("#regions [data-code='US']")
    page.wait_for_function("REPORT && REPORT.region === 'US'")
    # 이전 상세의 history 요청이 늦게 끝나도 콘솔 에러가 없어야 함
    page.wait_for_timeout(800)
    assert not page.errors, page.errors


def test_all_ages_tab(page, site):
    page.goto(site + "#age/20대/week")
    page.wait_for_selector("#heat table")
    heads = page.locator("#heat thead th").all_inner_texts()[1:]
    assert heads == ["10대", "20대", "30대", "40대", "50대", "60대+", "남성", "여성"]
    # a column header picks the group the cards below describe
    assert "20대" in page.locator("#g-title").inner_text()
    page.click("#heat thead [data-g='50대']")
    assert "50대" in page.locator("#g-title").inner_text() and "50대" in page.locator("#g-title2").inner_text()
    assert page.locator("#heat tbody tr").first.locator("td.on").count() == 1
    assert "#age/50대/week" in page.evaluate("decodeURIComponent(location.hash)")
    assert not page.errors, page.errors


def test_no_source_names_leak_and_mobile_fits(page, site):
    for route in ("", "#diffusion", "#country/KR/live", "#age/20대/week"):
        page.goto(site + route)
        page.wait_for_timeout(600)
        html = page.content()
        assert not PROVIDERS.search(html), (route, PROVIDERS.search(html).group(0))
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(site)
    wait_rows(page, "#y-disc li[data-cat]")
    assert page.evaluate("document.documentElement.scrollWidth") <= 391
    for route, ready in (("#diffusion", "#dif-now .dif"), ("#country/KR/live", "#rank li[data-i]"), ("#age/20대/week", "#heat table")):
        page.goto(site + route)
        page.wait_for_selector(ready)
        page.wait_for_timeout(300)
        assert page.evaluate("document.documentElement.scrollWidth") <= 391, route


def test_categories_overview_and_filters(page, site):
    """분야 칩/타일 필터 — 세그먼트·분야 개수가 바뀌어도 동적으로 고른다."""
    page.goto(site + "#youth/20대/now")
    wait_rows(page, "#y-cats .ctile")
    chip_sel = '#y-cchips .cchip[data-c]:not([data-c=""])'
    cat = None
    for btn in page.locator("#ygroups [data-g]").all():
        btn.click()
        page.wait_for_timeout(250)
        if page.locator(chip_sel).count() >= 1:
            chip = page.locator(chip_sel).first
            cat = chip.get_attribute("data-c")
            chip.click()
            break
    if not cat:
        tile = page.locator("#y-cats .ctile").first
        cat = tile.get_attribute("data-c")
        tile.click()
    tags = page.locator("#y-disc li[data-cat], #y-issues li[data-cat]").evaluate_all("els => els.map(e => e.dataset.cat)")
    assert cat and tags and set(tags) == {cat}, (cat, tags)

    page.goto(site + "#country/KR/live")
    page.wait_for_function(
        'document.querySelectorAll(\'#c-cchips .cchip[data-c]:not([data-c=""])\').length >= 1',
        timeout=15000,
    )
    chip = page.locator('#c-cchips .cchip[data-c]:not([data-c=""])').first
    chosen = chip.get_attribute("data-c")
    chip.click()
    row_tags = page.locator("#rank .rcat").all_inner_texts()
    assert row_tags and set(row_tags) == {chosen}
    assert len(row_tags) == page.locator("#rank li[data-i]").count()
    assert not page.errors, page.errors


def test_country_ranking_shows_themes(page, site):
    page.goto(site + "#country/KR/live")
    wait_rows(page, "#rank li[data-i]", 10)
    labels = page.locator("#rank .label").all_inner_texts()
    assert labels and all(l.strip() for l in labels)
    # A row opens *its own* story. Themes merge clusters, so a row's position is not a cluster index —
    # the last row is where the two lists have drifted furthest apart.
    for i in (0, len(labels) - 1):
        page.click(f"#rank li[data-i='{i}']")
        page.wait_for_function("t => document.querySelector('#detail h2')?.textContent === t", arg=labels[i].strip())
    assert not page.errors, page.errors


def test_country_detail_says_who_searches_more_and_side_lists(page, site):
    page.goto(site + "#country/KR/live")
    # age/gender interest is Korean search data: measured for the top issues, shown inside the open story
    page.wait_for_selector("#aff .affrow")
    assert page.locator("#aff .affrow span:first-child").all_inner_texts() == ["10대", "20대", "30대", "40대", "50대", "60대+", "남성", "여성"]
    assert "샘플 데이터" in page.locator("#aff").inner_text()  # offline numbers are synthetic and say so
    assert page.locator("#card-apps:not([hidden]) #apps li").count() >= 1
    assert page.locator("#news li").count() >= 1
    page.click("#regions [data-code='US']")
    page.wait_for_function("REPORT && REPORT.region === 'US'")
    page.wait_for_selector("#detail h2")
    page.wait_for_timeout(500)
    assert page.locator("#aff .affrow").count() == 0  # no Korean age data for other countries
    assert not page.errors, page.errors


def test_alerts_card_and_feed(page, site):
    import urllib.request
    page.goto(site + "#diffusion")
    page.wait_for_selector("#dif-now .dif")
    page.wait_for_timeout(800)
    assert "RSS" in page.locator("#feed-link").inner_text() and page.locator("#feed-link").get_attribute("href") == "feed.xml"
    assert page.locator("#d-flash-t").inner_text().strip()  # a stage change, or a line saying there was none
    card = page.locator("#alert-card")
    if not card.is_hidden():  # offline fixtures may produce no alerts on a first run
        assert page.locator("#alerts li").count() > 0
    feed = urllib.request.urlopen(site + "feed.xml").read().decode()
    assert feed.startswith("<?xml") and "<rss" in feed
    assert not page.errors, page.errors


def test_youth_matrix_and_trend(page, site):
    page.goto(site + "#youth/20대/now")
    page.wait_for_selector("#y-matrix tbody tr td.cat")
    heads = page.locator("#y-matrix thead th").all_inner_texts()
    assert heads[1:] == ["10대 여성", "10대 남성", "20대 여성", "20대 남성"]
    assert page.locator("#y-matrix td.cat").count() >= 3
    assert page.locator("#y-trend").inner_text().strip()  # chart or "기록이 쌓이면" note
    assert not page.errors, page.errors


def test_attention_card_shows_each_country_against_its_own_normal(page, site):
    page.goto(site + "#country/KR/live")
    page.wait_for_selector("#card-att:not([hidden]) .attrow b")
    kr = page.locator("#att").inner_text()
    assert "상위 10개" in kr and "평소" in kr
    page.click("#regions [data-code='JP']")
    page.wait_for_function("ATT.JP !== undefined")
    page.wait_for_function("document.querySelector('#att').innerText !== " + repr(kr).replace("'", '"'))
    assert not page.errors, page.errors


def test_shape_card_labels_how_each_riser_got_its_attention(page, site):
    page.goto(site + "#country/KR/live")
    page.wait_for_selector("#card-shape:not([hidden]) #shape li")
    labels = page.locator("#shape li .st").all_inner_texts()
    assert labels and set(labels) <= {"예고형", "하루형", "대칭형", "여운형"}
    assert "정점" in page.locator("#shape li").first.inner_text()
    assert not page.errors, page.errors


def test_transfer_kernel_card_breaks_a_handover_into_lag_strength_and_same_week(page, site):
    page.goto(site + "#diffusion")
    page.wait_for_selector("#transfer-card:not([hidden]) .xt tbody tr")
    heads = page.locator("#transfer .xt thead tr").nth(1).all_inner_texts()[0]
    assert "시차" in heads and "전달" in heads and "같은 주" in heads
    first = page.locator("#transfer .xt tbody tr").first.inner_text()
    assert "20대 →" in first and "주" in first
    assert not page.errors, page.errors


def test_country_flow_card_reads_from_where_a_topic_started(page, site):
    page.goto(site + "#country/KR/live")
    page.wait_for_selector("#card-flow:not([hidden]) #flow li")
    text = page.locator("#flow").inner_text()
    assert "먼저 뜬 주제는" in text and "주 뒤" in text
    assert "처음 등장한 나라" in page.locator("#flow-note").inner_text()
    assert not page.errors, page.errors
