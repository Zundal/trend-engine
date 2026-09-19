"""Category classifier: each evidence type, the lexicon, disambiguation, and the engine wiring."""

from trend_engine import categories as cat
from trend_engine.config import Settings
from trend_engine.engine import TrendEngine
from trend_engine.store import Store


def test_wiki_category_patterns_and_disambiguation():
    assert cat.wiki_category(["1인칭 슈팅 게임", "2020년 비디오 게임"]) == "게임"
    assert cat.wiki_category(["과일 요리", "중국의 후식"]) == "음식"
    assert cat.wiki_category(["대한민국의 여자 가수", "대한민국의 댄스 음악 가수"]) == "음악"
    assert cat.wiki_category(["동음이의어 문서", "대한민국의 가수"]) is None  # 청하: ambiguous page
    assert cat.wiki_category(["경기도 출신", "조선의 공주"]) is None  # '경기' is a place, not a match
    assert cat.wiki_category(["기술 혁신", "미술가"]) != "음식"  # '술' no longer matches


def test_each_evidence_type_votes():
    topics = {"SPORTS": ["KT 로건 7이닝 무실점…위즈 연승"], "ENTERTAINMENT": ["청하 컴백 확정"]}
    videos = [{"keyword": "아일릿 신곡 MV", "category": "음악", "related": ["아일릿"]}]
    wiki = {"발로란트": ["2020년 비디오 게임"]}
    shop = {"후드집업": "패션의류"}
    assert cat.classify(["KT 로건"], [], topics, [], {}, {})[0] == "스포츠"
    assert cat.classify(["아일릿"], [], {}, videos, {}, {})[0] == "음악"
    assert cat.classify(["발로란트"], [], {}, [], wiki, {}) == ("게임", {"게임": 2 + 1})  # wiki +2, lexicon +1
    assert cat.classify(["후드집업"], [], {}, [], {}, shop) == ("패션·뷰티", {"패션·뷰티": 2})
    assert cat.classify(["석유 최고가격 동결"], [], {}, [], {}, {})[0] == "경제·재테크"  # lexicon
    assert cat.classify(["이선민"], [], {}, [], {}, {}) == ("기타", {})


def test_related_headline_overlap_counts():
    topics = {"NATION": ["여의도역 에스컬레이터 화재로 승객 대피…인명피해 없어"]}
    related = ["여의도역 에스컬레이터 화재 승객 대피"]
    votes = cat.classify(["여의도역 5번 출구"], related, topics, [], {}, {})[1]
    assert votes.get("정치·사회", 0) >= 2


def test_parse_wiki_maps_redirects_back_to_the_query():
    raw = '{"query":{"redirects":[{"from":"롤","to":"리그 오브 레전드"}],"pages":{"1":{"title":"리그 오브 레전드","categories":[{"title":"분류:e스포츠 게임"}]}}}}'
    assert "롤" in cat.parse_wiki(raw)


async def test_engine_attaches_categories_offline():
    rep = await TrendEngine(Settings(offline=True, db_path=":memory:"), Store(":memory:")).collect("KR", save=False)
    labels = [c.category for c in rep.clusters]
    assert all(l in cat.TAXONOMY for l in labels)
    assert sum(l != "기타" for l in labels) >= len(labels) // 2  # recorded evidence classifies most trends
    assert all(c.category_votes or c.category == "기타" for c in rep.clusters)
