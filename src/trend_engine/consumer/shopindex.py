"""한국 쇼핑 클릭 지수: 포털 쇼핑 분석의 분야·키워드 클릭 추이 (키 불필요, 주 단위, 1년치).

'어디에 관심(돈)이 가나'를 나이·성별로 숫자와 추이로 본다.

- 분야 11개를 한 척도로: 한 요청에 분야 3개까지라 기준 분야(패션의류) + 2개씩 5번 묻고, 요청마다 기준 분야의 합으로
  배율을 맞춰 잇는다(`chain`). 업스트림은 요청마다 최댓값을 100 으로 두기 때문이다.
- 그룹(전체 · 나이 · 성별 · 나이×성별)마다 최근 4주 분야 비중(%), 전체 대비 배수, 클릭 4주 변화(직전 4주 대비 %),
  작년 대비(52주 전 같은 4주와의 비중 차이, %p), 52주 주별 비중(%) — `build`, 순수 함수.
  작년 대비를 클릭 양이 아니라 비중으로 보는 까닭: 포털 전체 클릭이 한 해 사이 30% 넘게 줄어 양으로 보면 모든 분야가
  줄어든 것처럼 보인다. 비중은 '돈(관심)이 어디로 옮겨 갔나'만 남긴다. 키워드 추이도 같은 이유로 그 분야 전체 클릭에
  대한 비율로 그린다.
- '클릭 양'이다. 금액도, 그 나이 사람 중 몇 %도 아니다 — 화면 문구도 그렇게 쓴다.
- 끝난 주만 쓴다(덜 찬 주는 값이 낮다). 같은 주 안에선 값이 안 바뀌니 그룹·키워드마다 주 단위로 캐시하고, 한 번 실행에
  그룹 몇 개씩만 받는다 — 비공식 엔드포인트라 차례로·간격을 두고, 막히면 쉰다.
- 소비 키워드의 1년 클릭 추이(`keyword_trends`): 키워드는 분야를 정해 물어야 해서, 키워드가 나온 분야부터 차례로
  5개씩 묻고 빈 결과면 다음 분야로 넘긴다.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx

from ..config import Settings
from ..normalize import norm_key
from ..sources.base import SourceError, TransientError
from ..store import Store
from .trends import lean

CAT_URL = "https://datalab.naver.com/shoppingInsight/getCategoryClickTrend.naver"
KW_URL = "https://datalab.naver.com/shoppingInsight/getKeywordClickTrend.naver"
CAT_REF = "https://datalab.naver.com/shoppingInsight/sCategory.naver"
KW_REF = "https://datalab.naver.com/shoppingInsight/sKeyword.naver"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36"
PACE_SECONDS = 1.0
REST = timedelta(hours=3)  # refused (429 · 5xx): don't ask again for this long
KEEP = timedelta(days=15)  # weekly results: this week's and last week's (the fallback)

CATS: tuple[tuple[str, str], ...] = (
    ("패션의류", "50000000"), ("패션잡화", "50000001"), ("화장품·미용", "50000002"), ("디지털·가전", "50000003"),
    ("가구·인테리어", "50000004"), ("출산·육아", "50000005"), ("식품", "50000006"), ("스포츠·레저", "50000007"),
    ("생활·건강", "50000008"), ("여가·생활편의", "50000009"), ("도서", "50005542"))
CID = dict(CATS)
NAME = {cid: name for name, cid in CATS}
BASE = "패션의류"  # in every request: its total carries the scale from one request to the next
_REST = [n for n, _ in CATS if n != BASE]
REQUESTS = [(BASE, _REST[i], _REST[i + 1]) for i in range(0, len(_REST), 2)]

AGES = (("10대", "10", 10), ("20대", "20", 20), ("30대", "30", 30), ("40대", "40", 40), ("50대", "50", 50),
        ("60대+", "60", 60))
GENDERS = (("여성", "f"), ("남성", "m"))
# (label, age code, gender code, age, gender) — 전체 first: every other group is compared with it
GROUPS: list[tuple[str, str, str, int, str]] = (
    [("전체", "", "", 0, "")] + [(a, ac, "", n, "") for a, ac, n in AGES] + [(g, "", gc, 0, g) for g, gc in GENDERS]
    + [(f"{a} {g}", ac, gc, n, g) for a, ac, n in AGES for g, gc in GENDERS])

WEEKS = 57  # 52 to draw + the same 4 weeks a year earlier
SHOW = 52
RECENT = 4
PER_RUN = 7  # groups fetched per run (5 requests each); the rest wait for the next hourly run
KW_PER_RUN = 12  # keyword requests per run
KW_TOP = 12  # themes that get a yearly line
MIN_WEEKS = 8  # see sold_there()

# 소비 분야 → 쇼핑 분야 (키워드를 물을 순서). 종합 쇼핑은 모든 분야를 이 순서로.
FIELD_CATS = {"패션": ("패션의류", "패션잡화"), "뷰티": ("화장품·미용",), "디지털·가전": ("디지털·가전",),
              "식품": ("식품",), "생활·리빙": ("생활·건강", "가구·인테리어"), "도서": ("도서",)}
ORDER = ("패션의류", "패션잡화", "식품", "화장품·미용", "디지털·가전", "생활·건강", "가구·인테리어", "스포츠·레저",
         "출산·육아", "여가·생활편의", "도서")
BASIS = "포털 쇼핑에서 분야·검색어를 누른 양 · 주 단위 · 금액이 아니에요"


# ---- 순수 함수 ---------------------------------------------------------------------------------
def window(today: date) -> tuple[date, date]:
    """Whole weeks only: they end on the last Sunday at least 2 days ago (the portal posts a day late)."""
    end = today - timedelta(days=2)
    end -= timedelta(days=(end.weekday() + 1) % 7)
    return end - timedelta(weeks=WEEKS) + timedelta(days=1), end


def periods(start: date) -> list[str]:
    return [(start + timedelta(weeks=k)).strftime("%Y%m%d") for k in range(WEEKS)]


def parse(raw: str) -> dict[str, dict[str, float]]:
    """One click-trend response → {category id, or the keyword: {week 'YYYYMMDD': value}}."""
    d = json.loads(raw)
    if "result" not in d:
        raise SourceError(f"click trend: no result ({str(d.get('message') or d)[:80]})")
    return {str(r.get("code") or r.get("title")): {p["period"]: float(p["value"]) for p in r.get("data") or []}
            for r in d["result"]}


def chain(parts: list[dict[str, dict[str, float]]], weeks: list[str]) -> dict[str, list[float]]:
    """Responses that each carry BASE and two more categories → all categories on the first response's scale."""
    out: dict[str, list[float]] = {}
    ref = None
    for p in parts:
        base = sum((p.get(CID[BASE]) or {}).values())
        if base <= 0:
            continue
        ref = ref or base
        k = ref / base
        for cid, s in p.items():
            if cid in NAME and NAME[cid] not in out:
                out[NAME[cid]] = [round(s.get(w, 0.0) * k, 4) for w in weeks]
    return out


def _pct(new: float, old: float) -> int | None:
    return round(100 * (new / old - 1)) if old > 0 else None


def _has_final(word: str) -> bool:
    """Does the last Hangul syllable end in a consonant (받침)? Picks 은/는, 을/를, 이/가."""
    for ch in reversed(word):
        if "가" <= ch <= "힣":
            return (ord(ch) - 0xAC00) % 28 != 0
        if ch.isdigit():
            return ch in "013678"
    return False


def josa(word: str, pair: str) -> str:
    a, b = pair.split("/")
    return word + (a if _has_final(word) else b)


def headline(g: dict[str, Any]) -> str:
    ranked = sorted(g["share"].items(), key=lambda x: -x[1])
    (c1, s1), (c2, s2), (c3, s3) = ranked[:3]
    if g["label"] == "전체":
        return f"쇼핑 클릭의 {s1:.0f}%가 {c1}, 다음은 {c2}({s2:.0f}%) · {c3}({s3:.0f}%)"
    head = f"{josa(g['label'], '은/는')} 쇼핑 클릭의 {s1:.0f}%가 {c1}"
    lv = lean(g)
    if lv and lv[1] >= 1.2:
        return f"{head} · 전체보다 {josa(lv[0], '을/를')} {lv[1]:.1f}배 더 봐요"
    return f"{head} · 분야 비중이 전체와 비슷해요"


def moves(g: dict[str, Any]) -> str:
    ch = [(c, v) for c, v in g["change"].items() if v is not None and g["share"][c] >= 1]
    if not ch:
        return ""
    up, down = max(ch, key=lambda x: x[1]), min(ch, key=lambda x: x[1])
    out = []
    if up[1] > 0:
        out.append(f"최근 4주 가장 늘어난 분야는 {up[0]}(+{up[1]}%)")
    if down[1] < 0:
        out.append(f"가장 줄어든 분야는 {down[0]}({down[1]}%)")
    return ", ".join(out)


def build(by_group: dict[str, dict[str, list[float]]], weeks: list[str]) -> dict[str, Any] | None:
    """Per group: share of the last 4 weeks, lean against 전체, 4-week change, year-on-year, 52-week index."""
    names = [n for n, _ in CATS]
    out = []
    for label, _, _, age, gender in GROUPS:
        s = by_group.get(label)
        if not s or any(n not in s for n in names):
            continue  # one request of five failed: half a picture would mislead
        recent = {c: sum(s[c][-RECENT:]) for c in names}
        total = sum(recent.values())
        if total <= 0:
            continue
        then = {c: sum(s[c][-SHOW - RECENT:-SHOW]) for c in names} if len(weeks) >= SHOW + RECENT else {}
        then_total = sum(then.values())
        week_total = [sum(s[c][i] for c in names) for i in range(len(weeks))][-SHOW:]
        share = {c: round(100 * recent[c] / total, 1) for c in names}
        out.append({
            "label": label, "age": age, "gender": gender, "share": share,
            "change": {c: _pct(recent[c], sum(s[c][-2 * RECENT:-RECENT])) for c in names},
            "yoy": {c: round(share[c] - 100 * then[c] / then_total, 1) if then_total else None for c in names},
            "series": {c: [round(100 * v / t, 1) if t else 0.0 for v, t in zip(s[c][-SHOW:], week_total)] for c in names}})
    if not out or out[0]["label"] != "전체":
        return None
    base = out[0]["share"]
    for g in out:
        g["over"] = {c: round(g["share"][c] / base[c], 2) if base[c] else None for c in names}
        g["headline"], g["moves"] = headline(g), moves(g)
    last = date(int(weeks[-1][:4]), int(weeks[-1][4:6]), int(weeks[-1][6:]))
    return {"cats": names, "weeks": [f"{w[:4]}-{w[4:6]}-{w[6:]}" for w in weeks[-SHOW:]],
            "until": (last + timedelta(days=6)).isoformat(), "basis": BASIS, "groups": out}


def cats_for(fields: list[str]) -> list[str]:
    """Shopping categories to ask about a word, most likely first; [] for non-shopping fields (영화·게임 …)."""
    out = [c for f in fields for c in FIELD_CATS.get(f, ())]
    if "종합 쇼핑" in fields:
        out += ORDER
    return list(dict.fromkeys(out))


def spark(values: list[float], base: list[float] | None = None) -> dict[str, Any] | None:
    """A keyword's year: 52 weeks scaled to its own peak (= 100), and how the last 4 weeks compare.

    With `base` (its category's clicks, same weeks) the line is the keyword's slice of that category, so the portal's
    own shrinking traffic doesn't read as the keyword fading; year-on-year is only given then."""
    if base is not None and len(base) == len(values):
        values = [v / b if b > 0 else 0.0 for v, b in zip(values, base)]
    top = max(values[-SHOW:], default=0)
    if top <= 0:
        return None
    last = sum(values[-RECENT:])
    then = sum(values[-SHOW - RECENT:-SHOW]) if base is not None and len(values) >= SHOW + RECENT else None
    out = {"unit": "week", "series": [round(100 * v / top) for v in values[-SHOW:]],
           "now": round(100 * values[-1] / top), "change": _pct(last, sum(values[-2 * RECENT:-RECENT])), "yoy": None}
    if then is not None and last > 0:
        if then < 0.1 * last:
            out["fresh"] = True  # next to nothing a year ago: a percentage would only shout
        else:
            out["yoy"] = _pct(last, then)
    return out


def sold_there(series: dict[str, float], weeks: list[str]) -> bool:
    """Is the word really sold in this category? Its own category shows it nearly every week; a wrong one shows
    a few stray weeks (크록스 under 생활·건강) or none lately — then the next category is asked."""
    on = [series.get(w, 0.0) > 0 for w in weeks]
    return sum(on) >= 0.6 * len(weeks) or (sum(on) >= MIN_WEEKS and sum(on[-RECENT:]) >= RECENT - 1)


# ---- 수집 -----------------------------------------------------------------------------------------
def _group_key(label: str, end: date) -> str:
    return f"shopindex:v1:{label}:{end.isoformat()}"


def _kw_key(term: str, end: date) -> str:
    return f"shopkw:v1:{norm_key(term)}:{end.isoformat()}"


async def _post(client: httpx.AsyncClient, url: str, form: dict[str, Any], ref: str) -> str:
    r = None
    for attempt in range(2):
        r = await client.post(url, data=form, headers={"User-Agent": UA, "Referer": ref})
        if r.status_code == 200 and r.text.lstrip().startswith("{"):
            await asyncio.sleep(PACE_SECONDS)
            return r.text
        if r.status_code != 429 and r.status_code < 500:
            raise SourceError(f"click trend HTTP {r.status_code}")
        await asyncio.sleep(min(15.0, float(r.headers.get("Retry-After") or 5 * 2 ** attempt)))
    raise TransientError(f"click trend HTTP {r.status_code if r else '?'}")


def _form(start: date, end: date, age: str = "", gender: str = "", **extra: Any) -> dict[str, Any]:
    return {"timeUnit": "week", "startDate": start.isoformat(), "endDate": end.isoformat(), "age": age,
            "gender": gender, "device": "", **extra}


def fixture(settings: Settings, name: str) -> Path:
    return settings.fixtures_dir / "consumer" / name


Base = tuple[list[str], dict[str, list[float]]]  # (weeks, 전체's clicks per category on one scale)


def _offline_index(settings: Settings) -> tuple[dict | None, Base | None]:
    p = fixture(settings, "kr-shopindex.json")
    if not p.exists():
        return None, None
    fx = json.loads(p.read_text(encoding="utf-8"))
    weeks = periods(date.fromisoformat(fx["start"]))
    have = {label: chain([parse(json.dumps(r)) for r in raws], weeks) for label, raws in fx["groups"].items()}
    return build(have, weeks), ((weeks, have["전체"]) if "전체" in have else None)


async def collect(settings: Settings, store: Store, today: date,
                  fetch: bool = True) -> tuple[dict | None, Base | None, list[str]]:
    """This week's index if every group is in, else the newest week that is complete (or at least has 전체).
    Also hands back 전체's raw clicks, which keyword lines are divided by."""
    if settings.offline:
        return (*_offline_index(settings), [])
    errors: list[str] = []
    start, end = window(today)
    weeks = periods(start)
    have = {g[0]: hit for g in GROUPS if (hit := store.cache_get(_group_key(g[0], end), KEEP)) is not None}
    todo = [g for g in GROUPS if g[0] not in have]
    if fetch and todo and store.cache_get("shopindex:rest", REST) is None:
        async with httpx.AsyncClient(timeout=settings.timeout) as client:
            for label, age, gender, _, _ in todo[:PER_RUN]:
                try:
                    parts = [parse(await _post(client, CAT_URL, _form(start, end, age, gender, cid=[CID[c] for c in req]),
                                               CAT_REF)) for req in REQUESTS]
                except Exception as e:  # noqa: BLE001 — one refusal ends the run; the next run picks up
                    errors.append(f"shopindex {label}: {e}")
                    if isinstance(e, TransientError):
                        store.cache_set("shopindex:rest", True)
                    break
                got = chain(parts, weeks)
                if len(got) == len(CATS):
                    store.cache_set(_group_key(label, end), got)
                    have[label] = got
    if len(have) < len(GROUPS):  # the week just turned over: last week's full set beats a half-filled one
        p_start, p_end = start - timedelta(weeks=1), end - timedelta(weeks=1)
        old = {g[0]: hit for g in GROUPS if (hit := store.cache_get(_group_key(g[0], p_end), KEEP)) is not None}
        if len(old) > len(have) or "전체" not in have:
            have, weeks = old, periods(p_start)
    return build(have, weeks), ((weeks, have["전체"]) if "전체" in have else None), errors


def _base_for(base: Base | None, weeks: list[str], cat: str | None) -> list[float] | None:
    return base[1].get(cat) if base and cat and base[0] == weeks else None


def _offline_keywords(settings: Settings, terms: list[str], base: Base | None) -> dict[str, dict]:
    p = fixture(settings, "kr-shopkw-trend.json")
    if not p.exists():
        return {}
    fx = json.loads(p.read_text(encoding="utf-8"))
    weeks = periods(date.fromisoformat(fx["start"]))
    out = {}
    for raw in fx["responses"]:
        cat = NAME.get(raw.get("cid", ""))
        for term, s in parse(json.dumps(raw)).items():
            if term in terms and term not in out and sold_there(s, weeks):
                if sp := spark([s.get(w, 0.0) for w in weeks], _base_for(base, weeks, cat)):
                    out[term] = sp
    return out


async def keyword_trends(settings: Settings, store: Store, today: date, themes: list[dict[str, Any]],
                         base: Base | None = None, fetch: bool = True) -> tuple[dict[str, dict], list[str]]:
    """{theme term: spark} for the top themes sold in a shopping category. Misses are cached too."""
    asks = {t["term"]: cats_for(t["fields"]) for t in themes[:KW_TOP]}
    asks = {term.replace(",", " "): cats for term, cats in asks.items() if cats}
    if settings.offline:
        return _offline_keywords(settings, list(asks), base), []
    start, end = window(today)
    weeks = periods(start)
    out: dict[str, dict] = {}
    pending: dict[str, list[str]] = {}
    for term, cats in asks.items():
        hit = store.cache_get(_kw_key(term, end), KEEP)
        if hit is None:
            pending[term] = cats
        elif hit.get("values") and (sp := spark(hit["values"], _base_for(base, weeks, hit.get("cat")))):
            out[term] = sp
    errors: list[str] = []
    if not (fetch and pending) or store.cache_get("shopindex:rest", REST) is not None:
        return out, errors
    tried: dict[str, set[str]] = {t: set() for t in pending}
    calls = 0
    async with httpx.AsyncClient(timeout=settings.timeout) as client:
        for cat in ORDER:
            batch = [t for t, cats in pending.items() if cat in cats]
            for i in range(0, len(batch), 5):
                if calls >= KW_PER_RUN:
                    break
                chunk = batch[i:i + 5]
                calls += 1
                try:
                    got = parse(await _post(client, KW_URL, _form(start, end, cid=CID[cat], keyword=",".join(chunk)), KW_REF))
                except Exception as e:  # noqa: BLE001
                    errors.append(f"shopkw {cat}: {e}")
                    if isinstance(e, TransientError):
                        store.cache_set("shopindex:rest", True)
                    return out, errors
                for term in chunk:
                    tried[term].add(cat)
                    s = got.get(term) or {}
                    if sold_there(s, weeks):
                        values = [s.get(w, 0.0) for w in weeks]
                        store.cache_set(_kw_key(term, end), {"values": values, "cat": cat})
                        if sp := spark(values, _base_for(base, weeks, cat)):
                            out[term] = sp
                        pending.pop(term)
    for term, cats in pending.items():  # asked in every category it could be in: not a shopping word
        if tried[term] >= set(cats):
            store.cache_set(_kw_key(term, end), {"values": None})
    return out, errors


async def record(settings: Settings, themes: list[dict[str, Any]], groups: list[str] | None = None) -> list[str]:
    """Fixtures for offline mode: raw responses of a few groups, and of the current top themes' keywords."""
    from ..store import utcnow

    today = (utcnow() + timedelta(hours=9)).date()
    start, end = window(today)
    groups = groups or ["전체", "10대", "20대", "30대", "40대", "50대", "60대+", "여성", "남성", "20대 여성", "20대 남성"]
    lines: list[str] = []

    def trim(raw: str) -> dict:
        d = json.loads(raw)
        return {"result": [{"code": r.get("code"), "title": r.get("title"),
                            "data": [{"period": p["period"], "value": round(float(p["value"]), 2)} for p in r.get("data") or []]}
                           for r in d.get("result") or []]}

    async with httpx.AsyncClient(timeout=settings.timeout) as client:
        fx: dict[str, Any] = {"start": start.isoformat(), "groups": {}}
        for label, age, gender, _, _ in GROUPS:
            if label in groups:
                fx["groups"][label] = [trim(await _post(client, CAT_URL, _form(start, end, age, gender,
                                                                                  cid=[CID[c] for c in req]), CAT_REF))
                                       for req in REQUESTS]
        p = fixture(settings, "kr-shopindex.json")
        p.write_text(json.dumps(fx, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        lines.append(f"OK   tests/fixtures/consumer/{p.name} ({p.stat().st_size // 1024}KB)")
        kw: dict[str, Any] = {"start": start.isoformat(), "responses": []}
        asks = {t["term"].replace(",", " "): cats_for(t["fields"]) for t in themes[:KW_TOP]}
        pending = {t: c for t, c in asks.items() if c}
        for cat in ORDER:
            batch = [t for t, cats in pending.items() if cat in cats]
            for i in range(0, len(batch), 5):
                chunk = batch[i:i + 5]
                raw = trim(await _post(client, KW_URL, _form(start, end, cid=CID[cat], keyword=",".join(chunk)), KW_REF))
                kw["responses"].append(raw | {"cid": CID[cat]})
                for term, ser in parse(json.dumps(raw)).items():
                    if term in pending and sold_there(ser, periods(start)):
                        pending.pop(term)
        p = fixture(settings, "kr-shopkw-trend.json")
        p.write_text(json.dumps(kw, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        lines.append(f"OK   tests/fixtures/consumer/{p.name} ({p.stat().st_size // 1024}KB)")
    return lines
