"""소비 트렌드 읽기 — 순수 함수 (네트워크·시간·난수 없음).

순위표는 '지금 무엇이 팔리나'일 뿐이다. 여기서 '무엇이 변하고, 누가, 어디서'를 읽는다.

- rising   뜨는 것: 새로 진입·급상승한 품목. 업스트림이 적어 준 변동(지난주 대비 등)이 있으면 그것을,
           없으면 우리 스냅샷의 전날 대비를 쓴다 (실시간·일간 목록만 — 주간 목록은 하루 사이 안 변한다).
- themes   소비 키워드: 키워드 순위표 + 여러 순위표의 상품명에 겹쳐 나오는 단어. 한 목록이 몰아서 올리지 못하게
           목록당 3개까지만 세고, 목록 이름과 같은 단어(노트북 목록의 '노트북')는 세지 않는다. 일주일 전 대비 변화.
- segments 세대·성별 차이: 같은 카드의 연령·성별 탭끼리 견준다 (10·20대 탭 vs 30대 이상 탭, 여성 vs 남성).
           '순위에 오른 상품' 비교다 — 그 연령 구매자 비율이 아니다.
- world    나라 간 비교: 앱·게임은 상점 id, 그 밖엔 같은 라틴 문자 이름으로 같은 품목을 잇는다. 나라별 '뜨는 것'의 분야 구성(mix).
- daily · history  하루가 남기는 작은 기록(키워드 점수·분야별 뜨는 것 수) → 날짜별 추이. 기록은 archive 가 보관한다.
- summary  오늘 요약 타일: 도표 위에 놓는 숫자 몇 개.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter, defaultdict
from typing import Any

from ..normalize import norm_key
from .base import FIELDS, LIMIT, Board, Item

GOODS = ("종합 쇼핑", "패션", "뷰티", "디지털·가전", "식품", "생활·리빙")  # 상품명에서 키워드를 캐는 분야
ROLLING = ("실시간", "일간")  # 하루 사이에 바뀌는 목록: 스냅샷 전날 대비가 뜻이 있다

# 상품명에 흔한 판촉·규격 단어: 무엇을 사는지 말해 주지 않는다
STOP = set("""
무료배송 무료 배송 당일발송 당일 발송 오늘출발 빠른배송 정품 국내 국내산 국산 정식 수입 세트 택1 택 증정 사은품 공식 본사 단독 할인 특가
선물 선물용 추천 인기 신상 신상품 최신 최신형 대용량 고급 프리미엄 브랜드 남녀공용 공용 남성 여성 남자 여자 남여 한정 한정판 기획 기획전
구성 신제품 리뉴얼 사이즈 컬러 색상 옵션 선택 모음 전용 정기 이벤트 쿠폰 최대 개입 묶음 박스 봉 팩 개 매 장 종 외 및 용 new best
the and with for of in on to by from at or pack set count piece pieces pcs inch oz ml edition black white size women men womens mens
kids unisex original premium official free plus version series collection gift box bundle sale value
블랙 화이트 그레이 네이비 베이지 아이보리 브라운 차콜 카키 멜란지 핑크 블루 레드 그린 옐로우 퍼플 실버 골드 라이트 다크 리얼
color colors colour grey gray navy beige ivory brown pink blue red green light dark
送料無料 公式 正規品 限定 国内正規品 選べる 対応 セット 免運 官方 公司貨 限定 組 入 件 款
ブラック ホワイト グレー シルバー ネイビー ベージュ ゴールド レッド ブルー ピンク グリーン カラー サイズ タイプ
黑色 白色 灰色 現貨 免運費 特價 熱銷
high soft easy ultra super mini max pro lite air portable rechargeable compatible large small medium heavy duty quality
durable waterproof lightweight adjustable multi design home kitchen includes ideal perfect great latest upgraded
year years old adult adults baby boys girls toddler toddlers day days hour hours long short full extra power
cotton stainless steel natural fresh classic style use non count fl one two three four new 2nd 3rd gen generation
amazon basics essentials brand pack packs refill refills case cases cover cable cables
系列 任選 入組 頂級 經典 智慧 智能 科技 休閒 超級 專屬 禮盒 組合 加大 升級 款式 新款 多款 多色 原廠 保固 台灣 一入 二入
モデル インチ 搭載 用 対応 シリーズ キット 価格 プラス シングル セミダブル ダブル
built proof leak clear compact quick fast plastic free assorted mixed double single mens' women's star
""".split())

KANA_HAN = re.compile(r"[぀-ヿ㐀-鿿豈-﫿]")
KATAKANA_RUN = re.compile(r"[\u30a1-\u30fa\u30fc]{2,}")
HAN_RUN = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]{2,}")
BRACKETS = re.compile(r"\[[^\]]*\]|【[^】]*】|\([^)]*\)|（[^）]*）|〔[^〕]*〕|<[^>]*>")


# ---- identity -------------------------------------------------------------------------------
_IDS = ((re.compile(r"steampowered\.com/(?:app|bundle|sub)/(\d+)"), "pc"), (re.compile(r"apple\.com/.*?/id(\d+)"), "ios"),
        (re.compile(r"xbox\.com/games/store/x/(\w+)"), "console"))


def ikey(it: Item) -> str:
    """Same thing in another list or country: store id for apps/games, else the normalised name."""
    url = it.get("url") or ""
    for pat, tag in _IDS:
        if m := pat.search(url):
            return f"{tag}:{m.group(1)}"
    return norm_key(it["name"])[:48]


def _world_key_ok(k: str) -> bool:
    return ":" in k or (k.isascii() and len(k) >= 6 and any(c.isalpha() for c in k))


# ---- 뜨는 것 -----------------------------------------------------------------------------------
def upstream_move(it: Item) -> tuple[str, int] | None:
    """Movement the upstream printed (parsers write it in one vocabulary): ('new', 0) | ('up', steps)."""
    note = it.get("note") or ""
    if re.search(r"새로 진입|새 개봉|새로 출시", note):
        return ("new", 0)
    if m := re.search(r"(\d+)계단 상승", note):
        return ("up", int(m.group(1)))
    if (m := re.search(r"지난 (\d+)위", note)) and int(m.group(1)) > it["rank"]:
        return ("up", int(m.group(1)) - it["rank"])
    if re.search(r"(?<![\d가-힣])(급)?상승", note):
        return ("up", 0)
    return None


def snap_move(it: Item, prev: list[list] | None) -> tuple[str, int] | None:
    """Against yesterday's snapshot of the same list: new in the top 15, or up 3+ places."""
    if not prev or len(prev) < 10:
        return None
    before = {k: r for k, r in prev}
    r0 = before.get(ikey(it)[:32])
    if r0 is None:
        return ("new", 0) if it["rank"] <= 15 else None
    return ("up", r0 - it["rank"]) if r0 - it["rank"] >= 3 else None


def _strength(kind: str, steps: int, rank: int) -> float:
    pos = (LIMIT + 1 - min(rank, LIMIT)) / LIMIT  # 1.0 at #1 … 0.05 at #20
    if kind == "new":
        return 0.6 + pos
    if kind == "hot":
        return 0.3 + 0.8 * pos
    return (min(steps, 20) / 20 if steps else 0.25) + 0.5 * pos


def _signal(kind: str, steps: int, rank: int) -> str:
    if kind == "new":
        return f"새로 진입 · {rank}위"
    if kind == "hot":
        return f"급상승 {rank}위"
    return f"{steps}계단 상승 · {rank}위" if steps else f"상승 · {rank}위"


def _where(b: Board) -> str:
    return f"{b.card} · {b.tab}"


def rising(boards: list[Board], lists: dict[str, dict], prev: dict[str, list] | None = None,
           limit: int = 60, per_card: int = 6) -> list[dict[str, Any]]:
    """Items that just entered or climbed, strongest first; one row per item (its strongest list)."""
    prev = prev or {}
    best: dict[str, dict[str, Any]] = {}
    for b in boards:
        got = lists.get(b.id)
        if not got or got.get("stale"):
            continue
        hot = "급상승" in b.card or "급상승" in b.tab
        for it in got["items"]:
            sig = upstream_move(it) or (snap_move(it, prev.get(b.id)) if b.period in ROLLING else None)
            if not sig and hot and it["rank"] <= 10:
                sig = ("hot", 0)
            if not sig:
                continue
            kind, steps = sig
            s = _strength(kind, steps, it["rank"])
            k = ikey(it)
            row = best.get(k)
            if row is None:
                row = best[k] = {"key": k, "name": it["name"], "by": it.get("by"), "url": it.get("url"), "field": b.field,
                                 "where": _where(b), "card": b.card, "kind": b.kind, "signal": _signal(kind, steps, it["rank"]),
                                 "move": kind, "steps": steps, "rank": it["rank"], "score": 0.0, "lists": 0, "_best": -1.0}
            row["score"] += s
            row["lists"] += 1
            if s > row["_best"]:
                row.update({"_best": s, "field": b.field, "where": _where(b), "card": b.card, "steps": steps,
                            "signal": _signal(kind, steps, it["rank"]), "move": kind, "kind": b.kind, "rank": it["rank"],
                            "url": it.get("url") or row["url"]})
    rows = sorted(best.values(), key=lambda r: -r["score"])
    out, per = [], defaultdict(int)
    for r in rows:  # keep the view varied: one busy list must not fill it
        if per[r["card"]] >= per_card:
            continue
        per[r["card"]] += 1
        out.append({k: (round(v, 2) if k == "score" else v) for k, v in r.items() if k not in ("_best", "card")})
        if len(out) >= limit:
            break
    return out


# ---- 소비 키워드 --------------------------------------------------------------------------------
def _base(name: str) -> str:
    return BRACKETS.sub(" ", unicodedata.normalize("NFKC", name))


def words(name: str) -> set[str]:
    """Space-separated words of a product name (Hangul / Latin scripts), minus promo and size words."""
    out = set()
    for tok in re.split(r"[^\w]+", _base(name)):
        t = tok.lower().strip("_")
        if (len(t) < 2 or any(c.isdigit() for c in t) or t in STOP or KANA_HAN.search(t)
                or (t.isascii() and len(t) < 3)):
            continue
        out.add(t)
    return out


def phrases(name: str) -> set[str]:
    """Two-word Latin phrases ('toilet paper', 'heated throw'): English names a product type in two words."""
    toks = [t.lower() for t in re.split(r"[^\w'-]+", _base(name)) if t]
    out = set()
    for a, b in zip(toks, toks[1:]):
        if (a.isascii() and b.isascii() and a.isalpha() and b.isalpha() and len(a) >= 3 and len(b) >= 3
                and a not in STOP and b not in STOP):
            out.add(f"{a} {b}")
    return out


def grams(name: str) -> set[str]:
    """Japanese/Chinese have no spaces. A katakana word is taken whole ('ドラゴンクエスト', never 'イン');
    a kanji/hanzi run gives its 2–4 character pieces ('炊飯器', '保溫瓶'); hiragana only separates."""
    out = set()
    base = _base(name)
    for w in KATAKANA_RUN.findall(base):
        if len(w) >= 3 and w not in STOP:
            out.add(w)
    for run in HAN_RUN.findall(base):
        for n in range(2, min(4, len(run)) + 1):
            for i in range(len(run) - n + 1):
                if run[i:i + n] not in STOP:
                    out.add(run[i:i + n])
    return out


def _mine(names: dict[str, str], min_support: int = 3) -> dict[str, set[str]]:
    """item key -> kept CJK words: pieces in ≥ min_support items, longest form wins
    ('ドラゴンクエスト' over 'ドラゴンクエ' when they cover the same items)."""
    per_item = {k: grams(n) for k, n in names.items()}
    support: dict[str, int] = defaultdict(int)
    for gs in per_item.values():
        for g in gs:
            support[g] += 1
    cand = sorted((g for g, c in support.items() if c >= min_support), key=len, reverse=True)
    kept: list[str] = []
    for g in cand:
        if not any(g in h and support[h] >= 0.7 * support[g] for h in kept):
            kept.append(g)
    keep = set(kept)
    return {k: gs & keep for k, gs in per_item.items()}


def _tab_words(b: Board) -> set[str]:
    return {norm_key(w) for w in re.split(r"[\s·,/]+", f"{b.tab} {b.card}") if w}


def term_weights(boards: list[Board], lists: dict[str, dict]) -> dict[str, dict[str, Any]]:
    """term -> {score, items: {item key: (weight, name)}, lists: {board id}, fields, explicit}."""
    goods = [(b, lists[b.id]["items"]) for b in boards
             if lists.get(b.id, {}).get("items") and (b.kind == "keyword" or b.field in GOODS)]
    names = {ikey(it): it["name"] for b, items in goods if b.kind != "keyword" for it in items}
    mined = _mine(names)
    terms: dict[str, dict[str, Any]] = {}

    def add(term: str, b: Board, it: Item, w: float, explicit: bool) -> None:
        t = terms.setdefault(term, {"items": {}, "lists": set(), "fields": set(), "explicit": False, "label": term})
        k = ("kw:" if b.kind == "keyword" else "") + ikey(it)  # a search word is not a product
        if k not in t["items"] or w > t["items"][k][0]:
            t["items"][k] = (w, it["name"])
        t["lists"].add(b.id)
        t["fields"].add(b.field)
        t["explicit"] = t["explicit"] or explicit

    for b, items in goods:
        if b.kind == "keyword":  # the list *is* the shopping words: each list that has it counts, rising ones more
            for it in items:
                k = norm_key(it["name"])
                w = 1.5 / math.sqrt(it["rank"]) + (0.5 if upstream_move(it) else 0.0)
                add(k, b, it, 0.0, True)
                terms[k]["label"] = it["name"]
                if b.age or b.gender:  # which age/gender tabs search it
                    who = terms[k].setdefault("who", {})
                    who[b.tab] = min(who.get(b.tab, 99), it["rank"])
                terms[k]["kw"] = terms[k].get("kw", 0.0) + w
            continue
        skip = _tab_words(b)
        per_list: dict[str, int] = defaultdict(int)
        for it in items:
            for term in words(it["name"]) | phrases(it["name"]) | mined.get(ikey(it), set()):
                if norm_key(term) in skip or per_list[term] >= 3:
                    continue
                per_list[term] += 1
                add(term, b, it, 1 / math.sqrt(it["rank"]), False)
    for t in terms.values():
        t["score"] = sum(w for w, _ in t["items"].values()) + t.get("kw", 0.0)
    return terms


def themes(boards: list[Board], lists: dict[str, dict], before: dict[str, float] | None = None,
           limit: int = 24) -> list[dict[str, Any]]:
    """Words people are buying under right now, strongest first, with the change since `before`."""
    terms = term_weights(boards, lists)
    for t in terms.values():
        # a word several lists agree on beats one list's run of near-identical names; a word found in every
        # field ('soft', '系列') is how products are sold, not what is bought
        spread = max(1, len(t["fields"] - {"종합 쇼핑"}))
        t["score"] *= (1 + 0.05 * min(len(t["lists"]), 10)) / spread ** 0.75
    rows = [(term, t) for term, t in terms.items()
            if t["explicit"] or (len(t["items"]) >= 3 and len(t["lists"]) >= 2)]
    rows.sort(key=lambda x: -x[1]["score"])
    groups: list[dict[str, Any]] = []
    for term, t in rows:
        keys = set(t["items"])
        # same goods under another word ('일본' / 'eSIM' / '도쿄' are one eSIM theme): fold into the stronger one
        if g := next((g for g in groups if keys & g["keys"]
                      and len(keys & g["keys"]) >= 0.75 * min(len(keys), len(g["keys"]))), None):
            if g["label"] in t["label"] and len(keys) >= 0.6 * len(g["keys"]):
                g["also"].insert(0, g["label"])  # 'paper' -> 'toilet paper': the fuller name of the same goods
                g["label"] = t["label"]
            elif len(g["also"]) < 3 and t["label"] not in g["also"]:
                g["also"].append(t["label"])
            g["also"] = [a for a in g["also"] if a != g["label"]][:3]
            g["keys"] |= keys
            g["items"] |= t["items"]
            g["lists"] |= t["lists"]
            g["fields"] |= t["fields"]
            continue
        if len(groups) >= limit:
            continue
        groups.append({"term": term, "label": t["label"], "score": t["score"], "keys": set(keys), "items": dict(t["items"]),
                       "lists": set(t["lists"]), "fields": set(t["fields"]), "explicit": t["explicit"], "also": [],
                       "who": t.get("who", {})})
    out = []
    for g in groups:
        ex = [n for _, n in sorted(g["items"].values(), key=lambda x: -x[0]) if norm_key(n) != norm_key(g["term"])]
        goods = [k for k in g["keys"] if not k.startswith("kw:")]
        out.append({"term": g["label"], "also": g["also"], "score": round(g["score"], 2), "items": len(goods),
                    "lists": len(g["lists"]), "fields": sorted(g["fields"], key=FIELDS.index), "keyword": g["explicit"],
                    "examples": ex[:3], "trend": _trend(norm_key(g["label"]), g["score"], before),
                    "who": [{"tab": tab, "rank": r} for tab, r in sorted(g["who"].items(), key=lambda x: x[1])[:5]]})
    return out


def _trend(term: str, score: float, before: dict[str, float] | None) -> dict[str, Any] | None:
    if not before or len(before) < 10:
        return None
    old = before.get(term)
    if old is None:
        return {"move": "new"}
    ratio = score / old if old else 0
    move = "up" if ratio >= 1.3 else "down" if ratio <= 0.7 else "flat"
    return {"move": move, "pct": round((ratio - 1) * 100)}


# ---- 세대·성별 차이 -----------------------------------------------------------------------------
def segments(boards: list[Board], lists: dict[str, dict]) -> list[dict[str, Any]]:
    """For each 10·20대 (or gender) tab: what is in its list but in none of the older (other-gender) tabs
    of the same card — items, and words that pile up only there."""
    by_card: dict[tuple[str, str], list[tuple[Board, list[Item]]]] = defaultdict(list)
    for b in boards:
        if (b.age or b.gender) and lists.get(b.id, {}).get("items"):
            by_card[(b.field, b.card)].append((b, lists[b.id]["items"]))
    out: list[dict[str, Any]] = []
    for (field, card), got in by_card.items():
        for b, items in got:
            if b.age in (10, 20):
                ref = [(o, oi) for o, oi in got if o.age >= 30 and (not b.gender or o.gender in ("", b.gender))]
                vs = "30대 이상" + (f" {b.gender}" if b.gender and any(o.gender for o, _ in ref) else "")
            elif not b.age and b.gender:
                other = "남성" if b.gender == "여성" else "여성"
                ref = [(o, oi) for o, oi in got if not o.age and o.gender == other]
                vs = other
            else:
                continue
            if not ref:
                continue
            older = {ikey(it) for _, oi in ref for it in oi}
            only = [{k: it.get(k) for k in ("rank", "name", "by", "url", "note")} for it in items if ikey(it) not in older]
            terms: list[dict[str, Any]] = []
            if b.kind != "keyword":
                mine = _count_words(items)
                theirs = [_count_words(oi) for _, oi in ref]
                for term, (w, n) in sorted(mine.items(), key=lambda x: -x[1][0]):
                    o = sum(t.get(term, (0.0, 0))[0] for t in theirs) / len(theirs)
                    if n >= 2 and (o == 0 or w >= 3 * o):
                        terms.append({"term": term, "items": n, "older": "없음" if o == 0 else "적음"})
                    if len(terms) >= 6:
                        break
            out.append({"label": b.tab, "age": b.age, "gender": b.gender, "field": field, "list": card,
                        "keyword": b.kind == "keyword", "vs": vs, "only": only[:10], "terms": terms})
    out.sort(key=lambda g: (0 if g["age"] else 1, g["age"], g["gender"] != "여성"))
    return out


def _count_words(items: list[Item]) -> dict[str, tuple[float, int]]:
    acc: dict[str, list[float]] = defaultdict(lambda: [0.0, 0])
    for it in items:
        for t in words(it["name"]) | {g for g in grams(it["name"]) if len(g) >= 3}:
            acc[t][0] += 1 / math.sqrt(it["rank"])
            acc[t][1] += 1
    return {t: (w, int(n)) for t, (w, n) in acc.items()}


# ---- 나라 간 비교 ------------------------------------------------------------------------------
def world(by_country: dict[str, dict[str, Any]], min_countries: int = 3, limit: int = 24) -> dict[str, Any]:
    """Across countries' cards: what charts in several countries at once, and what charts only here.
    `by_country` = collect() results (cards + rising)."""
    occ: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    types: dict[tuple[str, str], dict[str, set[str]]] = defaultdict(dict)  # (card, tab) -> country -> keys
    for code, d in by_country.items():
        for c in d.get("cards", []):
            for li in c["lists"]:
                keys = types[(c["title"], li["tab"])].setdefault(code, set())
                for it in li["items"]:
                    k = ikey(it)
                    keys.add(k)
                    if not _world_key_ok(k):
                        continue
                    cur = occ[k].get(code)
                    if cur is None or it["rank"] < cur["rank"]:
                        occ[k][code] = {"rank": it["rank"], "where": f'{c["title"]} · {li["tab"]}', "name": it["name"],
                                        "field": c["field"], "url": it.get("url"), "by": it.get("by")}
    risers = {code: {r["key"] for r in d.get("rising", [])} for code, d in by_country.items()}
    shared = []
    for k, cs in occ.items():
        if len(cs) < min_countries:
            continue
        first = cs.get("US") or cs.get("GB") or next(iter(cs.values()))
        shared.append({"key": k, "name": first["name"], "by": first["by"], "field": first["field"],
                       "countries": {code: {"rank": v["rank"], "where": v["where"]} for code, v in cs.items()},
                       "rising_in": sorted(code for code in cs if k in risers.get(code, set())),
                       "_mean": sum(v["rank"] for v in cs.values()) / len(cs)})
    shared.sort(key=lambda r: (-(len(r["countries"]) + 1.5 * len(r["rising_in"])), r["_mean"]))  # rising together first
    local: dict[str, list[dict[str, Any]]] = {}
    for code, d in by_country.items():
        rows = []
        for c in d.get("cards", []):
            for li in c["lists"]:
                others = {cc: ks for cc, ks in types[(c["title"], li["tab"])].items() if cc != code}
                if len(others) < 2:
                    continue  # a list only this country has says nothing about 'only here'
                seen = set().union(*others.values())
                for it in li["items"][:10]:
                    if ikey(it) not in seen:
                        rows.append({"rank": it["rank"], "name": it["name"], "by": it.get("by"), "url": it.get("url"),
                                     "field": c["field"], "where": f'{c["title"]} · {li["tab"]}', "key": ikey(it)})
        uniq: dict[str, dict[str, Any]] = {}
        for r in sorted(rows, key=lambda r: r["rank"]):
            uniq.setdefault(r["key"], r)
        local[code] = list(uniq.values())[:limit]
    mix = {code: dict(Counter(r["field"] for r in d.get("rising", []) if r.get("field"))) for code, d in by_country.items()}
    return {"shared": [{k: v for k, v in r.items() if k != "_mean"} for r in shared], "local": local, "mix": mix}


# ---- 스냅샷 ------------------------------------------------------------------------------------
def snapshot(lists: dict[str, dict], terms: list[dict[str, Any]]) -> dict[str, Any]:
    """What tomorrow compares against: each list's (item key, rank) and today's keyword scores."""
    return {"lists": {bid: [[ikey(it)[:32], it["rank"]] for it in got["items"]]
                      for bid, got in lists.items() if got.get("items") and not got.get("stale")},
            "themes": {norm_key(t["term"]): t["score"] for t in terms}}


# ---- 기록 · 추이 · 요약 --------------------------------------------------------------------------
DAY_THEMES = 40


def daily(themes: list[dict[str, Any]], rising: list[dict[str, Any]]) -> dict[str, Any]:
    """What one day leaves for the long record: keyword scores and how many rising things each field had."""
    return {"themes": {norm_key(t["term"]): [t["term"], t["score"]] for t in themes[:DAY_THEMES]},
            "fields": dict(Counter(r["field"] for r in rising))}


def history(records: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    """Daily records (oldest first) → rising things per field per day, and each keyword's score per day."""
    days = [d for d, _ in records]
    fields: dict[str, list[int]] = {}
    terms: dict[str, list[float]] = {}
    for i, (_, rec) in enumerate(records):
        for f, n in (rec.get("fields") or {}).items():
            fields.setdefault(f, [0] * len(days))[i] = n
        for k, (_, score) in (rec.get("themes") or {}).items():
            terms.setdefault(k, [0.0] * len(days))[i] = score
    order = sorted(fields, key=lambda f: FIELDS.index(f) if f in FIELDS else len(FIELDS))
    return {"days": days, "fields": {f: fields[f] for f in order}, "themes": terms}


def attach_history(themes: list[dict[str, Any]], hist: dict[str, Any], min_days: int = 3) -> None:
    """Keywords without a shopping-click line get one from our own daily record, once it is a few days long."""
    if len(hist.get("days") or []) < min_days:
        return
    for t in themes:
        s = hist["themes"].get(norm_key(t["term"]))
        if t.get("spark") or not s or not (top := max(s)):
            continue
        t["spark"] = {"unit": "day", "series": [round(100 * v / top) for v in s], "now": round(100 * s[-1] / top),
                      "change": round(100 * (s[-1] / s[-8] - 1)) if len(s) >= 8 and s[-8] else None, "yoy": None}


def lean(g: dict[str, Any]) -> tuple[str, float] | None:
    """The shopping category a group leans to most against 전체 (categories under 3% of its clicks aside)."""
    cands = [(c, r) for c, r in g["over"].items() if r and g["share"][c] >= 3]
    return max(cands, key=lambda x: x[1]) if cands else None


def summary(d: dict[str, Any]) -> list[dict[str, Any]]:
    """Four numbers to read before any chart. `d` is the public view (adult names already gone)."""
    tiles: list[dict[str, Any]] = []
    rising, themes = d.get("rising") or [], d.get("themes") or []
    shared = (d.get("world") or {}).get("shared") or []
    if idx := d.get("index"):
        g0 = idx["groups"][0]
        ch = [(c, v) for c, v in g0["change"].items() if v is not None and v > 0 and g0["share"][c] >= 1]
        if ch:  # nothing grew: no 'grew most' tile
            c, v = max(ch, key=lambda x: x[1])
            tiles.append({"label": "가장 늘어난 쇼핑 분야", "value": c, "delta": v, "sub": "최근 4주 클릭, 그 전 4주 대비"})
        groups = [g for g in idx["groups"][1:] if g["age"] and g["gender"]] or idx["groups"][1:]  # 나이×성별 first
        leans = [(g, *lv) for g in groups if (lv := lean(g))]
        if leans:
            g, c, r = max(leans, key=lambda x: x[2])
            tiles.append({"label": "유독 많이 보는 분야", "value": f"{g['label']} · {c}",
                          "sub": f"쇼핑 클릭 비중이 전체의 {r:.1f}배"})
    if len(tiles) < 2:
        tiles.append({"label": "지금 뜨는 것", "value": f"{len(rising)}개", "sub": "새로 순위에 들거나 크게 오른 것"})
        if cnt := Counter(r["field"] for r in rising):
            f, n = cnt.most_common(1)[0]
            tiles.append({"label": "가장 많이 뜨는 분야", "value": f, "sub": f"뜨는 것의 {round(100 * n / len(rising))}% ({n}개)"})
    if themes:
        tiles.append({"label": "뜨는 소비 키워드", "value": " · ".join(t["term"] for t in themes[:3]),
                      "sub": "여러 순위표에 겹쳐 나온 말"})
    if shared:
        r = shared[0]
        tiles.append({"label": "여러 나라에서 동시에", "value": r["name"], "sub": f"{len(r['countries'])}개국 순위 · {r['field']}"})
    return tiles[:4]
