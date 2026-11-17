"""여러 나라에 같은 모양으로 있는 목록: 앱·영화·음반·도서 판매(애플 공개 RSS), PC 게임 주간 판매·분야별 판매,
콘솔 게임 판매. 나라 코드만 바꿔 같은 파서를 쓴다."""

from __future__ import annotations

import json
import re
from datetime import timedelta
from urllib.parse import quote

from .base import LIMIT, Board, Item, clean, first, item, json_after, money, move, ranked

COUNTRIES = ("KR", "US", "JP", "GB", "TW", "VN")


# ---- 애플 공개 RSS ----------------------------------------------------------------------
def _label(entry: dict, key: str) -> str:
    v = entry.get(key) or {}
    return (v.get("label") or "").strip() if isinstance(v, dict) else ""


def parse_itunes(raw: str) -> list[Item]:
    """앱·영화·음반·도서: 가격은 그 나라 통화 표기 그대로. 무료(받기)는 가격 없음."""
    entries = json.loads(raw)["feed"].get("entry", [])
    rows = []
    for rank, e in enumerate([entries] if isinstance(entries, dict) else entries, 1):
        amount = float(((e.get("im:price") or {}).get("attributes") or {}).get("amount", 0) or 0)
        rent = _label(e, "im:rentalPrice")
        rows.append(item(rank, _label(e, "im:name"), _label(e, "im:artist"),
                         price=_label(e, "im:price") if amount > 0 else None,
                         note=f"대여 {rent}" if rent else None, url=_label(e, "id").replace("?uo=2", "")))
    return ranked(rows)


ITUNES = "https://itunes.apple.com/{c}/rss/{feed}/limit={n}/{genre}json"
# 앱 매출(인앱 결제·구독 포함): 분야 칩. 앱스토어 분류 번호.
GROSSING_GENRES: tuple[tuple[str, str], ...] = (
    ("전체", ""), ("게임", "6014"), ("엔터테인먼트", "6016"), ("소셜 네트워킹", "6005"), ("생산성", "6007"),
    ("사진 및 비디오", "6008"), ("쇼핑", "6024"), ("라이프스타일", "6012"), ("교육", "6017"),
    ("건강 및 피트니스", "6013"), ("음악", "6011"), ("도서", "6018"), ("금융", "6015"), ("음식 및 음료", "6023"),
    ("여행", "6003"),
)
# 나라마다 비어 있는 미디어 목록이 있다 (2026-11-18 확인: 음반은 한국 없음, 전자책·오디오북은 미국·영국·일본만,
# TV 시즌은 미국·영국만). 빈 목록은 카드에서 빠질 뿐이지만 요청을 아끼려고 처음부터 뺀다.
ITUNES_MEDIA: tuple[tuple[str, str, str, str, str, frozenset[str]], ...] = (
    # (feed, field, card, tab, basis, countries)
    ("topmovies", "영화", "디지털 영화 판매", "전체", "디지털 영화 구매·대여 순위", frozenset(COUNTRIES)),
    ("toptvseasons", "영화", "TV 시리즈 판매", "전체", "TV 시즌 구매 순위", frozenset({"US", "GB"})),
    ("topalbums", "음악", "디지털 음반 판매", "전체", "디지털 앨범 구매 순위", frozenset({"US", "JP", "GB", "TW", "VN"})),
    ("toppaidebooks", "도서", "전자책 판매", "유료", "유료 전자책 판매 순위", frozenset({"US", "JP", "GB"})),
    ("topaudiobooks", "도서", "오디오북 판매", "전체", "오디오북 판매 순위", frozenset({"US", "JP", "GB"})),
)


def itunes_boards(country: str) -> list[Board]:
    c = country.lower()
    boards = [Board(id=f"{c}-app-grossing-{genre or 'all'}", country=country, field="앱 결제", card="앱 매출 순위",
                    tab=tab, basis="앱 안 결제·구독까지 합친 매출 순위 (아이폰)", period="실시간",
                    url=ITUNES.format(c=c, feed="topgrossingapplications", n=LIMIT,
                                      genre=f"genre={genre}/" if genre else ""), parser="itunes")
              for tab, genre in GROSSING_GENRES]
    boards += [Board(id=f"{c}-{feed}", country=country, field=fld, card=card, tab=tab, basis=basis, period="실시간",
                     url=ITUNES.format(c=c, feed=feed, n=LIMIT, genre=""), parser="itunes")
               for feed, fld, card, tab, basis, where in ITUNES_MEDIA if country in where]
    return boards


# ---- PC 게임: 주간 판매(나라별) + 분야별 지금 판매 ----------------------------------------------
STEAM_WEEKLY = "https://api.steampowered.com/IStoreTopSellersService/GetWeeklyTopSellers/v1/?input_json={q}"
STEAM_SEARCH = ("https://store.steampowered.com/search/results/?filter=topsellers&cc={cc}&l=english&infinite=1"
                "&start=0&count=25&category1=998{tag}")
STEAM_LANG = {"KR": "koreana", "JP": "japanese", "TW": "tchinese", "VN": "vietnamese"}
STEAM_TAGS: tuple[tuple[str, str], ...] = (
    ("액션", "19"), ("어드벤처", "21"), ("RPG", "122"), ("전략", "9"), ("시뮬레이션", "599"), ("스포츠", "701"),
    ("레이싱", "699"), ("캐주얼", "597"), ("인디", "492"),
)
ADULT_DESCRIPTORS = {3, 4}  # 성인 전용 노출·성적 내용


def parse_steam_weekly(raw: str) -> list[Item]:
    rows = []
    for r in json.loads(raw)["response"].get("ranks", []):
        it = r.get("item") or {}
        if ADULT_DESCRIPTORS & set(it.get("content_descriptorids") or []):
            continue
        info = it.get("basic_info") or {}
        maker = (info.get("publishers") or info.get("developers") or [{}])[0].get("name")
        price = "무료" if it.get("is_free") else (it.get("best_purchase_option") or {}).get("formatted_final_price")
        path = it.get("store_url_path") or (f"app/{r.get('appid')}" if r.get("appid") else "")
        weeks = r.get("consecutive_weeks") or 0
        note = move(r.get("last_week_rank"), r["rank"])
        if weeks >= 2:
            note += f" · {weeks}주째"
        rows.append(item(r["rank"], it.get("name", ""), maker, price, note,
                         f"https://store.steampowered.com/{path}" if path else None))
    return ranked(rows)


def parse_steam_search(raw: str) -> list[Item]:
    body = json.loads(raw).get("results_html", "")
    rows = []
    for rank, chunk in enumerate(re.split(r'(?=<a href="https://store\.steampowered\.com/(?:app|bundle|sub)/)', body)[1:], 1):
        url = first(r'<a href="(https://store\.steampowered\.com/[^"?]+)', chunk)
        price = clean(first(r'class="discount_final_price[^"]*">(.*?)</div>', chunk)) or None
        if price and price.lower().startswith("free"):
            price = "무료"
        rows.append(item(rank, first(r'<span class="title">(.*?)</span>', chunk), None, price,
                         _released(clean(first(r'class="search_released[^"]*">(.*?)</div>', chunk))), url))
    return ranked(rows)


MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                      "dec"), 1)}


def _released(s: str) -> str | None:
    """'3 Jul, 2025' / 'Jul 3, 2025' -> '2025.07 출시'; 'Coming soon' -> '출시 예정'."""
    m = re.search(r"\b([A-Z][a-z]{2})[a-z]*\b.*?(\d{4})", s)
    if m and m.group(1).lower() in MONTHS:
        return f"{m.group(2)}.{MONTHS[m.group(1).lower()]:02d} 출시"
    if re.search(r"(?i)coming soon|to be announced", s):
        return "출시 예정"
    return None


def steam_boards(country: str) -> list[Board]:
    c = country.lower()
    q = json.dumps({"country_code": country, "context": {"language": STEAM_LANG.get(country, "english"),
                                                         "country_code": country},
                    "data_request": {"include_basic_info": True}, "page_start": 0, "page_count": 40},
                   separators=(",", ":"))
    basis = "PC 게임 상점의 이 나라 매출 순위 — 주간은 지난주 대비, 나머지는 지금 판매"
    card = dict(country=country, field="게임", card="PC 게임 판매 순위", basis=basis, parser="steam_search",
                pace=2.0)  # the store search answers 429 to quick bursts
    weekly = [] if country in NO_WEEKLY else [  # the weekly chart is not published for every store country
        Board(id=f"{c}-pcgame-weekly", tab="주간 전체", period="주간", url=STEAM_WEEKLY.format(q=quote(q)),
              **(card | {"parser": "steam_weekly"}))]
    return weekly + [Board(id=f"{c}-pcgame-now", tab="지금 전체", period="실시간", url=STEAM_SEARCH.format(cc=c, tag=""),
                           **card)] + [
        Board(id=f"{c}-pcgame-{tag}", tab=name, period="실시간", url=STEAM_SEARCH.format(cc=c, tag=f"&tags={tag}"),
              ttl=timedelta(hours=24), **card)  # genre ranks move slowly; one search a day per genre
        for name, tag in STEAM_TAGS]


NO_WEEKLY = {"VN"}


# ---- 콘솔 게임 판매 (서버에서 그린 페이지의 상태 JSON) --------------------------------------------
XBOX = "https://www.xbox.com/{loc}/games/browse?orderby=BestSelling"
XBOX_LOCALE = {"KR": "ko-KR", "US": "en-US", "JP": "ja-JP", "GB": "en-GB", "TW": "zh-TW", "VN": "vi-VN"}
CURRENCY = {"KRW": ("", 0, "원"), "USD": ("$", 2, ""), "JPY": ("¥", 0, ""), "GBP": ("£", 2, ""), "TWD": ("NT$", 0, ""),
            "VND": ("", 0, "₫"), "EUR": ("€", 2, "")}


def _price(amount, currency: str) -> str | None:
    sym, dec, suf = CURRENCY.get(currency, ("", 2, f" {currency}"))
    return money(amount, sym, dec, suf)


def parse_xbox(raw: str) -> list[Item]:
    state = json_after(raw, "__PRELOADED_STATE__")
    core = state["core2"]
    channel = next(v for k, v in core["channels"]["channelData"].items() if "BESTSELLING" in k)
    summaries = core["products"]["productSummaries"]
    rows = []
    for rank, p in enumerate(channel["data"]["products"], 1):
        s = summaries.get(p["productId"]) or {}
        prices = ((s.get("specificPrices") or {}).get("purchaseable") or [{}])[0]
        price = prices.get("listPrice")
        currency = prices.get("currency") or ""
        rows.append(item(rank, s.get("title", ""), s.get("publisherName") or s.get("developerName"),
                         _price(price, currency),
                         " · ".join((s.get("categories") or [])[:2]) or None,
                         f"https://www.xbox.com/games/store/x/{p['productId']}"))
    return ranked(rows)


def xbox_board(country: str) -> Board:
    return Board(id=f"{country.lower()}-console-bestselling", country=country, field="게임", card="콘솔 게임 판매",
                 tab="전체", basis="콘솔 게임 상점 판매 순위", period="실시간", url=XBOX.format(loc=XBOX_LOCALE[country]),
                 parser="xbox", ext="html", headers=(("Accept-Language", XBOX_LOCALE[country]),))


def trim_xbox(raw: str) -> str:
    """Fixture trim: keep only the ranking channel + its product summaries (the page echoes the caller's IP)."""
    state = json_after(raw, "__PRELOADED_STATE__")
    core = state["core2"]
    ch = {k: v for k, v in core["channels"]["channelData"].items() if "BESTSELLING" in k}
    ids = [p["productId"] for v in ch.values() for p in v["data"]["products"]]
    keep = ("title", "publisherName", "developerName", "categories", "specificPrices", "productId")
    summ = {i: {k: v for k, v in (core["products"]["productSummaries"].get(i) or {}).items() if k in keep} for i in ids}
    small = {"core2": {"channels": {"channelData": ch}, "products": {"productSummaries": summ}}}
    return f"<script>window.__PRELOADED_STATE__ = {json.dumps(small, ensure_ascii=False)};</script>"


PARSERS = {"itunes": parse_itunes, "steam_weekly": parse_steam_weekly, "steam_search": parse_steam_search,
           "xbox": parse_xbox}
TRIMS = {"xbox": trim_xbox}


def boards(country: str) -> list[Board]:
    return itunes_boards(country) + steam_boards(country) + [xbox_board(country)]
