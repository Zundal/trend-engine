"""일본 소비 목록: 가격비교 사이트 분야별 인기, 가전 매장 판매 집계, 추정 판매량 차트(도서·음반·영상),
게임 소프트 판매량, 서점 베스트셀러, 박스오피스.

조사(2026-11-18): 대형 몰·뷰티·패션(라쿠텐 시장·야후 쇼핑·@cosme·ZOZOTOWN·Qoo10·드러그스토어)과 가전 양판점은
봇 차단으로 막혀 있다. 패션·뷰티는 가격비교 사이트의 해당 분야 순위로 대신한다.
"""

from __future__ import annotations

import json
import re
from datetime import timedelta

from .base import Board, Item, clean, first, item, lean_html, man, money, num, ranked


# ---- 가격비교 사이트: 분야별 인기 (많이 본·찾은 상품, 판매량 아님) -----------------------------------
def parse_kakaku(raw: str) -> list[Item]:
    out = []
    for chunk in raw.split('<td class="rankingRate">')[1:]:
        rank = num(first(r'ranknum[^"]*"><span>(\d+)</span>', chunk))
        maker = first(r'rank3BarMaker">(.*?)</span>', chunk)
        name = first(r'rank3BarItem">(.*?)</span>', chunk)
        href = first(r'href="(/item/[^"]+)"', chunk)
        price = first(r'rankingSupInfoItemNum">&#165;([\d,]+)', chunk)
        cate = clean(first(r'rankingCate">(.*?)</p>', chunk))
        if rank:
            out.append(item(int(rank), name, maker, money(price, "¥"), cate.split(">")[-1].strip() or None,
                            f"https://kakaku.com{href}" if href else None))
    return ranked(out)


KAKAKU_GROUPS: tuple[tuple[str, str, str], ...] = (
    # (field, tab, group path under /ranking/)
    ("종합 쇼핑", "전체", ""), ("종합 쇼핑", "취미·장난감", "hobby/"), ("종합 쇼핑", "유아", "baby/"),
    ("종합 쇼핑", "스포츠", "sports/"), ("종합 쇼핑", "아웃도어", "outdoor/"), ("종합 쇼핑", "반려동물", "pet/"),
    ("종합 쇼핑", "자동차용품", "car_goods/"), ("종합 쇼핑", "자전거", "bike_goods/"),
    ("패션", "신발", "shoes/"), ("패션", "시계·액세서리", "watch_accessory/"),
    ("뷰티", "뷰티·헬스", "beauty_health/"),
    ("디지털·가전", "가전", "kaden/"), ("디지털·가전", "PC", "pc/"), ("디지털·가전", "카메라", "camera/"),
    ("식품", "식품", "food/"), ("식품", "음료·주류", "drink/"),
    ("생활·리빙", "생활용품", "houseware/"), ("생활·리빙", "주방", "kitchen/"), ("생활·리빙", "인테리어", "interior/"),
    ("생활·리빙", "주택 설비", "housing/"), ("생활·리빙", "DIY·공구", "diy/"),
    ("게임", "게임", "game/"),
)


# ---- 가전 판매 집계 (매장·온라인 실판매, 월간) ------------------------------------------------
def parse_bcn(raw: str) -> list[Item]:
    marker = 'class="rankingList01_summaryBox' if 'class="rankingList01_summaryBox' in raw else \
        'class="rankingList01_box rankingList01_btn'
    out = []
    for chunk in raw.split(marker)[1:]:
        f = lambda c: clean(first(r'rankingList01_' + c + r'[^"]*">\s*(.*?)\s*</(?:p|h1)>', chunk))  # noqa: E731
        rank = num(f("rank"))
        if rank:
            out.append(item(int(rank), " ".join(x for x in (f("name"), f("model")) if x), f("maker"), None,
                            _ym(f("date"))))
    return ranked(out)


def _ym(s: str) -> str | None:
    m = re.search(r"(\d{4})年\s*(\d{1,2})月", s)
    return f"{m.group(1)}.{int(m.group(2)):02d} 출시" if m else None


BCN_TYPES: tuple[tuple[str, str], ...] = (
    ("노트북", "176"), ("데스크톱", "175"), ("태블릿", "177"), ("스마트폰", "196"), ("TV", "198"),
    ("이어폰·헤드폰", "185"), ("보조배터리", "189"), ("미러리스·DSLR", "193"), ("모니터", "178"),
    ("SSD", "180"), ("스마트 스피커", "203"),
)


# ---- 추정 판매량 차트 (도서·음반·영상, 주간) --------------------------------------------------
def parse_oricon(raw: str) -> list[Item]:
    out = []
    for chunk in raw.split('class="box-rank-entry"')[1:]:
        rank = num(first(r'<p class="num[^"]*">(\d+)</p>', chunk))
        title = first(r'class="title"[^>]*>(.*?)</h2>', chunk)
        name = clean(first(r'<p class="name">(.*?)</p>', chunk))
        url = first(r'href="(https://www\.oricon\.co\.jp/[^"]+)" itemprop="url"', chunk)
        facts = dict(x.split("：", 1) for x in re.findall(r"<li>([^<]+：[^<]+)</li>", chunk.split("unit-actions")[0]))
        sales = facts.get("推定売上部数") or facts.get("推定売上枚数") or facts.get("推定売上数")
        unit = "부" if "部" in (sales or "") else "장"
        by = name if name and name != "-" else facts.get("出版社") or facts.get("発売元")
        price = (facts.get("価格") or "").split("(")[0].strip()
        if rank:
            out.append(item(int(rank), title, by, price.replace("円", "엔") or None,
                            f"주간 추정 {man(sales)}{unit}" if num(sales) else None, url))
    return ranked(out)


ORICON: tuple[tuple[str, str, str, str], ...] = (
    # (field, card, tab, chart code)
    ("도서", "주간 도서 판매량", "종합", "ob"), ("도서", "주간 도서 판매량", "만화", "obc"),
    ("도서", "주간 도서 판매량", "문고", "obb"), ("도서", "주간 도서 판매량", "문예", "oba"),
    ("도서", "주간 도서 판매량", "라이트노벨", "obl"), ("도서", "주간 도서 판매량", "비즈니스", "obbb"),
    ("도서", "주간 도서 판매량", "자기계발", "obs"), ("도서", "주간 도서 판매량", "어린이", "obcb"),
    ("도서", "주간 도서 판매량", "요리", "obr"), ("도서", "주간 도서 판매량", "패션 잡지·무크", "obf"),
    ("음악", "주간 음반 판매량", "앨범 판매", "ja"), ("음악", "주간 음반 판매량", "싱글 판매", "js"),
    ("음악", "주간 음반 판매량", "앨범 합산", "coa"), ("음악", "주간 음반 판매량", "싱글 합산", "cos"),
    ("영화", "주간 영상물 판매량", "DVD", "dg"), ("영화", "주간 영상물 판매량", "블루레이", "bd"),
)


# ---- 게임 소프트 판매량 (주간) ------------------------------------------------------------
def parse_famitsu(raw: str) -> list[Item]:
    data = json.loads(first(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', raw))
    rows = data["props"]["pageProps"]["gameSalesRankingData"]["rankingData"]
    out = []
    for r in rows:
        sales, total = r.get("salesCount"), r.get("totalSalesCount")
        note = f"주간 {man(sales)}개" + (f" · 누적 {man(total)}개" if total and total != sales else " · 새로 출시")
        out.append(item(int(r["rank"]), r.get("title", ""), " · ".join(x for x in (r.get("platform"), r.get("maker")) if x),
                        money(r.get("price"), "", suffix="엔"), note))
    return ranked(out)


# ---- 서점 베스트셀러 (일간·주간) -----------------------------------------------------------
def parse_kino(raw: str) -> list[Item]:
    out = []
    for chunk in raw.split('<div class="list_area rankingList')[1:]:
        rank = num(first(r'rankingLabel">\s*<img[^>]*/?><span>(\d+)</span>', chunk))
        a = re.search(r'<h3 class="heightLine-2">\s*<a href="([^"]+)">(.*?)</a>', chunk, re.S)
        author = clean(first(r'<p class="clearfix ml10">(.*?)</p>', chunk))
        price = first(r"sale_price[^>]*>&yen;([\d,]+)", chunk)
        if rank and a:
            out.append(item(int(rank), a.group(2), re.sub(r"【[^】]*】", "", author).strip() or None, money(price, "¥"),
                            None, a.group(1)))
    return ranked(out)


KINO: tuple[tuple[str, str], ...] = (("종합 (주간)", "107002001001&vTp=w"), ("만화 (주간)", "107002001004&vTp=w"),
                                     ("전자책 (주간)", "107002002005&vTp=w"), ("예약 (주간)", "107002001011&vTp=w"))


# ---- 박스오피스 (주말) --------------------------------------------------------------------
def parse_eiga(raw: str) -> list[Item]:
    table = first(r'class="ranking-table">(.*?)</table>', raw)
    out = []
    for tr in re.findall(r"<tr>(.*?)</tr>", table, re.S):
        rank = num(first(r'rank-circle[^"]*">(\d+)<', tr))
        a = re.search(r'<h2 class="title">\s*<a href="(/movie/\d+/)">(.*?)</a>', tr, re.S)
        if not rank or not a:
            continue
        lw = re.search(r'last-week (\w+)">([^<]*)<', tr)
        weeks = first(r'class="weeks">(\d+)<', tr)
        screens = first(r'class="screen">(\d+)<', tr)
        trend = {"new": "새 개봉", "stay": "변동 없음", "up": "상승", "down": "하락"}.get(lw.group(1), "") if lw else ""
        if lw and lw.group(1) in ("up", "down") and num(lw.group(2)):
            trend = f"지난 {int(num(lw.group(2)))}위"
        parts = [trend, f"{weeks}주째" if weeks and weeks != "1" else "", f"{screens}개 관" if screens else ""]
        out.append(item(int(rank), a.group(2).replace("　", " "), first(r"<p>配給：(.*?)</p>", tr) or None, None,
                        " · ".join(p for p in parts if p), f"https://eiga.com{a.group(1)}"))
    return ranked(out)


def boards(country: str) -> list[Board]:
    if country != "JP":
        return []
    out = [Board(id=f"jp-kakaku-{g.strip('/') or 'all'}", country="JP", field=fld, card="가격비교 인기 순위", tab=tab,
                 basis="가격비교 사이트에서 많이 본 상품 순위 (관심도, 판매량 아님)", period="실시간",
                 url=f"https://kakaku.com/ranking/{g}", parser="kakaku", ext="html", encoding="cp932")
           for fld, tab, g in KAKAKU_GROUPS]
    out += [Board(id=f"jp-bcn-{t}", country="JP", field="디지털·가전", card="가전 판매 집계", tab=tab,
                  basis="전국 가전 매장·온라인 판매 실적 집계 (월간)", period="월간",
                  url=f"https://www.bcnretail.com/ranking/monthly/contents_type={t}", parser="bcn", ext="html",
                  ttl=timedelta(hours=24))
            for tab, t in BCN_TYPES]
    out += [Board(id=f"jp-oricon-{code}", country="JP", field=fld, card=card, tab=tab,
                  basis="주간 추정 판매량 (부·장) 순위", period="주간",
                  url=f"https://www.oricon.co.jp/rank/{code}/w/", parser="oricon", ext="html", encoding="cp932",
                  ttl=timedelta(hours=24), pace=5.0)  # weekly charts; a burst of 8 gets a challenge page
            for fld, card, tab, code in ORICON]
    out += [Board(id="jp-gamesales", country="JP", field="게임", card="게임 소프트 판매량", tab="주간",
                  basis="패키지·다운로드 게임 주간 판매 개수", period="주간",
                  url="https://www.famitsu.com/ranking/game-sales", parser="famitsu", ext="html",
                  ttl=timedelta(hours=12))]
    out += [Board(id=f"jp-books-{q.split('&')[0]}", country="JP", field="도서", card="대형 서점 베스트셀러", tab=tab,
                  basis="대형 서점 체인 판매 순위", period="주간",
                  url=f"https://www.kinokuniya.co.jp/disp/CKnRankingPageCList.jsp?dispNo={q}", parser="kino", ext="html",
                  ttl=timedelta(hours=12), pace=10.0)  # robots.txt Crawl-delay: 10
            for tab, q in KINO]
    out += [Board(id="jp-boxoffice", country="JP", field="영화", card="박스오피스", tab="주말",
                  basis="주말 극장 관객·흥행 순위", period="주간", url="https://eiga.com/ranking/jp/", parser="eiga",
                  ext="html", ttl=timedelta(hours=12))]
    return out


PARSERS = {"kakaku": parse_kakaku, "bcn": parse_bcn, "oricon": parse_oricon, "famitsu": parse_famitsu,
           "kino": parse_kino, "eiga": parse_eiga}
TRIMS = {"bcn": lean_html, "oricon": lean_html, "kino": lean_html, "kakaku": lean_html, "eiga": lean_html}
