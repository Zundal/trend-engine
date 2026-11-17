"""한국 소비 목록: 포털 쇼핑 구매 순위(연령·성별), 오픈마켓 베스트, 선물하기, 패션·뷰티 플랫폼(연령대별),
장보기, 서점·음반, 극장 관객·예매율, 공연 예매 순위.

조사(2026-11-18, 국내 가정 회선): G마켓·올리브영·쿠팡·오늘의집·SSG·에이블리·CGV 는 봇 차단, W컨셉·교보문고는
키가 필요하고, 지그재그·KREAM·다이소몰은 화면을 스크립트로 그려 받을 곳이 없다.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import httpx

from ..sources.base import SourceError, TransientError, get_text_retry
from .base import BROWSER_UA, Board, Item, clean, first, item, man, money, num, ranked

KST = timezone(timedelta(hours=9))


def won(v) -> str | None:
    return money(v, "", suffix="원")


def _step(delta) -> str | None:
    """+3 -> '3계단 상승' (upstream deltas are 'how far it climbed')."""
    d = int(num(delta) or 0)
    return f"{d}계단 상승" if d > 0 else f"{-d}계단 하락" if d < 0 else None


def _join(*parts) -> str | None:
    return " · ".join(p for p in parts if p) or None


# ---- 포털 쇼핑: 많이 구매한 상품 (연령·성별·분야) ---------------------------------------------
def parse_snx(raw: str) -> list[Item]:
    out = []
    for p in json.loads(raw).get("products") or []:
        if p.get("isAd"):
            continue
        review = f"★{p['reviewScore']} · 리뷰 {p['reviewCount']}" if p.get("reviewScore") and p.get("reviewCount") else None
        out.append(item(p["rank"], p.get("title", ""), p.get("mallNm"), won(p.get("discountPriceValue") or p.get("priceValue")),
                        review, p.get("linkUrl")))
    return ranked(out)


SNX = ("https://snxbest.naver.com/api/v1/snxbest/product/rank?ageType={a}&categoryId={c}"
       "&sortType=PRODUCT_BUY&periodType=DAILY")
SNX_AGES: tuple[tuple[str, str], ...] = (
    ("전체", "ALL"), ("여성", "WOMEN_ALL"), ("남성", "MEN_ALL"), ("10대 여성", "WOMEN_10"), ("10대 남성", "MEN_10"),
    ("20대 여성", "WOMEN_20"), ("20대 남성", "MEN_20"), ("30대 여성", "WOMEN_30"), ("30대 남성", "MEN_30"),
    ("40대 여성", "WOMEN_40"), ("40대 남성", "MEN_40"), ("50대+ 여성", "WOMEN_50"), ("50대+ 남성", "MEN_50"),
)
SNX_CATS: tuple[tuple[str, str, str], ...] = (
    ("패션", "의류", "50000000"), ("패션", "잡화", "50000001"), ("뷰티", "화장품·미용", "50000002"),
    ("디지털·가전", "디지털·가전", "50000003"), ("생활·리빙", "가구·인테리어", "50000004"),
    ("생활·리빙", "생활·건강", "50000008"), ("식품", "식품", "50000006"), ("종합 쇼핑", "출산·육아", "50000005"),
    ("종합 쇼핑", "스포츠·레저", "50000007"), ("종합 쇼핑", "여가·생활편의", "50000009"),
)


# ---- 오픈마켓 베스트 ---------------------------------------------------------------------
def parse_11st(raw: str) -> list[Item]:
    body = raw[raw.find('id="bestPrdList"'):]
    out = []
    for chunk in body.split('<li id="thisClick_')[1:]:
        prd = chunk.split('"', 1)[0]
        rank = num(first(r'<span class="best">(\d+)</span>', chunk))
        if rank:
            out.append(item(int(rank), first(r'<div class="pname">\s*<p>(.*?)</p>', chunk),
                            first(r'<div class="store"[^>]*>\s*<a[^>]*>(.*?)</a>', chunk) or None,
                            won(first(r'class="sale_price">([\d,]+)<', chunk)), None,
                            f"https://www.11st.co.kr/products/{prd}" if prd.isdigit() else None))
    return ranked(out)  # the list is followed by other modules that restart at 1: ranked() stops there


ELEVEN: tuple[tuple[str, str, str], ...] = (
    ("종합 쇼핑", "전체", "0"), ("종합 쇼핑", "유아동", "9"), ("종합 쇼핑", "레저·자동차", "11"),
    ("종합 쇼핑", "해외직구", "14"), ("패션", "브랜드 패션", "4"), ("패션", "의류", "6"), ("패션", "잡화", "7"),
    ("뷰티", "뷰티", "8"), ("디지털·가전", "디지털·가전", "12"), ("식품", "신선식품", "1"), ("식품", "가공식품", "2"),
    ("생활·리빙", "생활용품", "5"), ("생활·리빙", "가구", "10"),
)


def parse_auction(raw: str) -> list[Item]:
    out = []
    for no, rank, name, price in re.findall(
            r'<li class="[^"]*box_best-item-wrap" data-id="([A-Z0-9]+)">.*?<div class="rank">(\d+)</div>'
            r'.*?class="text__item-title"><a [^>]*>(.*?)</a>.*?class="text__normal-price">([\d,]+)</strong>', raw, re.S):
        out.append(item(int(rank), name, None, won(price), None,
                        f"https://itempage3.auction.co.kr/detailview.aspx?ItemNo={no}"))
    return ranked(out)


AUCTION: tuple[tuple[str, str, str], ...] = (
    ("종합 쇼핑", "전체", ""), ("종합 쇼핑", "출산·육아", "31000000"), ("종합 쇼핑", "장난감", "20000000"),
    ("종합 쇼핑", "반려동물", "45000000"), ("종합 쇼핑", "캠핑·낚시", "72000000"), ("종합 쇼핑", "자동차용품", "04000000"),
    ("패션", "여성의류", "12000000"), ("패션", "남성의류", "13000000"), ("패션", "신발", "30000000"),
    ("패션", "가방·잡화", "16000000"), ("패션", "스포츠의류", "37000000"),
    ("뷰티", "화장품·향수", "18000000"), ("뷰티", "바디·헤어", "05000000"),
    ("디지털·가전", "모바일·태블릿", "07000000"), ("디지털·가전", "노트북·PC", "22000000"),
    ("디지털·가전", "영상가전", "29000000"), ("디지털·가전", "생활·미용가전", "71000000"),
    ("디지털·가전", "주방가전", "03000000"), ("디지털·가전", "음향기기", "14000000"),
    ("식품", "신선식품", "51000000"), ("식품", "가공식품", "64000000"), ("식품", "건강식품", "19000000"),
    ("식품", "커피·음료", "38000000"),
    ("생활·리빙", "생활용품", "28000000"), ("생활·리빙", "생필품", "39000000"), ("생활·리빙", "주방용품", "44000000"),
    ("생활·리빙", "가구·DIY", "27000000"), ("생활·리빙", "침구·커튼", "75000000"),
    ("게임", "게임", "15000000"),
)


# ---- 선물하기: 많이 선물한 상품 -------------------------------------------------------------
def parse_gift(raw: str) -> list[Item]:
    out = []
    for i, p in enumerate(json.loads(raw).get("products") or [], 1):
        wish = (p.get("wish") or {}).get("wishCount")
        out.append(item(i, p.get("name", ""), (p.get("brand") or {}).get("name"),
                        won((p.get("price") or {}).get("sellingPrice")), f"위시 {man(wish)}" if man(wish) else None,
                        f"https://gift.kakao.com/product/{p['productId']}" if p.get("productId") else None))
    return ranked(out)


GIFT = "https://gift.kakao.com/a/rank/v1/gift-rank/ranking-tab/category-tab/search"
GIFT_TABS: tuple[tuple[str, str, int], ...] = (
    ("종합 쇼핑", "전체", 11000), ("종합 쇼핑", "유아동", 3), ("종합 쇼핑", "레저·스포츠", 6),
    ("종합 쇼핑", "반려동물", 20), ("패션", "패션", 1), ("패션", "명품", 9), ("뷰티", "뷰티", 2),
    ("디지털·가전", "가전·디지털", 7), ("식품", "식품", 4), ("식품", "건강", 8), ("식품", "주류", 34),
    ("생활·리빙", "리빙", 5),
)


# ---- 패션 플랫폼: 연령대·분야별 랭킹 + 인기 검색어 ----------------------------------------------
def parse_musinsa(raw: str) -> list[Item]:
    out = []
    for m in json.loads(raw)["data"]["modules"]:
        if m.get("type") != "THREECOLUMN":
            continue
        for it in m.get("items") or []:
            if it.get("type") != "PRODUCT_COLUMN":
                continue
            info, img = it.get("info") or {}, it.get("image") or {}
            labels = [x.get("text") for x in img.get("labels") or [] if x.get("text")]
            if num(img.get("rank")):
                out.append(item(int(num(img["rank"])), info.get("productName", ""), info.get("brandName"),
                                won(info.get("finalPrice")), _join(*labels[:2]),
                                f"https://www.musinsa.com/products/{it['id']}" if it.get("id") else None))
    return ranked(out)


MUSINSA = ("https://api.musinsa.com/api2/hm/v5/pans/ranking/sections/199?storeCode=musinsa&categoryCode={c}"
           "&contentsId=&gf=A&ageBand={a}&period=DAILY")
MUSINSA_HEADERS = (("Origin", "https://www.musinsa.com"), ("Referer", "https://www.musinsa.com/"))
MUSINSA_AGES: tuple[tuple[str, str], ...] = (
    ("전체", "AGE_BAND_ALL"), ("19세 이하", "AGE_BAND_MINOR"), ("20~24세", "AGE_BAND_20"), ("25~29세", "AGE_BAND_25"),
    ("30~34세", "AGE_BAND_30"), ("35~39세", "AGE_BAND_35"), ("40세 이상", "AGE_BAND_40"),
)
MUSINSA_CATS: tuple[tuple[str, str, str], ...] = (
    ("패션", "상의", "001"), ("패션", "아우터", "002"), ("패션", "바지", "003"), ("패션", "원피스·스커트", "100"),
    ("패션", "신발", "103"), ("패션", "가방", "004"), ("패션", "모자", "120"), ("패션", "소품", "101"),
    ("패션", "속옷·홈웨어", "026"), ("패션", "스포츠·레저", "017"), ("뷰티", "뷰티", "104"),
)


def parse_musinsa_kw(raw: str) -> list[Item]:
    out = []
    for m in json.loads(raw)["data"]["modules"]:
        if m.get("type") != "RANKING_SEARCH" or not num(m.get("rank")):
            continue
        f = m.get("fluctuation") or {}
        amt = int(num(f.get("amount")) or 0)
        note = {"UP": f"{amt}계단 상승" if amt else "상승", "DOWN": f"{amt}계단 하락" if amt else "하락",
                "NEW": "새로 진입"}.get(f.get("type"))
        out.append(item(int(num(m["rank"])), (m.get("title") or {}).get("text", ""), None, None, note,
                        ((m.get("onClick") or {}).get("url"))))
    return ranked(out)


def parse_29cm(raw: str) -> list[Item]:
    out = []
    for i, p in enumerate(json.loads(raw)["data"]["content"], 1):
        heart = p.get("heartCount")
        out.append(item(i, p.get("itemName", ""), p.get("frontBrandNameKor"), won(p.get("lastSalePrice")),
                        f"찜 {man(heart)}" if man(heart) else None,
                        f"https://www.29cm.co.kr/products/{p['itemNo']}" if p.get("itemNo") else None))
    return ranked(out)


CM29 = "https://recommend-api.29cm.co.kr/api/v4/best/items?categoryList={c}&periodSort=ONE_DAY&limit=30&offset=0"
CM29_CATS: tuple[tuple[str, str, str], ...] = (
    ("패션", "여성 의류", "268100100"), ("패션", "남성 의류", "272100100"), ("패션", "여성 가방", "269100100"),
    ("패션", "여성 신발", "270100100"), ("패션", "남성 신발", "274100100"), ("패션", "주얼리", "305100100"),
    ("뷰티", "뷰티", "266100100"), ("디지털·가전", "디지털", "294100100"), ("디지털·가전", "가전", "293100100"),
    ("생활·리빙", "주방·생활", "292100100"), ("생활·리빙", "가구·인테리어", "291100100"), ("식품", "푸드", "289100100"),
)


# ---- 뷰티: 화장품 리뷰 앱 랭킹 (급상승 · 연령대별) ----------------------------------------------
def parse_hwahae(raw: str) -> list[Item]:
    out = []
    for i, d in enumerate(json.loads(raw)["data"]["details"], 1):
        p, b, g = d.get("product") or {}, d.get("brand") or {}, d.get("goods") or {}
        rating = f"★{p['review_rating']:.2f} · 리뷰 {man(p.get('review_count'))}" if p.get("review_rating") else None
        trend = "새로 진입" if d.get("is_rank_new") else _step(d.get("rank_delta"))
        slug = quote("-".join(f"{b.get('name', '')} {g.get('name') or p.get('name', '')}".split()))
        out.append(item(i, p.get("name", ""), b.get("name"), won(p.get("price")), _join(trend, rating),
                        f"https://www.hwahae.co.kr/goods/{slug}/{g['id']}" if g.get("id") else None))
    return ranked(out)


HWAHAE = "https://gateway.hwahae.co.kr/v14/rankings/{d}/details?page=1&page_size=30"
HWAHAE_TABS: tuple[tuple[str, str, int], ...] = (
    ("급상승", "전체", 5102), ("급상승", "스킨케어", 5104), ("급상승", "클렌징", 5178), ("급상승", "마스크·팩", 5223),
    ("급상승", "선케어", 5297), ("급상승", "베이스 메이크업", 5339), ("급상승", "아이 메이크업", 5414),
    ("급상승", "립 메이크업", 5446), ("급상승", "바디", 5470), ("급상승", "헤어", 5507), ("급상승", "향수", 5551),
    ("급상승", "이너뷰티", 5569), ("연령대별", "10대", 1372), ("연령대별", "20대", 1543), ("연령대별", "30대", 1714),
    ("연령대별", "40대 이상", 1885),
)


# ---- 장보기 ----------------------------------------------------------------------------
def parse_kurly(raw: str) -> list[Item]:
    out = []
    for i, p in enumerate(json.loads(raw).get("data") or [], 1):
        if p.get("is_only_adult"):
            continue
        rc = p.get("review_count")
        out.append(item(i, p.get("name", ""), None, won(p.get("discounted_price") or p.get("sales_price")),
                        f"후기 {rc}" if rc and rc != "0" else None,
                        f"https://www.kurly.com/goods/{p['no']}" if p.get("no") else None))
    return ranked(out)


KURLY = ("https://api.kurly.com/collection/v2/home/sites/market/product-collections/market-best/products"
         "?sort_type=4&page=1&per_page=30{f}")
KURLY_CATS: tuple[tuple[str, str], ...] = (
    ("전체", ""), ("과일·쌀", "908"), ("채소", "907"), ("정육", "910"), ("수산", "909"), ("국·반찬", "911"),
    ("간편식", "912"), ("면·양념", "913"), ("유제품", "018"), ("베이커리", "915"), ("건강식품", "032"),
    # 간식·음료·커피 분류는 베스트가 10개도 안 돼 뺐다 (2026-11-18)
)


# ---- 도서 · 음반 -------------------------------------------------------------------------
def parse_yes24(raw: str) -> list[Item]:
    body = raw[raw.find('id="yesBestList"'):]
    out = []
    for chunk in re.split(r'<li class="[^"]*" data-goods-no="', body)[1:]:
        no = chunk.split('"', 1)[0]
        rank = num(first(r'<em class="ico rank">(\d+)</em>', chunk))
        if not rank:
            continue
        ch = re.search(r'<span class="rank_info (rank_\w+)">.*?<em class="txt rank">([^<]*)</em>', chunk, re.S)
        trend = None
        if ch:
            amt = int(num(ch.group(2)) or 0)
            trend = {"rank_up": f"{amt}계단 상승" if amt else "상승", "rank_dn": f"{amt}계단 하락" if amt else "하락",
                     "rank_new": "새로 진입"}.get(ch.group(1))
        author = clean(first(r'class="authPub info_auth"[^>]*>(.*?)</span>', chunk))
        pub = clean(first(r'class="authPub info_pub"[^>]*>(.*?)</span>', chunk))
        out.append(item(int(rank), first(r'class="gd_name"[^>]*>(.*?)</a>', chunk), author or pub or None,
                        won(first(r'class="txt_num"><em class="yes_b">([\d,]+)</em>', chunk)),
                        _join(pub if author else None, trend),
                        f"https://www.yes24.com/product/goods/{no}" if no.isdigit() else None))
    return ranked(out)


YES24 = "https://www.yes24.com/Product/Category/BestSeller?categoryNumber={c}&pageNumber=1&pageSize=24"


def parse_aladin(raw: str) -> list[Item]:
    out = []
    for chunk in raw.split('class="ss_book_box" itemId="')[1:]:
        iid = chunk.split('"', 1)[0]
        rank = num(first(r'<div style="text-align: center;">(\d+)\.</div>', chunk))
        name = first(r'class="bo3">(.*?)</a>', chunk)
        if not rank or not name:
            continue
        authors = [clean(a) for a in re.findall(r'AuthorSearch=[^"]*"[^>]*>(.*?)</a>', chunk)]
        point = first(r'class="sales_point">\s*([\d,]+)', chunk)
        out.append(item(int(rank), name, ", ".join(dict.fromkeys(a for a in authors if a)) or None,
                        won(first(r'class="ss_p2"\s*><em>([\d,]+)원', chunk)),
                        f"판매 지수 {man(point)}" if man(point) else None,
                        f"https://www.aladin.co.kr/shop/wproduct.aspx?ItemId={iid}" if iid.isdigit() else None))
    return ranked(out)


ALADIN = "https://www.aladin.co.kr/shop/common/wbest.aspx?BestType=Bestseller&BranchType=1&CID={c}"
ALADIN_CATS: tuple[tuple[str, str], ...] = (
    ("종합", "0"), ("소설·시", "1"), ("에세이", "55889"), ("장르소설", "112011"), ("경제경영", "170"),
    ("자기계발", "336"), ("인문", "656"), ("역사", "74"), ("과학", "987"), ("만화·라이트노벨", "2551"),
    ("어린이", "1108"), ("청소년", "1137"), ("요리·살림", "1230"), ("여행", "1196"), ("수험서", "1383"),
)


def parse_ridi(raw: str) -> list[Item]:
    data = json.loads(first(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', raw))
    rows: list = []
    for q in data["props"]["pageProps"]["dehydratedState"]["queries"]:
        if q.get("queryKey", [None])[0] == "BestSellers":
            rows = _find_books(q["state"]["data"]) or []
            break
    out = []
    for i, r in enumerate(rows, 1):
        b = r.get("book") or {}
        if b.get("adultOnly") or b.get("isAdultOnly"):
            continue
        title = b.get("title") or {}
        authors = [a["name"] for a in b.get("authors") or [] if a.get("role") in ("AUTHOR", "COMIC_AUTHOR", None)]
        price = (((b.get("priceInfo") or {}).get("purchase") or {}).get("sellingPrice"))
        out.append(item(i, title.get("main") if isinstance(title, dict) else str(title), ", ".join(authors[:2]) or None,
                        won(price), None, f"https://ridibooks.com/books/{b['id']}" if b.get("id") else None))
    return ranked(out)


def _find_books(o):
    if isinstance(o, dict):
        for v in o.values():
            if isinstance(v, list) and v and isinstance(v[0], dict) and "book" in v[0]:
                return v
            if (r := _find_books(v)) is not None:
                return r
    return None


RIDI: tuple[tuple[str, str], ...] = (("일반", "general"), ("판타지", "fantasy"))  # 로맨스는 세트 상품뿐, 만화는 404


# ---- 영화: 어제 관객 · 실시간 예매율 (전국 극장 통합 집계) ---------------------------------------
def parse_kobis(raw: str) -> list[Item]:
    i = raw.find("<tbody")
    body = raw[i: raw.find("</tbody>", i)]  # the first table only: the day's top 10 / every film on sale
    booking = "예매율" in raw[:i][-6000:]
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.S):
        tds = [clean(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        title = first(r'<a [^>]*title="([^"]+)"', tr)
        if len(tds) < 8 or not num(tds[0]) or not title:
            continue
        if booking:  # 순위 영화명 개봉일 예매율 예매매출 누적매출 예매관객 누적관객
            note = _join(f"예매율 {tds[3]}", f"예매 {man(tds[6])}명" if man(tds[6]) else None,
                         f"누적 {man(tds[7])}명" if man(tds[7]) else "개봉 전")
        else:  # 순위 영화명 개봉일 매출 점유율 매출증감 누적매출 관객 관객증감 누적관객 스크린 상영
            note = _join(f"관객 {man(tds[7])}명" if man(tds[7]) else None, f"누적 {man(tds[9])}명" if man(tds[9]) else None,
                         f"점유율 {tds[4]}")
        out.append(item(int(num(tds[0])), title, f"{tds[2]} 개봉" if re.match(r"\d{4}-", tds[2]) else None, None, note))
    return ranked(out)


async def fetch_kobis(client: httpx.AsyncClient, b: Board) -> str:
    """The stats pages answer a POST carrying the CSRF token of the GET before it (same cookie jar)."""
    headers = {"User-Agent": BROWSER_UA}
    page = await get_text_retry(client, b.url, retries=1, base_wait=3.0, headers=headers)
    token = first(r'name="CSRFToken" value="([^"]+)"', page)
    if not token:
        raise SourceError("no CSRF token on the stats page")
    form = {"CSRFToken": token, "loadEnd": "0", **dict(b.form)}
    if "Daily" in b.url:
        day = (datetime.now(KST) - timedelta(days=1)).strftime("%Y-%m-%d")
        form |= {"searchType": "search", "sSearchFrom": day, "sSearchTo": day}
    r = await client.post(b.url, data=form, headers=headers | {"Referer": b.url})
    if r.status_code >= 400:
        raise (TransientError if r.status_code in (403, 429, 500, 502, 503, 504) else SourceError)(
            f"HTTP {r.status_code} from {b.url.split('?')[0]}")
    return r.text


KOBIS = "https://www.kobis.or.kr/kobis/business/stat/boxs/{p}.do"


# ---- 공연: 예매 순위 -----------------------------------------------------------------------
def parse_tickets(raw: str) -> list[Item]:
    out = []
    for r in (json.loads(raw).get("data") or {}).get("content") or []:
        rk = r.get("ranking") or {}
        start, end = (r.get("playStartDate") or "")[5:].replace("-", "."), (r.get("playEndDate") or "")[5:].replace("-", ".")
        when = start if start == end else f"{start}~{end}" if start else None
        prev = rk.get("prevRankingNo")
        trend = "새로 진입" if prev == 0 else None if not prev or prev == r.get("rankingNo") else f"지난 {prev}위"
        out.append(item(r.get("rankingNo") or 0, r.get("goodsName", ""), r.get("placeName"), None,
                        _join(f"예매 점유 {rk['bookingRate']}%" if rk.get("bookingRate") else None, when, trend),
                        f"https://tickets.interpark.com/goods/{r['goodsCode']}" if r.get("goodsCode") else None))
    return ranked(out)


TICKETS = "https://nol.yanolja.com/ticket/display/api/ent/x01/v2/ranking?genreType={g}&languageType=KR&page=0&size=30"
TICKET_GENRES: tuple[tuple[str, str], ...] = (
    ("뮤지컬", "MUSICAL"), ("콘서트", "CONCERT"), ("연극", "DRAMA"), ("클래식·무용", "CLASSIC_DANCE"),
    ("전시·행사", "EXHIBIT"), ("아동·가족", "KIDS"), ("스포츠", "SPORTS"),
)


# ---- fixture trims (record only) ------------------------------------------------------------
def _cut_html(start: str, marker: str, n: int = 24):
    def trim(raw: str) -> str:
        body = raw[raw.find(start):] if start in raw else raw
        parts = body.split(marker)
        return marker.join(parts[: n + 1])
    return trim


def _cut_json(path: tuple[str, ...], n: int = 24):
    def trim(raw: str) -> str:
        d = json.loads(raw)
        node = d
        for k in path[:-1]:
            node = node[k]
        node[path[-1]] = node[path[-1]][:n]
        return json.dumps(d, ensure_ascii=False)
    return trim


def _trim_musinsa(raw: str) -> str:
    d = json.loads(raw)
    keep, n = [], 0
    for m in d["data"]["modules"]:
        if m.get("type") in ("THREECOLUMN", "RANKING_SEARCH") and n < 24:
            keep.append(m)
            n += len(m.get("items") or [1])
    d["data"]["modules"] = keep
    return json.dumps(d, ensure_ascii=False)


def _trim_auction(raw: str) -> str:
    i = raw.rfind("<li", 0, raw.find("box_best-item-wrap"))
    return "box_best-item-wrap".join(raw[i:].split("box_best-item-wrap")[:26])


def _trim_kobis(raw: str) -> str:
    i = raw.find("<tbody")
    rows = raw[i: raw.find("</tbody>", i)].split("<tr")
    return raw[max(0, raw.rfind("<thead", 0, i)): i] + "<tr".join(rows[:31]) + "</tbody>"


def _trim_yes24(raw: str) -> str:
    raw = re.sub(r"<script.*?</script>|<img [^>]*>|<!--.*?-->", "", raw, flags=re.S)
    return re.sub(r"\s+", " ", _cut_html('id="yesBestList"', 'data-goods-no="')(raw))


def _trim_ridi(raw: str) -> str:
    data = json.loads(first(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', raw))
    qs = [q for q in data["props"]["pageProps"]["dehydratedState"]["queries"] if q.get("queryKey", [None])[0] == "BestSellers"]
    rows = _find_books(qs[0]["state"]["data"]) if qs else None
    if rows:
        del rows[24:]
        for r in rows:  # long blurbs are most of the page
            (r.get("book") or {}).pop("introduction", None)
    data["props"]["pageProps"] = {"dehydratedState": {"queries": qs}}
    return f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(data, ensure_ascii=False)}</script>'


TRIMS = {
    "snx": _cut_json(("products",)), "11st": _cut_html('id="bestPrdList"', '<li id="thisClick_'),
    "auction": _trim_auction, "gift": _cut_json(("products",)),
    "musinsa": _trim_musinsa, "musinsa_kw": _trim_musinsa, "29cm": _cut_json(("data", "content")),
    "hwahae": _cut_json(("data", "details")), "kurly": _cut_json(("data",)),
    "yes24": _trim_yes24, "aladin": _cut_html('class="ss_book_box"', 'class="ss_book_box" itemId="'),
    "ridi": _trim_ridi, "kobis": _trim_kobis, "tickets": _cut_json(("data", "content")),
}


def boards(country: str) -> list[Board]:
    if country != "KR":
        return []
    snx_h = (("Referer", "https://snxbest.naver.com/"),)
    out = [Board(id=f"kr-shop-{a.lower()}", country="KR", field="종합 쇼핑", card="쇼핑 많이 산 상품", tab=tab,
                 basis="포털 쇼핑에서 오늘 많이 구매한 상품 (연령·성별)", period="일간",
                 url=SNX.format(a=a, c="A"), parser="snx", headers=snx_h)
           for tab, a in SNX_AGES]
    out += [Board(id=f"kr-shop-{c}", country="KR", field=fld, card="쇼핑 많이 산 상품", tab=tab,
                  basis="포털 쇼핑에서 오늘 많이 구매한 상품", period="일간",
                  url=SNX.format(a="ALL", c=c), parser="snx", headers=snx_h)
            for fld, tab, c in SNX_CATS]
    out += [Board(id=f"kr-open-{n}", country="KR", field=fld, card="오픈마켓 베스트", tab=tab,
                  basis="대형 오픈마켓 베스트 (판매·클릭 반영)", period="실시간",
                  url=f"https://www.11st.co.kr/browsing/BestSeller.tmall?method=getBestSellerMain&cornerNo={n}",
                  parser="11st", ext="html", encoding="cp949")
            for fld, tab, n in ELEVEN]
    out += [Board(id=f"kr-market-{c or 'all'}", country="KR", field=fld, card="오픈마켓 분야별 베스트", tab=tab,
                  basis="오픈마켓 분야별 판매 베스트", period="실시간",
                  url=f"https://corners.auction.co.kr/corner/categorybest.aspx{f'?category={c}' if c else ''}",
                  parser="auction", ext="html", encoding="cp949")
            for fld, tab, c in AUCTION]
    out += [Board(id=f"kr-gift-{n}", country="KR", field=fld, card="많이 선물한 상품", tab=tab,
                  basis="메신저 선물하기에서 많이 선물한 상품", period="실시간", url=GIFT, parser="gift",
                  method="POST", body=json.dumps({"navId": n, "page": 0, "size": 30}))
            for fld, tab, n in GIFT_TABS]
    out += [Board(id=f"kr-fashion-age-{a.lower()}", country="KR", field="패션", card="패션 플랫폼 연령대별 랭킹",
                  tab=tab, basis="패션 플랫폼 오늘 판매·조회 랭킹 (연령대별)", period="일간",
                  url=MUSINSA.format(c="000", a=a), parser="musinsa", headers=MUSINSA_HEADERS)
            for tab, a in MUSINSA_AGES]
    out += [Board(id=f"kr-fashion-{c}", country="KR", field=fld, card="패션 플랫폼 분야별 랭킹", tab=tab,
                  basis="패션 플랫폼 오늘 판매·조회 랭킹", period="일간",
                  url=MUSINSA.format(c=c, a="AGE_BAND_ALL"), parser="musinsa", headers=MUSINSA_HEADERS)
            for fld, tab, c in MUSINSA_CATS]
    out += [Board(id="kr-fashion-keywords", country="KR", field="패션", card="패션 인기 검색어", tab="지금",
                  basis="패션 플랫폼에서 많이 찾은 검색어", period="실시간",
                  url="https://api.musinsa.com/api2/hm/v5/pans/ranking?storeCode=musinsa&subPan=keyword",
                  parser="musinsa_kw", headers=MUSINSA_HEADERS)]
    out += [Board(id=f"kr-select-{c}", country="KR", field=fld, card="디자이너 편집숍 베스트", tab=tab,
                  basis="온라인 편집숍 하루 판매 베스트", period="일간", url=CM29.format(c=c), parser="29cm")
            for fld, tab, c in CM29_CATS]
    out += [Board(id=f"kr-beauty-{d}", country="KR", field="뷰티", card=f"화장품 랭킹 · {grp}", tab=tab,
                  basis="화장품 리뷰 앱 랭킹 (리뷰·조회 반영, " + ("급상승" if grp == "급상승" else "연령대별") + ")",
                  period="주간", url=HWAHAE.format(d=d), parser="hwahae", ttl=timedelta(hours=12))
            for grp, tab, d in HWAHAE_TABS]
    out += [Board(id=f"kr-grocery-{c or 'all'}", country="KR", field="식품", card="새벽배송 장보기 베스트", tab=tab,
                  basis="신선식품 장보기 판매 베스트", period="실시간",
                  url=KURLY.format(f=f"&filters=category%3A{c}" if c else ""), parser="kurly")
            for tab, c in KURLY_CATS]
    out += [Board(id=f"kr-books-{c}", country="KR", field="도서", card="온라인 서점 주간 베스트", tab=tab,
                  basis="온라인 서점 주간 판매 순위", period="주간", url=ALADIN.format(c=c), parser="aladin", ext="html",
                  ttl=timedelta(hours=12))
            for tab, c in ALADIN_CATS]
    out += [Board(id="kr-books-yes-001", country="KR", field="도서", card="온라인 서점 실시간 베스트", tab="국내도서",
                  basis="온라인 서점 판매 순위", period="실시간", url=YES24.format(c="001"), parser="yes24", ext="html"),
            Board(id="kr-books-yes-017", country="KR", field="도서", card="온라인 서점 실시간 베스트", tab="전자책",
                  basis="온라인 서점 판매 순위", period="실시간", url=YES24.format(c="017"), parser="yes24", ext="html")]
    out += [Board(id=f"kr-ebooks-{g}", country="KR", field="도서", card="전자책 주간 베스트", tab=tab,
                  basis="전자책 서점 주간 판매 순위", period="주간",
                  url=f"https://ridibooks.com/bestsellers/{g}?order=weekly", parser="ridi", ext="html",
                  ttl=timedelta(hours=12))
            for tab, g in RIDI]
    out += [Board(id="kr-albums", country="KR", field="음악", card="음반 판매 (CD·LP)", tab="음반",
                  basis="온라인 서점 음반 판매 순위", period="실시간", url=YES24.format(c="003"), parser="yes24", ext="html"),
            Board(id="kr-videos", country="KR", field="영화", card="영상물 판매 (DVD·블루레이)", tab="영상물",
                  basis="온라인 서점 영상물 판매 순위", period="실시간", url=YES24.format(c="004"), parser="yes24",
                  ext="html")]
    out += [Board(id="kr-boxoffice-booking", country="KR", field="영화", card="박스오피스", tab="실시간 예매율",
                  basis="전국 극장 통합 집계 · 지금 예매율", period="실시간",
                  url=KOBIS.format(p="findRealTicketList"), parser="kobis", ext="html", fetcher="kobis",
                  form=(("dmlMode", "search"), ("wideareaAll", "ALL"), ("allMovieYn", "Y")), ttl=timedelta(hours=2)),
            Board(id="kr-boxoffice-daily", country="KR", field="영화", card="박스오피스", tab="어제 관객",
                  basis="전국 극장 통합 집계 · 어제 관객 수", period="일간",
                  url=KOBIS.format(p="findDailyBoxOfficeList"), parser="kobis", ext="html", fetcher="kobis",
                  ttl=timedelta(hours=6))]
    out += [Board(id=f"kr-tickets-{g.lower()}", country="KR", field="공연", card="공연 예매 순위", tab=tab,
                  basis="티켓 예매처 하루 예매 순위 (예매 점유율)", period="일간", url=TICKETS.format(g=g),
                  parser="tickets")
            for tab, g in TICKET_GENRES]
    return out


PARSERS = {"snx": parse_snx, "11st": parse_11st, "auction": parse_auction, "gift": parse_gift,
           "musinsa": parse_musinsa, "musinsa_kw": parse_musinsa_kw, "29cm": parse_29cm, "hwahae": parse_hwahae,
           "kurly": parse_kurly, "yes24": parse_yes24, "aladin": parse_aladin, "ridi": parse_ridi,
           "kobis": parse_kobis, "tickets": parse_tickets}
FETCHERS = {"kobis": fetch_kobis}
