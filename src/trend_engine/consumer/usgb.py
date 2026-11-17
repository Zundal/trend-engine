"""미국·영국 소비 목록: 박스오피스, 서적 판매 부수, 음반·영상물 판매 차트, 쇼핑몰 분야별 베스트셀러.

조사(2026-11-18): 영미 대형 서점·유통(Waterstones·Barnes & Noble·Walmart·Target·Best Buy·Argos·Boots·Currys·
eBay·Etsy)은 봇 차단으로 막혀 있다. 쇼핑 분야는 쇼핑몰 베스트셀러 하나뿐이고 데이터센터 IP 를 자주 막아서,
12시간 캐시 + 막히면 사이트 휴식(`BLOCK_REST`) + 지난 결과로 버틴다.
"""

from __future__ import annotations

import io
import re
import zipfile
from datetime import timedelta
from xml.etree import ElementTree as ET

import httpx

from ..sources.base import SourceError, get_text_retry
from .base import BROWSER_UA, Board, Item, clean, compact, first, item, lean_html, move, num, ranked, table_rows


# ---- 박스오피스 (미국: 주말·일간) -----------------------------------------------------------
def parse_numbers(raw: str) -> list[Item]:
    """Chart table: rank from row order (the page prints '-' past ~10), gross / total / days from the header."""
    table = first(r'<table class="chart-desktop">(.*?)</table>', raw)
    rows = table_rows(table)
    head = [clean(h).lower() for h in rows[0]]
    col = {h: i for i, h in enumerate(head)}
    daily = "daily change" in col
    out = []
    for rank, r in enumerate(rows[1:], 1):
        if len(r) < len(head):
            continue
        title = r[col["title"]]
        prev = clean(r[col["prev"]]) if "prev" in col else ""
        days = clean(r[col["days in release"]]) if "days in release" in col else ""
        parts = [f"{'하루' if daily else '주말'} {compact(clean(r[col['gross']]))}",
                 f"누적 {compact(clean(r[col['total gross']]))}" if "total gross" in col else "",
                 "새 개봉" if prev == "(new)" else (move(prev.strip("()"), rank) if prev.strip("()").isdigit() else ""),
                 f"{days}일째" if days.isdigit() and prev != "(new)" else ""]
        href = first(r'href="(/movie/[^"]+)"', title)
        out.append(item(rank, title, None, None, " · ".join(p for p in parts if p),
                        f"https://www.the-numbers.com{href}" if href else None))
    return ranked(out)


# ---- 서적 판매 부수 (미국 주간) -------------------------------------------------------------
def parse_pw(raw: str) -> list[Item]:
    out = []
    for chunk in re.split(r"<!-- \d+ --><tr>", raw)[1:]:
        rank = num(clean(first(r'class="nielsen-rank"[^>]*>(.*?)</td>', chunk)))
        title = first(r'class="nielsen-booktitle">(.*?)</div>', chunk)
        author = first(r'class="nielsen-booktitle">.*?</div>\s*<div>(.*?)</div>', chunk)
        author = re.sub(r",\s*(Author|Illustrator|Editor)\b.*$", "", clean(author))
        pub = clean(first(r'class="nielsen-isbn">(.*?)<br', chunk))
        price = first(r"(\$[\d,.]+)", pub) or None
        units = clean(first(r"UNITS SOLD:\s*<strong>(.*?)</strong>", chunk))
        last = clean(first(r"LAST WEEK:\s*<strong>(.*?)</strong>", chunk))
        if not rank:
            continue
        note = " · ".join(x for x in (f"주간 {units}부" if units else "", move(last if last.isdigit() else 0, int(rank))) if x)
        out.append(item(int(rank), title, author, price, note))
    return ranked(out)


# ---- 영국 차트 (앨범·싱글 판매, 영상물 판매·대여) ----------------------------------------------
def parse_official(raw: str) -> list[Item]:
    out = []
    for chunk in re.split(r'<span class="sr-only">Number </span>', raw)[1:]:
        rank = num(first(r"<strong>(\d+)</strong>", chunk))
        a = re.search(r'<a href="([^"]+)" class="chart-name[^"]*">(.*?)</a>', chunk, re.S)
        if not rank or not a:
            continue
        name = re.sub(r'<span class="movement-icon[^"]*"[^>]*>.*?</span>', "", a.group(2), flags=re.S)
        artist = first(r'class="chart-artist[^"]*"[^>]*>(.*?)</a>', chunk)
        lw = clean(first(r"LW:\s*<span[^>]*>(.*?)</span>", chunk))
        weeks = clean(first(r"Weeks:\s*<span[^>]*>(.*?)</span>", chunk))
        note = "새로 진입" if lw.lower() in ("new", "re") or not lw else move(lw, int(rank))
        if weeks.isdigit() and int(weeks) > 1:
            note += f" · {weeks}주째"
        href = a.group(1)
        out.append(item(int(rank), name, clean(artist).title() if clean(artist).isupper() else artist, None, note,
                        f"https://www.officialcharts.com{href}" if href.startswith("/") else href))
    return ranked(out)


# ---- 영국 박스오피스 (주말, 공공기관 주간 보고서 · 약 10일 늦음) ---------------------------------
ODS = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
TEXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"


def _ods_rows(xml: str) -> list[list[str]]:
    root = ET.fromstring(xml)
    rows = []
    for tr in root.iter(f"{ODS}table-row"):
        cells: list[str] = []
        for td in tr:
            if td.tag not in (f"{ODS}table-cell", f"{ODS}covered-table-cell"):
                continue
            rep = min(int(td.get(f"{ODS}number-columns-repeated", "1")), 12)
            text = " ".join("".join(p.itertext()).strip() for p in td.iter(f"{TEXT}p")).strip()
            cells += [text] * rep
        rows.append(cells[:12])
    return rows


def parse_bfi(raw: str) -> list[Item]:
    rows = _ods_rows(raw)
    start = next(i for i, r in enumerate(rows) if r[:2] == ["Rank", "Film"])
    head = rows[start]
    col = {h.lower(): i for i, h in enumerate(head) if h}
    out = []
    for r in rows[start + 1:]:
        rank = num(r[0]) if r else None
        if not rank or not r[1]:
            break  # top table ends at the first row without a rank (next section starts)
        cell = lambda k: r[col[k]] if k in col and col[k] < len(r) else ""  # noqa: E731
        weeks = cell("weeks on release")
        parts = [f"주말 {compact(cell('weekend gross'), '£')}", f"누적 {compact(cell('total gross to date'), '£')}",
                 "새 개봉" if weeks == "1" else (f"{weeks}주째" if weeks.isdigit() else "")]
        out.append(item(int(rank), r[1], cell("distributor"), None, " · ".join(p for p in parts if "None" not in p and p)))
    return ranked(out)


BFI_PAGE = "https://www.bfi.org.uk/industry-data-insights/weekend-box-office-figures"


async def fetch_bfi(client: httpx.AsyncClient, b: Board) -> str:
    """The figures page lists weekly spreadsheets newest first: take the first, return its content.xml."""
    page = await get_text_retry(client, BFI_PAGE, retries=1, base_wait=3.0, headers={"User-Agent": BROWSER_UA})
    link = first(r'(https://core-cms\.bfi\.org\.uk/media/\d+/download)', page)
    if not link:
        raise SourceError("no spreadsheet link on the figures page")
    r = await client.get(link, headers={"User-Agent": BROWSER_UA})
    if r.status_code >= 400:
        raise SourceError(f"HTTP {r.status_code} from spreadsheet")
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        return z.read("content.xml").decode("utf-8")


# ---- 쇼핑몰 분야별 베스트셀러 ----------------------------------------------------------------
def _amazon(symbol: str, host: str):
    def parse(raw: str) -> list[Item]:
        out = []
        for chunk in raw.split('id="p13n-asin-index-')[1:]:
            rank = num(first(r'zg-bdg-text">#(\d+)', chunk))
            asin = first(r'data-asin="([A-Z0-9]{10})"', chunk)
            title = first(r'line-clamp[^"]*">(.*?)</div>', chunk)
            by = first(r'a-link-child"[^>]*>\s*<div[^>]*>(.*?)</div>', chunk) or first(
                r'<span class="a-size-small a-color-base">(.*?)</span>', chunk)
            price = clean(first(r'p13n-sc-price[^"]*">(.*?)</span>', chunk))
            rating = re.search(r'aria-label="([\d.]+) out of 5 stars, ([\d,]+) ratings"', chunk)
            note = f"★{rating.group(1)} · 리뷰 {rating.group(2)}" if rating else None
            if rank:
                out.append(item(int(rank), title, by, price if price.startswith(symbol) else None, note,
                                f"https://{host}/dp/{asin}" if asin else None))
        return ranked(out)
    return parse


def trim_amazon(raw: str) -> str:
    """Fixture trim: the grid only (the page around it is ~400KB of scripts)."""
    i = raw.find('id="gridItemRoot"')
    j = raw.rfind('id="p13n-asin-index-')
    end = raw.find("</li>", j) if j >= 0 else -1
    return raw[max(i - 200, 0): end + 5] if i >= 0 and end > 0 else raw


SHOP_US: tuple[tuple[str, str, str], ...] = (
    # (field, tab, category path)
    ("종합 쇼핑", "장난감", "toys-and-games"), ("종합 쇼핑", "스포츠·아웃도어", "sporting-goods"),
    ("종합 쇼핑", "건강·생활용품", "hpc"), ("종합 쇼핑", "반려동물", "pet-supplies"), ("종합 쇼핑", "유아", "baby-products"),
    ("종합 쇼핑", "사무용품", "office-products"), ("종합 쇼핑", "자동차용품", "automotive"),
    ("패션", "패션 전체", "fashion"), ("뷰티", "뷰티 전체", "beauty"),
    ("디지털·가전", "전자기기", "electronics"), ("디지털·가전", "컴퓨터", "pc"), ("디지털·가전", "가전", "appliances"),
    ("디지털·가전", "휴대폰·액세서리", "wireless"), ("디지털·가전", "카메라", "photo"),
    ("식품", "식품 전체", "grocery"), ("생활·리빙", "주방", "kitchen"), ("생활·리빙", "홈·인테리어", "home-garden"),
    ("생활·리빙", "공구·DIY", "hi"), ("도서", "종이책", "books"), ("도서", "전자책", "digital-text"),
    ("게임", "비디오 게임", "videogames"),
)
SHOP_GB: tuple[tuple[str, str, str], ...] = (
    ("종합 쇼핑", "장난감", "kids"), ("종합 쇼핑", "스포츠·아웃도어", "sports"), ("종합 쇼핑", "건강·생활용품", "drugstore"),
    ("종합 쇼핑", "반려동물", "pet-supplies"), ("종합 쇼핑", "유아", "baby"), ("종합 쇼핑", "사무용품", "officeproduct"),
    ("종합 쇼핑", "자동차용품", "automotive"),
    ("패션", "패션 전체", "fashion"), ("뷰티", "뷰티 전체", "beauty"),
    ("디지털·가전", "전자기기", "electronics"), ("디지털·가전", "컴퓨터", "computers"), ("디지털·가전", "가전", "appliances"),
    ("식품", "식품 전체", "grocery"), ("생활·리빙", "주방·홈", "kitchen"), ("생활·리빙", "공구·DIY", "diy"),
    ("생활·리빙", "정원", "outdoors"), ("생활·리빙", "조명", "lighting"),
    ("도서", "종이책", "books"), ("도서", "전자책", "digital-text"), ("게임", "비디오 게임", "videogames"),
)
SHOP_CARD = {"도서": "쇼핑몰 도서 베스트셀러", "게임": "쇼핑몰 게임 베스트셀러"}


def _shop_boards(country: str, host: str, cats, cookie: str) -> list[Board]:
    c = country.lower()
    return [Board(id=f"{c}-shop-{path}", country=country, field=fld, card=SHOP_CARD.get(fld, "쇼핑몰 베스트셀러"),
                  tab=tab, basis="대형 온라인 쇼핑몰 분야별 판매 순위 (매시간 갱신)", period="실시간",
                  url=f"https://{host}/gp/bestsellers/{path}/", parser=f"amazon_{c}", ext="html",
                  headers=(("Accept-Language", "en-US,en;q=0.9" if country == "US" else "en-GB,en;q=0.9"),
                           ("Accept", "text/html,application/xhtml+xml"), ("Cookie", cookie)),
                  ttl=timedelta(hours=12))
            for fld, tab, path in cats]


# ---- boards -----------------------------------------------------------------------------
PW_LISTS = (("종합 Top 10", "top100"), ("하드커버 소설", "hardcoverfiction"), ("하드커버 논픽션", "HardcoverNonfiction"),
            ("페이퍼백", "tradepaper"), ("어린이 소설", "kidsfiction"), ("그림책", "kidspicture"))
OC_MUSIC = (("앨범 종합", "albums-chart"), ("앨범 판매", "albums-sales-chart"), ("바이닐 앨범", "vinyl-albums-chart"),
            ("실물 앨범", "physical-albums-chart"), ("사운드트랙", "soundtrack-albums-chart"),
            ("싱글 판매", "singles-sales-chart"))
OC_VIDEO = (("영화", "film-chart"), ("TV 시리즈", "tv-on-video-chart"), ("DVD", "dvd-chart"), ("블루레이", "blu-ray-chart"))


def boards(country: str) -> list[Board]:
    if country == "US":
        box = [Board(id=f"us-boxoffice-{k}", country="US", field="영화", card="박스오피스", tab=tab,
                     basis="극장 매출 순위 (주말 3일·하루)", period="주말·일간",
                     url=f"https://www.the-numbers.com/{k}-box-office-chart", parser="numbers", ext="html")
               for tab, k in (("주말", "weekend"), ("하루", "daily"))]
        books = [Board(id=f"us-books-{k.lower()}", country="US", field="도서", card="베스트셀러 판매 부수", tab=tab,
                       basis="서점 판매 집계(판매 부수) 주간 순위", period="주간",
                       url=f"https://www.publishersweekly.com/pw/nielsen/{k}.html", parser="pw", ext="html",
                       ttl=timedelta(hours=12))
                 for tab, k in PW_LISTS]
        return box + books + _shop_boards("US", "www.amazon.com", SHOP_US, "i18n-prefs=USD; lc-main=en_US")
    if country == "GB":
        box = [Board(id="gb-boxoffice-weekend", country="GB", field="영화", card="박스오피스", tab="주말",
                     basis="극장 매출 순위 (주말 3일, 공공기관 주간 보고서라 약 10일 늦음)", period="주간",
                     url=BFI_PAGE, parser="bfi", ext="xml", fetcher="bfi", ttl=timedelta(hours=24))]
        video = [Board(id=f"gb-video-{slug}", country="GB", field="영화", card="영상물 판매·대여 차트", tab=tab,
                       basis="실물·디지털 구매와 대여를 합친 주간 차트", period="주간",
                       url=f"https://www.officialcharts.com/charts/{slug}/", parser="official", ext="html",
                       ttl=timedelta(hours=12))
                 for tab, slug in OC_VIDEO]
        music = [Board(id=f"gb-music-{slug}", country="GB", field="음악", card="음반 판매 차트", tab=tab,
                       basis="앨범 종합은 스트리밍 환산 포함, 나머지는 판매만", period="주간",
                       url=f"https://www.officialcharts.com/charts/{slug}/", parser="official", ext="html",
                       ttl=timedelta(hours=12))
                 for tab, slug in OC_MUSIC]
        return box + video + music + _shop_boards("GB", "www.amazon.co.uk", SHOP_GB, "i18n-prefs=GBP; lc-acbuk=en_GB")
    return []


PARSERS = {"numbers": parse_numbers, "pw": parse_pw, "official": parse_official, "bfi": parse_bfi,
           "amazon_us": _amazon("$", "www.amazon.com"), "amazon_gb": _amazon("£", "www.amazon.co.uk")}
FETCHERS = {"bfi": fetch_bfi}
TRIMS = {"amazon_us": trim_amazon, "amazon_gb": trim_amazon, "official": lean_html, "numbers": lean_html}
