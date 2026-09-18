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
import json
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Awaitable, Callable

import httpx

from .config import Settings
from .store import Store

# Naver moved new Search Trend keys to NAVER API HUB (NCP) on 2026-07-31. Same request/response body,
# different host + auth headers. Keys issued by the old developer center keep working until 2027-06-30.
ENDPOINTS = {
    "hub": ("https://naverapihub.apigw.ntruss.com/search-trend/v1/search", "X-NCP-APIGW-API-KEY-ID", "X-NCP-APIGW-API-KEY"),
    "legacy": ("https://openapi.naver.com/v1/datalab/search", "X-Naver-Client-Id", "X-Naver-Client-Secret"),
}
BATCH = 4  # + 1 anchor = DataLab's max of 5 groups


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


def parse_segment(name: str) -> Segment:
    """'20대', '여성', '20대 여성', '20대+30대 남성' -> Segment."""
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
        results.append({"title": g["groupName"], "keywords": g["keywords"],
                        "data": [{"period": f"d{i}", "ratio": round(level * rnd.uniform(0.7, 1.3), 3)} for i in range(7)]})
    return {"results": results}


class SegmentProfiler:
    def __init__(self, settings: Settings, store: Store | None = None, anchor: str = "날씨", days: int = 7,
                 poster: Poster | None = None, concurrency: int = 4):
        self.settings, self.store, self.anchor, self.days = settings, store, anchor, days
        self.synthetic = poster is None and settings.offline
        self._poster = poster
        self._sem = asyncio.Semaphore(concurrency)
        self._client: httpx.AsyncClient | None = None

    @property
    def available(self) -> bool:
        return bool(self._poster or self.settings.offline or (self.settings.naver_client_id and self.settings.naver_client_secret))

    async def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        if self._poster:
            return await self._poster(body)
        if self.settings.offline:
            return synthetic_response(body | {"_anchor": self.anchor})
        cache_key = "datalab:" + hashlib.sha1(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if self.store and (hit := self.store.cache_get(cache_key, timedelta(hours=6))):
            return hit
        assert self._client is not None
        url, id_header, secret_header = ENDPOINTS.get(self.settings.naver_api, ENDPOINTS["hub"])
        async with self._sem:
            resp = await self._client.post(
                url,
                json=body,
                headers={id_header: self.settings.naver_client_id, secret_header: self.settings.naver_client_secret},
            )
        if resp.status_code != 200:
            raise RuntimeError(f"DataLab HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        if self.store:
            self.store.cache_set(cache_key, data)
        return data

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

    async def profile(self, keywords: list[str], segments: list[Segment] | None = None) -> SegmentResult:
        segments = segments or DEFAULT_SEGMENTS
        keywords = list(dict.fromkeys(k.strip() for k in keywords if k.strip() and k.strip() != self.anchor))
        end = date.today() - timedelta(days=1)  # DataLab lags ~1 day
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
                (k for k in keywords if affinity[k].get(seg.name) is not None and (rel[ALL.name].get(k) or 0) >= 0.005),
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
            errors=errors,
        )
