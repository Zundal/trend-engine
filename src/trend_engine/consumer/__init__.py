"""소비 트렌드: 나라 × 분야별 '많이 사는 것' 순위. 키 불필요.

유료 앱 순위(appcharts.py)처럼 점수와 무관한 별도 표라 `Source` 가 아니다 — 이슈 순위에 영향이 없다.

- 목록(Board) 하나 = 업스트림 순위표 하나. fetch 는 원문 그대로, `PARSERS[...]` 는 순수 함수
  (네트워크·시간·난수 금지) → tests/fixtures/consumer/<id>.<ext> 로 오프라인 재현.
- 같은 카드(field + card)에 묶인 목록은 화면에서 한 카드의 세부 칩이 된다 (예: 앱 매출 순위 × 게임·쇼핑…).
- 목록마다 캐시(기본 6시간). 실패하면 3일 안의 마지막 성공 결과를 `stale` 로 보인다 — 실패는 캐시하지 않는다.
- 같은 사이트 요청은 차례로·간격을 두고, 사이트끼리는 동시에 받는다. 사이트가 막히면(429·5xx·접속 실패·
  봇 확인 페이지) 그 사이트의 남은 목록은 지난 결과로 넘기고, 그 사이트는 `BLOCK_REST` 동안 쉰다.
- 공개 뷰(`publish.public_consumer`)는 제공처 이름 없이 분야·카드 제목·기준만 싣는다.

나라별 목록은 common.py(여러 나라 공통) + kr.py · jp.py · usgb.py · twvn.py.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx

from ..config import Settings
from ..engine import make_client
from ..sources.base import SourceError, TransientError, get_text_retry
from ..store import Store, utcnow
from . import common, jp, kr, twvn, usgb
from .base import BROWSER_UA, FIELDS, LIMIT, Board, Fetcher, Item, Parser, clean, compact, item, man, money, ranked

__all__ = ["BOARDS", "FIELDS", "LIMIT", "PARSERS", "Board", "Item", "clean", "collect", "compact", "item", "man",
           "money", "ranked", "boards_for", "doctor", "record"]

PACE_SECONDS = 0.7  # between requests to the same site
STALE_FOR = timedelta(days=3)  # a failed list shows its last good result this long, marked stale
BLOCK_REST = timedelta(hours=3)  # a site that blocked us is not asked again for this long
CACHE_VERSION = "v1"
COUNTRY_MODULES = {"KR": kr, "JP": jp, "US": usgb, "GB": usgb, "TW": twvn, "VN": twvn}

PARSERS: dict[str, Parser] = {}
FETCHERS: dict[str, Fetcher] = {}
TRIMS: dict = {}  # parser -> fixture trimmer (record only): keeps fixtures small and free of echoed caller data
for _m in (common, kr, jp, usgb, twvn):
    PARSERS.update(_m.PARSERS)
    FETCHERS.update(getattr(_m, "FETCHERS", {}))
    TRIMS.update(getattr(_m, "TRIMS", {}))
parse_itunes = common.parse_itunes  # tests and callers that predate the split


def _all_boards() -> list[Board]:
    out: list[Board] = []
    for country, mod in COUNTRY_MODULES.items():
        out += common.boards(country) + mod.boards(country)
    return out


BOARDS: list[Board] = _all_boards()


def boards_for(country: str) -> list[Board]:
    country = country.upper()
    return [b for b in BOARDS if b.country == country]


# ---- collection ------------------------------------------------------------------------
BOT_WALLS = ("validateCaptcha", "api-services-support@amazon.com", "Robot or human", "Just a moment...",
             "cf-browser-verification", "Pardon Our Interruption", "Access Denied")


async def fetch_raw(client: httpx.AsyncClient, b: Board) -> str:
    if b.fetcher:
        return await FETCHERS[b.fetcher](client, b)
    headers = {"User-Agent": BROWSER_UA, **dict(b.headers)}
    if b.method == "POST":
        if b.body:
            r = await client.post(b.url, content=b.body.encode(), headers={"Content-Type": "application/json", **headers})
        else:
            r = await client.post(b.url, data=dict(b.form), headers=headers)
        if r.status_code >= 400:
            raise (TransientError if r.status_code in (403, 429, 500, 502, 503, 504) else SourceError)(
                f"HTTP {r.status_code} from {b.url.split('?')[0]}")
        raw = r.content.decode(b.encoding, errors="replace") if b.encoding else r.text
    else:
        try:
            raw = await get_text_retry(client, b.url, encoding=b.encoding, retries=1, base_wait=3.0, headers=headers)
        except SourceError as e:
            if "HTTP 403" in str(e):  # a bot wall, not a broken list: rest the site
                raise TransientError(str(e)) from e
            raise
    if len(raw) < 20000 and any(w in raw for w in BOT_WALLS):
        raise TransientError(f"bot check page from {b.host}")
    return raw


_fetch = fetch_raw  # patched in tests


def _key(b: Board) -> str:
    return f"consumer:{CACHE_VERSION}:{b.id}"


def _block_key(host: str) -> str:
    return f"consumer-block:{host}"


def fixture_path(settings: Settings, b: Board) -> Path:
    return settings.fixtures_dir / "consumer" / f"{b.id}.{b.ext}"


async def _host_run(client: httpx.AsyncClient, store: Store, boards: list[Board], fresh: dict[str, dict],
                    errors: list[str]) -> None:
    """One site's lists, in order and paced. A block stops the site; other failures skip one list."""
    for i, b in enumerate(boards):
        try:
            items = PARSERS[b.parser](await _fetch(client, b))
            if not items:
                raise SourceError("parsed 0 items (format changed?)")
            fresh[b.id] = {"at": utcnow().isoformat(timespec="seconds"), "items": items}
            store.cache_set(_key(b), fresh[b.id])
        except (TransientError, httpx.TransportError) as e:
            errors.append(f"{b.id}: {str(e)[:160] or type(e).__name__}")
            store.cache_set(_block_key(b.host), {"at": utcnow().isoformat(timespec="seconds"), "by": b.id})
            errors += [f"{x.id}: skipped (site blocked)" for x in boards[i + 1:]]
            return
        except Exception as e:  # noqa: BLE001 — one broken list must not hide the others
            errors.append(f"{b.id}: {str(e)[:160] or type(e).__name__}")
        if i < len(boards) - 1:
            await asyncio.sleep(max(PACE_SECONDS, b.pace) if PACE_SECONDS else 0)


def _offline(settings: Settings, boards: list[Board]) -> dict[str, dict]:
    out = {}
    for b in boards:
        p = fixture_path(settings, b)
        if p.exists():  # not every list has a fixture: one per parser is enough to test it
            out[b.id] = {"at": None, "items": PARSERS[b.parser](p.read_text(encoding="utf-8"))}
    return out


async def collect(settings: Settings, store: Store, country: str) -> dict[str, Any]:
    """Every list of this country: fresh from cache/upstream, or last good result (stale) if it failed."""
    boards = boards_for(country)
    lists: dict[str, dict] = {}
    errors: list[str] = []
    if settings.offline:
        lists = _offline(settings, boards)
    else:
        todo: dict[str, list[Board]] = {}
        for b in boards:
            if hit := store.cache_get(_key(b), b.ttl):
                lists[b.id] = hit
            elif store.cache_get(_block_key(b.host), BLOCK_REST) is not None:
                errors.append(f"{b.id}: resting (site blocked recently)")
            else:
                todo.setdefault(b.host, []).append(b)
        if todo:
            async with make_client(settings) as client:
                await asyncio.gather(*(_host_run(client, store, bs, lists, errors) for bs in todo.values()))
        for b in boards:
            if b.id not in lists and (old := store.cache_get(_key(b), STALE_FOR)):
                lists[b.id] = old | {"stale": True}
    return {"generated_at": utcnow().isoformat(timespec="seconds"), "country": country.upper(),
            "cards": cards(boards, lists), "errors": errors}


def cards(boards: list[Board], lists: dict[str, dict]) -> list[dict[str, Any]]:
    """Group lists into cards in FIELDS order (board order inside a field), dropping empty ones."""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for b in sorted(boards, key=lambda b: FIELDS.index(b.field)):
        got = lists.get(b.id)
        if not got or not got.get("items"):
            continue
        c = out.setdefault((b.field, b.card), {"id": b.id, "field": b.field, "title": b.card, "basis": b.basis,
                                               "period": b.period, "lists": []})
        c["lists"].append({"tab": b.tab, "items": got["items"], "at": got.get("at"), "stale": bool(got.get("stale"))})
    return list(out.values())


# ---- harness ---------------------------------------------------------------------------
async def doctor(settings: Settings, country: str) -> list[dict[str, Any]]:
    """Live check of every list of a country (one request each, paced per site)."""
    rows: list[dict[str, Any]] = []
    async with make_client(settings) as client:
        for b in boards_for(country):
            label = f"소비 {b.card} · {b.tab}"
            try:
                items = PARSERS[b.parser](await fetch_raw(client, b))
                rows.append({"check": b.id, "label": label, "status": "ok" if items else "warn", "count": len(items),
                             "detail": items[0]["name"] if items else "parsed 0 items (format changed?)"})
            except Exception as e:  # noqa: BLE001
                rows.append({"check": b.id, "label": label, "status": "fail",
                             "detail": str(e)[:160] or type(e).__name__})
            await asyncio.sleep(max(PACE_SECONDS, b.pace))
    return rows


async def record(settings: Settings, countries: list[str], only: set[str] | None = None) -> list[str]:
    """Save live responses as fixtures — by default the first list of each (country, parser), which is
    enough to test every parser without committing hundreds of near-identical files."""
    written: list[str] = []
    picked: list[Board] = []
    seen: set[tuple[str, str]] = set()
    for country in countries:
        for b in boards_for(country):
            if only is not None:
                if b.id in only:
                    picked.append(b)
            elif (b.country, b.parser) not in seen:
                seen.add((b.country, b.parser))
                picked.append(b)
    async with make_client(settings) as client:
        for b in picked:
            try:
                raw = await fetch_raw(client, b)
                if b.parser in TRIMS:
                    raw = TRIMS[b.parser](raw)
                if not PARSERS[b.parser](raw):
                    written.append(f"SKIP consumer/{b.id}: parsed 0 items")
                    continue
            except Exception as e:  # noqa: BLE001
                written.append(f"FAIL consumer/{b.id}: {e}")
                continue
            p = fixture_path(settings, b)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(raw, encoding="utf-8")
            written.append(f"OK   tests/fixtures/consumer/{p.name} ({len(raw) // 1024}KB)")
            await asyncio.sleep(PACE_SECONDS)
    return written
