from trend_engine.config import Settings
from trend_engine.seoul import Hotspot, annotate_skew, parse_citydata


def test_parse_sample_fixture():
    raw = (Settings().fixtures_dir / "seoul_citydata" / "sample.json").read_text(encoding="utf-8")
    spot = parse_citydata(raw, requested="강남역")
    assert spot.name == "광화문·덕수궁"
    assert spot.sample is True  # asked for 강남역, got the fixed sample place
    assert abs(sum(spot.ages.values()) - 100) < 1.5
    assert spot.forecast


def _spot(name, twenties):
    ages = {k: 10.0 for k in ["10세 미만", "10대", "20대", "30대", "40대", "50대", "60대", "70대+"]}
    ages["20대"] = twenties
    return Hotspot(name, "", "", "", 0, 0, 50, 50, ages, 0, "")


def test_age_skew_finds_over_represented_group():
    spots = [_spot("홍대", 40), _spot("종로", 5), _spot("여의도", 15)]
    annotate_skew(spots)
    assert spots[0].dominant_group == "20대"
    assert spots[0].age_skew["20대"] == 20.0
