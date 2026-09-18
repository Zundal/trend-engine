"""Seoul real-time city data (서울 실시간 도시데이터 - 인구): who is where, right now, by age/gender.

Answers "지금 서울 어디에 어떤 연령대가 몰리나". Needs SEOUL_API_KEY; with the public 'sample'
key the API always returns one fixed place, which we flag as sample=True.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from typing import Any
from urllib.parse import quote

import httpx

from .config import Settings
from .store import Store

AGE_KEYS = [("0", "10세 미만"), ("10", "10대"), ("20", "20대"), ("30", "30대"), ("40", "40대"),
            ("50", "50대"), ("60", "60대"), ("70", "70대+")]

# Subset of the 120+ official POI names (AREA_NM). Extend via TREND_ENGINE_SEOUL_PLACES or the API param.
DEFAULT_PLACES = [
    "강남역", "홍대 관광특구", "성수카페거리", "여의도", "잠실 관광특구", "명동 관광특구",
    "이태원 관광특구", "광화문·덕수궁", "서울숲공원", "여의도한강공원", "가로수길",
    "압구정로데오거리", "북촌한옥마을", "동대문 관광특구", "신촌·이대역", "건대입구역",
    "연남동", "뚝섬한강공원", "DDP(동대문디자인플라자)", "고척돔",
]


@dataclass
class Hotspot:
    name: str
    code: str
    congestion: str  # 여유 / 보통 / 약간 붐빔 / 붐빔
    message: str
    population_min: int
    population_max: int
    male: float
    female: float
    ages: dict[str, float]  # label -> %
    resident: float
    observed_at: str
    forecast: list[dict[str, Any]] = field(default_factory=list)
    sample: bool = False
    age_skew: dict[str, float] = field(default_factory=dict)  # label -> %p vs all-hotspot mean
    dominant_group: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _f(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def parse_citydata(raw: str, requested: str | None = None) -> Hotspot | None:
    data = json.loads(raw)
    rows = data.get("SeoulRtd.citydata_ppltn") or []
    if not rows:
        return None
    r = rows[0]
    return Hotspot(
        name=r.get("AREA_NM", ""),
        code=r.get("AREA_CD", ""),
        congestion=r.get("AREA_CONGEST_LVL", ""),
        message=r.get("AREA_CONGEST_MSG", ""),
        population_min=int(_f(r.get("AREA_PPLTN_MIN"))),
        population_max=int(_f(r.get("AREA_PPLTN_MAX"))),
        male=_f(r.get("MALE_PPLTN_RATE")),
        female=_f(r.get("FEMALE_PPLTN_RATE")),
        ages={label: _f(r.get(f"PPLTN_RATE_{k}")) for k, label in AGE_KEYS},
        resident=_f(r.get("RESNT_PPLTN_RATE")),
        observed_at=r.get("PPLTN_TIME", ""),
        forecast=[
            {"time": f.get("FCST_TIME"), "congestion": f.get("FCST_CONGEST_LVL"),
             "min": int(_f(f.get("FCST_PPLTN_MIN"))), "max": int(_f(f.get("FCST_PPLTN_MAX")))}
            for f in (r.get("FCST_PPLTN") or [])
        ],
        sample=bool(requested and r.get("AREA_NM") != requested),
    )


def annotate_skew(spots: list[Hotspot]) -> None:
    """Which age group is over-represented at each place compared to the other hotspots."""
    real = [s for s in spots if not s.sample] or spots
    if not real:
        return
    mean = {label: sum(s.ages[label] for s in real) / len(real) for _, label in AGE_KEYS}
    for s in spots:
        s.age_skew = {label: round(s.ages[label] - mean[label], 1) for _, label in AGE_KEYS}
        label, delta = max(s.age_skew.items(), key=lambda kv: kv[1])
        s.dominant_group = label if delta > 0 else None


class SeoulCity:
    def __init__(self, settings: Settings, store: Store | None = None):
        self.settings, self.store = settings, store

    @property
    def key(self) -> str:
        return self.settings.seoul_api_key or "sample"

    async def hotspots(self, places: list[str] | None = None) -> dict[str, Any]:
        places = places or DEFAULT_PLACES
        if self.settings.offline:
            path = self.settings.fixtures_dir / "seoul_citydata" / "sample.json"
            spot = parse_citydata(path.read_text(encoding="utf-8"))
            spots = [spot] if spot else []
            for s in spots:
                s.sample = True
            annotate_skew(spots)
            return {"places": [s.to_dict() for s in spots], "sample": True, "errors": ["offline fixture"]}

        cache_key = f"seoul:{self.key[:4]}:{','.join(places)}"
        if self.store and (hit := self.store.cache_get(cache_key, timedelta(minutes=10))):
            return hit

        errors: list[str] = []
        sem = asyncio.Semaphore(5)
        # With the public sample key every call returns the same place: one call is enough.
        targets = places if self.settings.seoul_api_key else places[:1]

        async with httpx.AsyncClient(timeout=self.settings.timeout) as client:
            async def one(place: str) -> Hotspot | None:
                url = f"http://openapi.seoul.go.kr:8088/{self.key}/json/citydata_ppltn/1/5/{quote(place)}"
                async with sem:
                    try:
                        resp = await client.get(url)
                        spot = parse_citydata(resp.text, place)
                        if spot is None:
                            errors.append(f"{place}: no data ({resp.text[:80]})")
                        return spot
                    except Exception as e:  # noqa: BLE001
                        errors.append(f"{place}: {e}")
                        return None

            spots = [s for s in await asyncio.gather(*(one(p) for p in targets)) if s]
        annotate_skew(spots)
        result = {
            "places": [s.to_dict() for s in spots],
            "sample": not self.settings.seoul_api_key,
            "errors": errors,
        }
        if self.store:
            self.store.cache_set(cache_key, result)
        return result
