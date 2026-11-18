"""소비 트렌드 공통: 목록(Board) 정의와 순수 파서 도우미. 네트워크·시간·난수 없음."""

from __future__ import annotations

import html
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from urllib.parse import urlsplit

import httpx

BROWSER_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36"
LIMIT = 20  # items kept per list

# 소비 분야: 화면의 칩 순서. 나라마다 있는 분야만 보인다.
FIELDS: tuple[str, ...] = ("종합 쇼핑", "패션", "뷰티", "디지털·가전", "식품", "생활·리빙", "도서", "영화", "음악",
                           "공연", "게임", "앱 결제")

Item = dict[str, Any]
Parser = Callable[[str], list[Item]]


@dataclass(frozen=True)
class Board:
    id: str  # stable: cache key and fixture name (tests/fixtures/consumer/<id>.<ext>)
    country: str  # ISO country of the shoppers ("KR", "US" …)
    field: str  # one of FIELDS
    card: str  # card title shown on the page (no provider names)
    tab: str  # this list's chip inside the card ("전체", "게임" …)
    basis: str  # what the list is ordered by, in plain Korean (no provider names)
    url: str
    parser: str  # key into PARSERS
    ext: str = "json"
    method: str = "GET"
    form: tuple[tuple[str, str], ...] = ()  # POST form fields
    body: str = ""  # POST JSON body (instead of form fields)
    headers: tuple[tuple[str, str], ...] = ()
    encoding: str | None = None  # force a body encoding (old Shift_JIS / Big5 pages)
    ttl: timedelta = timedelta(hours=6)
    period: str = ""  # 집계 기간 ("실시간", "일간", "주간" …)
    fetcher: str = ""  # key into FETCHERS for multi-step requests; "" = one plain request
    pace: float = 0.0  # seconds to wait before the next request to this site, if longer than the default
    kind: str = "item"  # "item" = products/titles, "keyword" = a ranked list of shopping search words
    age: int = 0  # the shoppers' age band this list is cut to (10, 20, 30 …), 0 = everyone
    gender: str = ""  # "여성" / "남성" if the list is cut by gender

    @property
    def host(self) -> str:
        return urlsplit(self.url).netloc


Fetcher = Callable[[httpx.AsyncClient, Board], Awaitable[str]]


def clean(s: str | None) -> str:
    """Tags out, entities decoded, whitespace collapsed."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", s or "")).split())


def short(s: str, n: int = 90) -> str:
    """Shop titles run to 200 characters of keywords: keep the head."""
    return s if len(s) <= n else s[: n - 1].rstrip(" ,|-/") + "…"


def item(rank: int, name: str, by: str | None = None, price: str | None = None, note: str | None = None,
         url: str | None = None) -> Item:
    return {"rank": int(rank), "name": short(clean(name)), "by": clean(by) or None, "price": clean(price) or None,
            "note": clean(note) or None, "url": url if url and url.startswith("https://") else None}


def ranked(rows: list[Item], limit: int = LIMIT) -> list[Item]:
    """Drop nameless rows and duplicates (same name + by), keep upstream order, cap at `limit`.
    Ranks stay as the upstream printed them (a dropped row must not lift the next one)."""
    out: list[Item] = []
    seen: set[tuple[str, str | None]] = set()
    last = 0
    for r in rows:
        k = (r["name"], r["by"])
        if not r["name"] or k in seen or r["rank"] <= last:
            continue
        seen.add(k)
        last = r["rank"]
        out.append(r)
        if len(out) >= limit:
            break
    return out


def num(s: Any) -> float | None:
    """'$1,234.5' / '1,234원' / 1234 -> 1234.5; anything else -> None."""
    if isinstance(s, (int, float)):
        return float(s)
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", str(s or ""))
    return float(m.group(0).replace(",", "")) if m else None


def money(amount: Any, symbol: str, decimals: int = 0, suffix: str = "") -> str | None:
    """1234.5, "$" -> "$1,234.50". None/blank/0 -> None (a missing price is better than a wrong one)."""
    v = num(amount)
    if v is None or v <= 0:
        return None
    return f"{symbol}{v:,.{decimals}f}{suffix}"


def compact(amount: Any, symbol: str = "$") -> str | None:
    """Box-office sized numbers: 19012017 -> "$19.0M", 812345 -> "$812K"."""
    v = num(amount)
    if v is None or v <= 0:
        return None
    if v >= 1e9:
        return f"{symbol}{v / 1e9:.2f}B"
    if v >= 1e6:
        return f"{symbol}{v / 1e6:.1f}M"
    if v >= 1e3:
        return f"{symbol}{v / 1e3:.0f}K"
    return f"{symbol}{v:.0f}"


def man(v: Any, unit: str = "") -> str | None:
    """Korean count: 1234567 -> '123만', 12345 -> '1.2만', 999 -> '999'."""
    n = num(v)
    if n is None or n <= 0:
        return None
    if n >= 1e8:
        return f"{n / 1e8:.1f}억{unit}"
    if n >= 1e5:
        return f"{n / 1e4:,.0f}만{unit}"
    if n >= 1e4:
        return f"{n / 1e4:.1f}만{unit}"
    return f"{n:,.0f}{unit}"


def move(last: Any, now: int) -> str | None:
    """Rank movement vs last period: None/0 = new entry."""
    lw = num(last)
    if not lw:
        return "새로 진입"
    lw = int(lw)
    return "변동 없음" if lw == now else f"지난 {lw}위"


def json_after(raw: str, marker: str) -> Any:
    """First JSON value after `marker` in an HTML page (window.__STATE__ = {...})."""
    i = raw.index(marker)
    j = min(k for k in (raw.find("{", i), raw.find("[", i)) if k >= 0)
    return json.JSONDecoder().raw_decode(raw[j:])[0]


def table_rows(table_html: str) -> list[list[str]]:
    """<tr><td>… cells (raw inner HTML) of a plain table, header rows included."""
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, re.S):
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)
        if cells:
            rows.append(cells)
    return rows


def first(pattern: str, s: str, flags: int = re.S) -> str:
    m = re.search(pattern, s, flags)
    return m.group(1) if m else ""


def lean_html(raw: str) -> str:
    """Fixture trim for server-rendered lists: scripts, styles, icons and comments out, runs of
    whitespace folded. Parsers read markup only, so the parse must come out the same (tested)."""
    raw = re.sub(r"<script\b.*?</script>|<style\b.*?</style>|<svg\b.*?</svg>|<!--.*?-->", "", raw, flags=re.S)
    return re.sub(r"[ \t\r\n]+", " ", raw)
