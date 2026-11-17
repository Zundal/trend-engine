"""대만 소비 목록: 종합 쇼핑몰 분야별 Top, 대형 서점 주간 베스트셀러.

조사(2026-11-18): 대만 momo·博客來·誠品·Shopee·屈臣氏 는 막혀 있다. 베트남은 Tiki(브라우저가 아닌 클라이언트 403)·
Shopee·Fahasa·FPT·Thế Giới Di Động·Lazada(봇 확인)가 모두 막혀 있고 극장 흥행 집계도 키 없이 받을 곳이 없어,
여러 나라 공통 목록(앱 매출·PC·콘솔 게임·영화·음반, common.py)만 보인다.
"""

from __future__ import annotations

import json
import re

from .base import Board, Item, first, item, lean_html, money, num, ranked


# ---- 대만 종합 쇼핑몰: 분야별 Top 30 (사이트 'Top 30 推薦' 과 같은 정렬) --------------------------
def parse_pchome(raw: str) -> list[Item]:
    out = []
    for rank, p in enumerate(json.loads(raw).get("Prods") or [], 1):
        if p.get("isNC17"):
            continue  # 18금 상품: 순위 번호는 그대로 둔다
        rating = p.get("ratingValue")
        note = f"★{rating} · 리뷰 {p['reviewCount']:,}" if rating and p.get("reviewCount") else None
        out.append(item(rank, p.get("Name", ""), p.get("Author") or p.get("Brand") or None, money(p.get("Price"), "NT$"),
                        note, f"https://24h.pchome.com.tw/prod/{p['Id']}" if p.get("Id") else None))
    return ranked(out)


PCHOME = "https://ecshweb.pchome.com.tw/search/v4.3/all/results?cateid={r}&sort=top/dc&page=1&pageCount=20"
PCHOME_REGIONS: tuple[tuple[str, str, str], ...] = (
    # (field, tab, region id) — 브랜드관이 아닌 상품 분류만 골랐다 (보건 분류의 성인용품 분류는 뺐다)
    ("종합 쇼핑", "장난감", "DEAS"), ("종합 쇼핑", "보드게임", "DEAM"), ("종합 쇼핑", "피규어·모형", "DEEE"),
    ("종합 쇼핑", "유아 수유·외출", "DWAC"), ("종합 쇼핑", "기저귀", "DAAO"), ("종합 쇼핑", "헬스", "DEBY"),
    ("종합 쇼핑", "캠핑", "DEBQ"), ("종합 쇼핑", "자동차용품", "DEAD"), ("종합 쇼핑", "반려동물", "DEAK"),
    ("패션", "의류", "DIAI"), ("패션", "속옷·잠옷", "DIAX"), ("패션", "운동화", "DXAX"), ("패션", "여성 신발", "DIEL"),
    ("패션", "남성 신발", "DIBP"), ("패션", "가방", "DIBM"), ("패션", "시계", "DIAC"), ("패션", "액세서리", "DIAE"),
    ("뷰티", "드럭스토어 스킨케어", "DDAB"), ("뷰티", "백화점 스킨케어", "DDAD"), ("뷰티", "메이크업", "DDBH"),
    ("뷰티", "향수", "DDAH"), ("뷰티", "샴푸", "DAAA"), ("뷰티", "바디케어", "DDAO"), ("뷰티", "미용가전", "DMAH"),
    ("디지털·가전", "노트북", "DHAA"), ("디지털·가전", "안드로이드폰", "DYAW"), ("디지털·가전", "태블릿", "DYAM"),
    ("디지털·가전", "이어폰", "DYAQ"), ("디지털·가전", "스마트워치", "DYAI"), ("디지털·가전", "모니터", "DSAB"),
    ("디지털·가전", "카메라", "DGBQ"), ("디지털·가전", "TV", "DPAD"), ("디지털·가전", "냉장고", "DPAC"),
    ("디지털·가전", "세탁기", "DPAI"), ("디지털·가전", "청소기", "DMAX"), ("디지털·가전", "로봇청소기", "DMBL"),
    ("디지털·가전", "제습기", "DMBQ"), ("디지털·가전", "에어컨", "DPAF"), ("디지털·가전", "주방가전", "DMAG"),
    ("식품", "과자", "DBAC"), ("식품", "수입 과자", "DBAE"), ("식품", "음료", "DBAB"), ("식품", "라면", "DBAY"),
    ("식품", "냉동식품", "DBCP"), ("식품", "커피", "DBAT"), ("식품", "과일·채소", "DBCZ"), ("식품", "육류·해산물", "DBCY"),
    ("식품", "쌀·식재료", "DBBY"), ("식품", "비타민", "DBBC"), ("식품", "유산균", "DBCC"),
    ("생활·리빙", "화장지", "DAAG"), ("생활·리빙", "세제", "DAAK"), ("생활·리빙", "청소용품", "DAAZ"),
    ("생활·리빙", "주방용품", "DEAG"), ("생활·리빙", "냄비·팬", "DEAW"), ("생활·리빙", "텀블러", "DEBW"),
    ("생활·리빙", "침구", "DEBC"), ("생활·리빙", "수납", "DQAU"), ("생활·리빙", "소파·의자", "DQCE"),
    ("생활·리빙", "조명", "DQBP"), ("생활·리빙", "공구", "DQBE"),
    ("게임", "콘솔·게임", "DGBJ"), ("게임", "게임 주변기기", "DGCU"),
)


# ---- 대만 대형 서점: 주간 베스트셀러 (분야별 100위) ----------------------------------------------
def parse_kingstone(raw: str) -> list[Item]:
    out = []
    for chunk in raw.split('<li class="modProList')[1:]:
        rank = num(first(r"TOP<span>(\d+)</span>", chunk))
        a = re.search(r'<div class="modProName">\s*<a href="(/basic/\d+/)[^"]*">(.*?)</a>', chunk, re.S)
        if not rank or not a or "restricted.jpg" in chunk:  # 18금 표지: 이름을 싣지 않는다
            continue
        trend = "상승" if 'class="hotUP"' in chunk else "하락" if 'class="hotDOWN"' in chunk else None
        out.append(item(int(rank), a.group(2), first(r'class="mProBlue"[^>]*>(.*?)</a>', chunk) or None,
                        money(first(r"特價<b>([\d,]+)</b>", chunk), "NT$"), trend,
                        f"https://www.kingstone.com.tw{a.group(1)}"))
    return ranked(out)


KINGSTONE: tuple[tuple[str, str], ...] = (
    ("종합", ""), ("문학", "bbbb"), ("만화", "hhhh"), ("라이트노벨", "qqqq"), ("재테크·경영", "eeee"),
    ("심리·자기계발", "aaaa"), ("어린이", "ssss"), ("생활", "cccc"), ("요리", "tttt"), ("여행", "kkkk"),
)


def boards(country: str) -> list[Board]:
    if country == "TW":
        out = [Board(id=f"tw-mall-{r.lower()}", country="TW", field=fld, card="종합 쇼핑몰 Top", tab=tab,
                     basis="대형 종합 쇼핑몰 분야별 추천 Top (판매·인기 반영)", period="실시간",
                     url=PCHOME.format(r=r), parser="pchome", headers=(("Accept", "application/json"),))
               for fld, tab, r in PCHOME_REGIONS]
        out += [Board(id=f"tw-books-{c or 'all'}", country="TW", field="도서", card="대형 서점 베스트셀러", tab=tab,
                      basis="서점 체인 주간 판매 순위 (18금 도서는 이름을 싣지 않음)", period="주간",
                      url=f"https://www.kingstone.com.tw/bestseller/best/book/{f'category/{c}/' if c else ''}",
                      parser="kingstone", ext="html")
                for tab, c in KINGSTONE]
        return out
    return []  # VN: only the lists every country shares (common.py) — see the module docstring


PARSERS = {"pchome": parse_pchome, "kingstone": parse_kingstone}
TRIMS = {"kingstone": lean_html}
