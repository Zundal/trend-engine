"""Keyless category classifier: what *kind* of interest is each trend? (연예·방송, 게임, 음식 …)

No single source labels trends, so several independent pieces of evidence vote:

  뉴스 섹션      keyword appears in headlines of a news section feed (연예/스포츠/경제/IT/건강/사회)  +1 each (≤3)
  영상 카테고리  a popular video whose title/tags mention the keyword has that video category    +1 each (≤3)
  위키백과 분류  the keyword's article categories match a pattern (가수→음악, 비디오 게임→게임)   +2
  쇼핑 분류      the keyword is a top shopping search in that shopping category (Korea)         +2
  관련 기사      a news item attached to the trend shares ≥60% of its words with a section headline  +2
  핵심어 사전    strong domain words inside the keyword itself (부동산→경제, 검찰→정치·사회)         +1 (≤2)

Highest total wins; nothing ≥ 1 → "기타". Votes are kept so the UI/tests can explain a label.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any
from urllib.parse import quote

import httpx
from defusedxml import ElementTree as ET  # remote feeds: no XXE / entity expansion

from .config import Region, Settings
from .normalize import mentions_any, norm_key, tokens

TAXONOMY = ["연예·방송", "음악", "게임", "스포츠", "패션·뷰티", "음식", "테크·IT", "경제·재테크", "정치·사회", "생활·건강", "기타"]

NEWS_TOPICS = {  # Google News section -> category
    "ENTERTAINMENT": "연예·방송", "SPORTS": "스포츠", "BUSINESS": "경제·재테크",
    "TECHNOLOGY": "테크·IT", "HEALTH": "생활·건강", "NATION": "정치·사회",
}
VIDEO_CATEGORIES = {  # content item category (YouTube label, Apple/Steam chart) -> our category
    "테크·IT": "테크·IT", "게임": "게임",
    "음악": "음악", "게임": "게임", "스포츠": "스포츠", "엔터테인먼트": "연예·방송", "영화/애니": "연예·방송",
    "코미디": "연예·방송", "뉴스/정치": "정치·사회", "노하우/스타일": "패션·뷰티", "과학기술": "테크·IT",
    "자동차": "테크·IT", "교육": "생활·건강", "여행": "생활·건강", "동물": "생활·건강",
}
SHOPPING_CATEGORIES = {  # 네이버 쇼핑인사이트 분야 -> category
    "패션의류": "패션·뷰티", "패션잡화": "패션·뷰티", "화장품/미용": "패션·뷰티", "식품": "음식",
    "디지털/가전": "테크·IT", "스포츠/레저": "스포츠", "생활/건강": "생활·건강", "가구/인테리어": "생활·건강",
    "출산/육아": "생활·건강", "여가/생활편의": "생활·건강", "도서": "기타",
}
# Wikipedia category name patterns (ko/en/ja/zh/vi/de/fr mixed — first match wins per category string)
WIKI_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"비디오 게임|게임|e스포츠|video game|esports|ゲーム|電子遊戲|trò chơi", re.I), "게임"),
    (re.compile(r"가수|아이돌|음악 그룹|음반|노래|밴드|래퍼|작곡가|singer|musician|album|song|rapper|歌手|アイドル|ca sĩ", re.I), "음악"),
    (re.compile(r"배우|드라마|영화|예능|방송|텔레비전|유튜버|코미디언|actor|actress|film|television|series|tv |youtuber|俳優|ドラマ|映画|演員|diễn viên|phim", re.I), "연예·방송"),
    (re.compile(r"축구|야구|농구|배구|골프|테니스|선수|올림픽|리그|football|soccer|baseball|basketball|athlete|olympic|league|サッカー|野球|選手|cầu thủ|bóng đá", re.I), "스포츠"),
    (re.compile(r"요리|음식|과자|음료|디저트|빵|주류|dish|food|cuisine|dessert|drink|beverage|料理|食品|món ăn", re.I), "음식"),
    (re.compile(r"패션|의류|화장품|뷰티|fashion|clothing|cosmetic|ファッション", re.I), "패션·뷰티"),
    (re.compile(r"소프트웨어|스마트폰|컴퓨터|인공지능|반도체|인터넷|software|smartphone|computer|artificial intelligence|semiconductor|ソフトウェア|人工知能", re.I), "테크·IT"),
    (re.compile(r"기업|회사|주식|은행|경제|암호화폐|company|companies|bank|economy|stock|企業|会社|công ty", re.I), "경제·재테크"),
    (re.compile(r"정치인|국회의원|정당|대통령|장관|법조인|군인|사건|사고|재판|선거|politician|election|minister|president|incident|政治家|事件|chính trị", re.I), "정치·사회"),
    (re.compile(r"질병|건강|의학|병원|disease|health|medicine|病気", re.I), "생활·건강"),
]
# Our own lexicon for headline-style Korean trends ("석유 최고가격 동결", "오세훈 부동산 문제") that rarely match
# a news section verbatim. Words, not substrings of names: matched against whole tokens / token prefixes.
LEXICON: dict[str, tuple[str, ...]] = {
    "경제·재테크": ("부동산", "집값", "금리", "환율", "주식", "주가", "코스피", "코스닥", "증시", "석유", "유가", "물가", "관세",
                 "etf", "비트코인", "코인", "배당", "상장", "매출", "실적", "연봉", "세금", "예산", "은행", "대출", "청약"),
    "정치·사회": ("대통령", "국회", "장관", "총리", "대표", "의원", "검찰", "법원", "재판", "선거", "탄핵", "정부", "여당", "야당",
               "특검", "대법관", "경찰", "화재", "사고", "사망", "실종", "지진", "태풍", "폭우", "파업", "시위", "집회", "개혁"),
    "스포츠": ("야구", "축구", "농구", "배구", "골프", "홈런", "솔로포", "선발", "감독", "우승", "결승", "리그", "올림픽",
             "아시안게임", "월드컵", "국가대표", "kbo", "epl"),
    "연예·방송": ("드라마", "예능", "영화", "배우", "시즌", "방송", "넷플릭스", "티빙", "시청률", "열애", "결혼", "이혼"),
    "음악": ("컴백", "앨범", "뮤비", "콘서트", "음원", "아이돌", "걸그룹", "보이그룹", "데뷔"),
    "게임": ("게임", "롤", "배그", "발로란트", "마크", "마인크래프트", "닌텐도", "스위치", "플스", "업데이트", "패치"),
    "테크·IT": ("아이폰", "갤럭시", "애플", "삼성전자", "ai", "인공지능", "챗gpt", "반도체", "앱", "출시", "노트북"),
    "음식": ("맛집", "레시피", "디저트", "과자", "라면", "치킨", "카페", "메뉴", "먹방"),
    "생활·건강": ("날씨", "건강", "병원", "독감", "코로나", "다이어트", "여행", "휴가", "연휴", "추석", "설날"),
}
# Basic English / Japanese domain words so foreign-country trends aren't left as 기타.
for _cat, _words in {
    "스포츠": ("nfl", "nba", "mlb", "nhl", "ufc", "f1", "golf", "standings", "fc", "premier", "tennis", "match", "サッカー", "野球", "試合"),
    "생활·건강": ("weather", "forecast", "storm", "hurricane", "earthquake", "天気", "台風", "地震"),
    "경제·재테크": ("stock", "stocks", "earnings", "price", "prices", "bitcoin", "crypto", "tariff", "株価", "円安"),
    "정치·사회": ("election", "senate", "congress", "governor", "shooting", "選挙", "首相"),
    "연예·방송": ("film", "movie", "season", "episode", "trailer", "netflix", "ドラマ", "映画"),
    "게임": ("game", "gaming", "roblox", "minecraft", "fortnite", "ゲーム"),
}.items():
    LEXICON[_cat] = LEXICON[_cat] + _words

_DISAMBIG = re.compile(r"동음이의|동명이인|disambiguation|曖昧さ回避|消歧义|định hướng", re.I)
UA = "trend-engine/0.1 (category classifier)"


def wiki_category(names: list[str]) -> str | None:
    """Category from an article's category names (disambiguation pages carry no signal)."""
    if any(_DISAMBIG.search(n) for n in names):
        return None
    votes: dict[str, int] = defaultdict(int)
    for n in names:
        for pat, cat in WIKI_PATTERNS:
            if pat.search(n):
                votes[cat] += 1
                break
    return max(votes, key=lambda c: (votes[c], -TAXONOMY.index(c))) if votes else None


# --- evidence fetchers ----------------------------------------------------------------------
def parse_topic_feed(raw: str) -> list[str]:
    root = ET.fromstring(raw)
    out = []
    for node in root.iter("item"):
        title = (node.findtext("title") or "").strip()
        publisher = (node.findtext("source") or "").strip()
        if publisher and title.endswith(f" - {publisher}"):
            title = title[: -len(publisher) - 3].strip()
        if title:
            out.append(title)
    return out


async def fetch_topics(client: httpx.AsyncClient, region: Region) -> dict[str, str]:
    """section -> raw RSS (kept raw so it can be recorded as a fixture)."""
    hl = {"ko": "ko", "ja": "ja", "zh": "zh-TW", "vi": "vi", "de": "de", "fr": "fr", "pt": "pt-BR"}.get(region.lang, f"en-{region.country}")
    out = {}
    for topic in NEWS_TOPICS:
        url = f"https://news.google.com/rss/headlines/section/topic/{topic}?hl={hl}&gl={region.country}&ceid={region.country}:{hl.split('-')[0]}"
        try:
            r = await client.get(url, follow_redirects=True)
            if r.status_code == 200:
                out[topic] = r.text
        except httpx.HTTPError:
            continue
    return out


async def fetch_wiki(client: httpx.AsyncClient, lang: str, titles: list[str]) -> str:
    """Raw MediaWiki response with categories for up to 50 titles (redirects resolved)."""
    t = "|".join(dict.fromkeys(x for x in titles if x))[:4000]
    url = (f"https://{lang}.wikipedia.org/w/api.php?action=query&prop=categories&cllimit=max&clshow=!hidden"
           f"&redirects=1&format=json&titles={quote(t)}")
    r = await client.get(url, headers={"User-Agent": UA})
    return r.text if r.status_code == 200 else "{}"


def parse_wiki(raw: str) -> dict[str, list[str]]:
    """requested-title (normalised key) -> category names."""
    data = json.loads(raw or "{}").get("query", {})
    back: dict[str, str] = {}
    for kind in ("normalized", "redirects"):
        for m in data.get(kind, []):
            back[m["to"]] = back.get(m["from"], m["from"])
    out: dict[str, list[str]] = {}
    for p in data.get("pages", {}).values():
        cats = [c["title"].split(":", 1)[-1] for c in p.get("categories", [])]
        title = p.get("title", "")
        if cats:
            out[norm_key(back.get(title, title))] = cats
            out[norm_key(title)] = cats
    return out


# --- voting ---------------------------------------------------------------------------------
def classify(texts: list[str], related: list[str], topics: dict[str, list[str]], videos: list[dict[str, Any]],
             wiki: dict[str, list[str]], shopping: dict[str, str]) -> tuple[str, dict[str, int]]:
    """texts = the trend's keyword variants. Returns (category, votes)."""
    votes: dict[str, int] = defaultdict(int)
    keys = {norm_key(t) for t in texts if norm_key(t)}
    related_tokens = [tokens(r) for r in related if len(tokens(r)) >= 3]
    for topic, heads in topics.items():
        cat = NEWS_TOPICS[topic]
        hits = sum(1 for h in heads if mentions_any(texts, h))
        votes[cat] += min(hits, 3)
        head_tokens = [tokens(h) for h in heads]
        if any(len(rt & ht) / len(rt) >= 0.6 for rt in related_tokens for ht in head_tokens if ht):
            votes[cat] += 2
    words = set().union(*(tokens(t) for t in texts)) | {norm_key(t) for t in texts}
    for cat, lex in LEXICON.items():
        n = sum(1 for w in lex if any(t == w or (len(w) >= 2 and t.startswith(w)) for t in words))
        if n:
            votes[cat] += min(n, 2)
    video_hits: dict[str, int] = defaultdict(int)
    for v in videos:
        cat = VIDEO_CATEGORIES.get(v.get("category") or "")
        tags = {norm_key(t) for t in v.get("related", [])}
        if cat and (keys & tags or mentions_any(texts, v.get("keyword", ""))):
            video_hits[cat] += 1
    for cat, n in video_hits.items():
        votes[cat] += min(n, 3)
    for k in keys:
        if k in wiki and (c := wiki_category(wiki[k])):
            votes[c] += 2
            break
    for k in keys:
        if k in shopping:
            votes[SHOPPING_CATEGORIES.get(shopping[k], "기타")] += 2
            break
    votes = {c: n for c, n in votes.items() if n > 0}
    if not votes:
        return "기타", {}
    best = max(votes, key=lambda c: (votes[c], -TAXONOMY.index(c)))
    return best, votes


def shopping_index(shopping: dict[str, Any] | None) -> dict[str, str]:
    """normalised keyword -> 쇼핑 분야, from a Shopping Insight result (any group)."""
    out: dict[str, str] = {}
    for cats in (shopping or {}).get("by_segment", {}).values():
        for cat, v in cats.items():
            for k in v.get("top", []):
                out.setdefault(norm_key(k), cat)
    for cat, top in (shopping or {}).get("overall", {}).items():
        for k in top:
            out.setdefault(norm_key(k), cat)
    return out


async def gather_evidence(settings: Settings, client: httpx.AsyncClient, region: Region,
                          titles: list[str]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """(topic headlines, wiki categories) for a region — from fixtures when offline."""
    if settings.offline:
        topics_raw, wiki_raw = {}, "{}"
        tp = settings.fixtures_dir / "news_topics" / f"{region.country}.json"
        wp = settings.fixtures_dir / "wiki_categories" / f"{region.lang}.json"
        if tp.exists():
            topics_raw = json.loads(tp.read_text(encoding="utf-8"))
        if wp.exists():
            wiki_raw = wp.read_text(encoding="utf-8")
    else:
        topics_raw = await fetch_topics(client, region)
        wiki_raw = await fetch_wiki(client, region.lang, titles[:50])
    topics = {t: parse_topic_feed(raw) for t, raw in topics_raw.items() if raw.strip().startswith("<")}
    return topics, parse_wiki(wiki_raw)
