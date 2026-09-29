"""Nate's JS data file sometimes carries raw control characters inside headlines (09-24 alert)."""

from trend_engine.sources.nate import Nate


def test_parse_tolerates_control_characters_in_strings():
    raw = 'var arrHotRecent = [["1","속보\t헤드라인","s","0","검색어"],["2","둘째","n","0",""]];'
    items = Nate().parse(raw, "KR")
    assert [i.keyword for i in items] == ["속보\t헤드라인", "둘째"]
    assert items[0].meta["query"] == "검색어"
