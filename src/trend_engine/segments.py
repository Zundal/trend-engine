"""Age / gender segment profiling via Naver DataLab search-trend API.

Why an anchor keyword?
  DataLab normalises every request to its own max (=100) and allows only 5 keyword
  groups per request. To compare 20 trending keywords inside one segment we send
  batches of [anchor + 4 keywords] and express each keyword relative to the anchor:
      rel_s(k) = Σ ratio_s(k) / Σ ratio_s(anchor)
  Then, per segment s:
      share_s(k)    = rel_s(k) / Σ_k rel_s(k)
      affinity_s(k) = share_s(k) / share_all(k) × 100     (100 = average, 150 = 1.5× over-indexed)
  Affinity answers "which of today's trends does this group care about MORE than everyone
  else". It is NOT a headcount share — DataLab never exposes absolute volumes. See docs/SEGMENTS.md.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import html
import json
import random
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Awaitable, Callable

import httpx

from .config import Settings
from .store import Store

log = logging.getLogger(__name__)
# Process-wide record of path failures that were rescued by a fallback (read by export -> health).
FALLBACK_EVENTS: list[str] = []

# Naver moved new Search Trend keys to NAVER API HUB (NCP) on 2026-07-31. Same request/response body,
# different host + auth headers. Keys issued by the old developer center keep working until 2027-06-30.
# "web" = no key: the same public form datalab.naver.com uses (qcHash -> trendResult). Unofficial,
# so it is paced (one request at a time) and cached; switch to "hub" once you have a key.
WEB_BASE = "https://datalab.naver.com"
WEB_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36"
WEB_PACE_SECONDS = 2.5  # gap between calls; Naver answers bursts with HTTP 429
WEB_RETRIES = 4  # on 429: wait Retry-After or 20s, 40s, 80s
ENDPOINTS = {
    "hub": ("https://naverapihub.apigw.ntruss.com/search-trend/v1/search", "X-NCP-APIGW-API-KEY-ID", "X-NCP-APIGW-API-KEY"),
    "legacy": ("https://openapi.naver.com/v1/datalab/search", "X-Naver-Client-Id", "X-Naver-Client-Secret"),
}
BATCH = 4  # + 1 anchor = DataLab's max of 5 groups
# Drop keywords under 0.01% of the anchor's volume: too little data for stable age ratios.
# ('날씨' is huge — '등산' is ~0.05% of it, so this must stay low.)
MIN_RELATIVE = 0.0001


@dataclass(frozen=True)
class Segment:
    name: str
    ages: tuple[str, ...] = ()  # DataLab age codes
    gender: str = ""  # "", "m", "f"

    def body_filters(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.ages:
            out["ages"] = list(self.ages)
        if self.gender:
            out["gender"] = self.gender
        return out


# DataLab age codes: 1:0-12 2:13-18 3:19-24 4:25-29 5:30-34 6:35-39 7:40-44 8:45-49 9:50-54 10:55-59 11:60+
AGE_GROUPS: dict[str, tuple[str, ...]] = {
    "10대": ("2",),
    "20대": ("3", "4"),
    "30대": ("5", "6"),
    "40대": ("7", "8"),
    "50대": ("9", "10"),
    "60대+": ("11",),
}
GENDERS = {"남성": "m", "여성": "f"}
ALL = Segment("전체")
DEFAULT_SEGMENTS = [Segment(n, a) for n, a in AGE_GROUPS.items()] + [Segment(n, gender=g) for n, g in GENDERS.items()]
# 10·20대 focus: gender splits + the comparison baseline "30대 이상" (all ages 30+ in one group).
YOUTH_GROUPS = ["10대", "20대", "10대 여성", "10대 남성", "20대 여성", "20대 남성"]
OLDER = "30대 이상"
OLDER_AGES = ("5", "6", "7", "8", "9", "10", "11")


def parse_segment(name: str) -> Segment:
    """'20대', '여성', '20대 여성', '20대+30대 남성', '30대 이상' -> Segment."""
    if name == OLDER:
        return Segment(OLDER, OLDER_AGES)
    ages: list[str] = []
    gender = ""
    toks = [p for w in name.split() for p in ([w] if w in AGE_GROUPS else [x for x in w.split("+") if x])]
    for tok in toks:
        if tok in AGE_GROUPS:
            ages.extend(AGE_GROUPS[tok])
        elif tok in GENDERS:
            gender = GENDERS[tok]
        else:
            raise ValueError(f"unknown segment token {tok!r}; use {list(AGE_GROUPS) + list(GENDERS)}")
    return Segment(name, tuple(ages), gender)


@dataclass
class SegmentResult:
    keywords: list[str]
    segments: list[str]
    affinity: dict[str, dict[str, float | None]]  # keyword -> segment -> index
    relative: dict[str, dict[str, float | None]]  # keyword -> segment -> % of anchor volume
    top_by_segment: dict[str, list[dict[str, Any]]]
    anchor: str
    period: tuple[str, str]
    synthetic: bool = False  # True in offline mode: numbers are NOT real
    mode: str = ""  # hub / legacy / web / offline
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__ | {"period": list(self.period)}


Poster = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def synthetic_response(body: dict[str, Any]) -> dict[str, Any]:
    """Deterministic fake DataLab response for offline demo/harness. Clearly flagged synthetic."""
    seg = f"{body.get('gender', '')}|{','.join(body.get('ages', []))}"
    results = []
    for g in body["keywordGroups"]:
        seed = int(hashlib.md5(f"{g['groupName']}|{seg}".encode()).hexdigest()[:8], 16)
        rnd = random.Random(seed)
        level = 60 if g["groupName"] == body.get("_anchor") else rnd.uniform(1, 80)
        try:  # real dates so callers that parse periods (diffusion.py) work offline too
            d0, d1 = date.fromisoformat(body["startDate"]), date.fromisoformat(body["endDate"])
            periods = [(d0 + timedelta(days=i)).strftime("%Y%m%d") for i in range(min((d1 - d0).days + 1, 2000))]
        except (KeyError, ValueError):
            periods = [f"d{i}" for i in range(7)]
        results.append({"title": g["groupName"], "keywords": g["keywords"],
                        "data": [{"period": p, "ratio": round(level * rnd.uniform(0.7, 1.3), 3)} for p in periods]})
    return {"results": results}


def parse_web_result(page: str) -> dict[str, Any]:
    """Pull the chart JSON out of trendResult.naver: <div class="graph_data" ...>[{title, data:[{period, value}]}]</div>."""
    m = re.search(r'graph_data"[^>]*>(.*?)</', page, re.S)
    if not m:
        raise RuntimeError("DataLab web: graph_data not found (page format changed?)")
    rows = json.loads(html.unescape(m.group(1)))
    return {"results": [{"title": r["title"], "data": [{"period": d["period"], "ratio": d.get("value", 0)} for d in r.get("data", [])]}
                        for r in rows]}


class SegmentProfiler:
    def __init__(self, settings: Settings, store: Store | None = None, anchor: str = "날씨", days: int = 7,
                 poster: Poster | None = None, concurrency: int = 4):
        self.settings, self.store, self.anchor, self.days = settings, store, anchor, days
        self.synthetic = poster is None and settings.offline
        self._poster = poster
        self._sem = asyncio.Semaphore(1 if settings.naver_mode == "web" else concurrency)
        self._web_sem = asyncio.Semaphore(1)  # the web path is always paced one-at-a-time
        self.used_modes: dict[str, int] = {}  # mode -> successful requests (observability / health)
        self.fallback_errors: list[str] = []
        self._client: httpx.AsyncClient | None = None
        self._web_primed = False

    @property
    def mode(self) -> str:
        return self.settings.naver_mode

    @property
    def available(self) -> bool:
        return True  # "web" mode needs no key

    async def _post_web(self, body: dict[str, Any]) -> dict[str, Any]:
        """Keyless path via the public DataLab web form. Returns the API-shaped response."""
        assert self._client is not None
        form = {
            "qcType": "",
            "queryGroups": "__OUML__".join(f"{g['groupName']}__SZLIG__{','.join(g['keywords'])}" for g in body["keywordGroups"]),
            "startDate": body["startDate"].replace("-", ""),
            "endDate": body["endDate"].replace("-", ""),
            "timeUnit": body.get("timeUnit", "date"),
            "gender": body.get("gender", ""),
            "age": ",".join(body.get("ages", [])),
            "device": "",
        }
        headers = {"User-Agent": WEB_UA, "Referer": f"{WEB_BASE}/keyword/trendSearch.naver", "X-Requested-With": "XMLHttpRequest"}
        async with self._web_sem:
            if not self._web_primed:  # visit the form once per session, like a browser would
                await self._client.get(f"{WEB_BASE}/keyword/trendSearch.naver", headers={"User-Agent": WEB_UA})
                self._web_primed = True
            for attempt in range(WEB_RETRIES + 1):
                r = await self._client.post(f"{WEB_BASE}/qcHash.naver", data=form, headers=headers)
                if r.status_code != 429 or attempt == WEB_RETRIES:
                    break
                wait = float(r.headers.get("Retry-After") or 20 * 2**attempt)
                log.info("DataLab web 429, retrying in %.0fs", wait)
                await asyncio.sleep(wait)
            if r.status_code != 200:
                raise RuntimeError(f"DataLab web qcHash HTTP {r.status_code}")
            info = json.loads(r.text or "{}")
            if not info.get("success"):
                raise RuntimeError(f"DataLab web qcHash failed: {info.get('message') or r.status_code}")
            page = await self._client.get(f"{WEB_BASE}/keyword/trendResult.naver", params={"hashKey": info["hashKey"]},
                                          headers={"User-Agent": WEB_UA})
            await asyncio.sleep(WEB_PACE_SECONDS)
        return parse_web_result(page.text)

    async def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        if self._poster:
            return await self._poster(body)
        if self.settings.offline:
            return synthetic_response(body | {"_anchor": self.anchor})
        cache_key = "datalab:" + hashlib.sha1(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if self.store and (hit := self.store.cache_get(cache_key, timedelta(hours=6))):
            return hit
        assert self._client is not None
        last: Exception | None = None
        for mode in self.settings.naver_modes:
            try:
                data = await (self._post_web(body) if mode == "web" else self._post_api(body, mode))
            except Exception as e:  # noqa: BLE001 — try the next path
                last = e
                self.fallback_errors.append(f"{mode}: {str(e)[:120]}")
                FALLBACK_EVENTS.append(f"{mode}: {str(e)[:120]}")
                log.warning("DataLab %s failed, trying next path: %s", mode, e)
                continue
            self.used_modes[mode] = self.used_modes.get(mode, 0) + 1
            if self.store:
                self.store.cache_set(cache_key, data)
            return data
        raise last or RuntimeError("no DataLab path available")

    async def _post_api(self, body: dict[str, Any], mode: str) -> dict[str, Any]:
        url, id_header, secret_header = ENDPOINTS.get(mode, ENDPOINTS["hub"])
        async with self._sem:
            resp = await self._client.post(
                url,
                json=body,
                headers={id_header: self.settings.naver_client_id, secret_header: self.settings.naver_client_secret},
            )
        if resp.status_code != 200:
            raise RuntimeError(f"DataLab HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    async def _relative(self, keywords: list[str], seg: Segment, start: str, end: str) -> dict[str, float | None]:
        """rel_s(k) for every keyword, via anchor-normalised batches."""
        out: dict[str, float | None] = {}

        async def run(batch: list[str]) -> None:
            groups = [{"groupName": self.anchor, "keywords": [self.anchor]}] + [
                {"groupName": k, "keywords": [k]} for k in batch
            ]
            body = {"startDate": start, "endDate": end, "timeUnit": "date", "keywordGroups": groups} | seg.body_filters()
            data = await self._post(body)
            sums = {r["title"]: sum(float(d.get("ratio", 0)) for d in r.get("data", [])) for r in data.get("results", [])}
            a = sums.get(self.anchor, 0.0)
            for k in batch:
                out[k] = (sums.get(k, 0.0) / a) if a > 0 else None

        await asyncio.gather(*(run(keywords[i : i + BATCH]) for i in range(0, len(keywords), BATCH)))
        return out

    async def profile(self, keywords: list[str], segments: list[Segment] | None = None,
                      end: date | None = None) -> SegmentResult:
        segments = segments or DEFAULT_SEGMENTS
        keywords = list(dict.fromkeys(k.strip() for k in keywords if k.strip() and k.strip() != self.anchor))
        end = end or date.today() - timedelta(days=1)  # DataLab lags ~1 day
        start = end - timedelta(days=self.days - 1)
        s, e = start.isoformat(), end.isoformat()

        errors: list[str] = []
        own_client = self._poster is None and not self.settings.offline
        if own_client:
            self._client = httpx.AsyncClient(timeout=self.settings.timeout)
        try:
            all_segs = [ALL, *segments]
            results = await asyncio.gather(*(self._relative(keywords, seg, s, e) for seg in all_segs), return_exceptions=True)
        finally:
            if own_client and self._client:
                await self._client.aclose()

        rel: dict[str, dict[str, float | None]] = {}
        for seg, res in zip(all_segs, results):
            if isinstance(res, Exception):
                errors.append(f"{seg.name}: {res}")
                res = {}
            rel[seg.name] = res

        def shares(seg_name: str) -> dict[str, float]:
            vals = {k: v for k, v in rel.get(seg_name, {}).items() if v}
            total = sum(vals.values())
            return {k: v / total for k, v in vals.items()} if total else {}

        base = shares(ALL.name)
        affinity: dict[str, dict[str, float | None]] = {k: {} for k in keywords}
        relative: dict[str, dict[str, float | None]] = {k: {} for k in keywords}
        top: dict[str, list[dict[str, Any]]] = {}
        for seg in segments:
            sh = shares(seg.name)
            for k in keywords:
                r = rel.get(seg.name, {}).get(k)
                relative[k][seg.name] = round(r * 100, 2) if r is not None else None
                affinity[k][seg.name] = round(sh[k] / base[k] * 100, 1) if k in sh and base.get(k) else None
            ranked = sorted(
                (k for k in keywords if affinity[k].get(seg.name) is not None and (rel[ALL.name].get(k) or 0) >= MIN_RELATIVE),
                key=lambda k: -(affinity[k][seg.name] or 0),
            )
            top[seg.name] = [{"keyword": k, "affinity": affinity[k][seg.name], "relative": relative[k][seg.name]} for k in ranked[:10]]
        for k in keywords:
            r = rel.get(ALL.name, {}).get(k)
            relative[k][ALL.name] = round(r * 100, 2) if r is not None else None

        return SegmentResult(
            keywords=keywords,
            segments=[seg.name for seg in segments],
            affinity=affinity,
            relative=relative,
            top_by_segment=top,
            anchor=self.anchor,
            period=(s, e),
            synthetic=self.synthetic,
            mode="offline" if self.synthetic else ("test" if self._poster else self.mode),
            errors=errors,
        )
