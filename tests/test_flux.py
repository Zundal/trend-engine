"""교체율·쏠림: pure math on daily rank lists, plus the pageviews parsers that feed them."""

from datetime import date, timedelta

import pytest

from trend_engine import flux
from trend_engine.config import Settings
from trend_engine.pageviews import History, days_back, parse_article, parse_top

TOP_RESPONSE = """{"items":[{"articles":[
  {"article":"\\uc704\\ud0a4\\ubc31\\uacfc:\\ub300\\ubb38","views":900,"rank":1},
  {"article":"\\ub300\\ubb38","views":800,"rank":2},
  {"article":"A","views":100,"rank":3},
  {"article":"B","views":50,"rank":4}]}]}"""


def test_parse_top_drops_portal_noise_and_keeps_counts():
    assert parse_top(TOP_RESPONSE) == [("A", 100), ("B", 50)]


def test_parse_article_fills_missing_days_with_zero():
    raw = '{"items":[{"timestamp":"2026010100","views":5},{"timestamp":"2026010300","views":7}]}'
    assert parse_article(raw, date(2026, 1, 1), date(2026, 1, 3)) == [
        (date(2026, 1, 1), 5), (date(2026, 1, 2), 0), (date(2026, 1, 3), 7)]


def test_turnover_counts_only_the_top_n():
    today = ["a", "b", "c", "x"]
    assert flux.turnover(today, ["a", "b", "c", "d"], n=3) == 0.0  # the newcomer is below the cut
    assert flux.turnover(today, ["d", "e", "f", "a"], n=3) == 1.0
    assert flux.turnover(["a", "b"], ["a", "b"], n=3) is None  # too short to judge


def test_concentration_is_the_top_n_share_of_views():
    rows = [("a", 60), ("b", 30), ("c", 10)]
    assert flux.concentration(rows, n=1) == pytest.approx(0.6)
    assert flux.concentration(rows, n=2) == pytest.approx(0.9)


def _days(n: int, make) -> dict[date, list[tuple[str, int]]]:
    start = date(2026, 1, 1)
    return {start + timedelta(days=i): make(i) for i in range(n)}


def test_summary_reports_today_against_the_countrys_own_median():
    # 20 quiet days (nothing moves), then a day where the whole top 10 is new and lopsided
    def quiet(i):
        return [(f"a{k}", 100) for k in range(20)]

    by_day = _days(20, quiet)
    last = max(by_day) + timedelta(days=1)
    by_day[last] = [("new0", 5000)] + [(f"new{k}", 10) for k in range(1, 20)]
    s = flux.summary(flux.daily(by_day))

    assert s["turnover"]["value"] == 1.0 and s["turnover"]["new_of_n"] == 10
    assert s["turnover"]["label"] == "평소보다 빠른 교체"
    assert s["concentration"]["label"] == "한 곳에 쏠림"
    assert s["concentration"]["gap_pp"] > 0
    assert len(s["spark"]) <= 42


def test_summary_needs_two_weeks_before_it_says_anything():
    assert flux.summary(flux.daily(_days(10, lambda i: [(f"a{k}", 10) for k in range(20)]))) is None


def test_trend_compares_two_windows_and_stays_quiet_when_short():
    rows = flux.daily(_days(30, lambda i: [(f"a{k}", 10) for k in range(20)]))
    assert flux.trend(rows, window=180) is None
    # alternating lists: every other day the top 3 is entirely new
    def flip(i):
        return [(f"{'x' if i % 2 else 'y'}{k}", 10) for k in range(20)]

    rows = flux.daily(_days(40, flip))
    t = flux.trend(rows, window=10)
    assert t["then"]["median"] == 1.0 and t["now"]["median"] == 1.0 and t["change_pp"] == 0.0


def test_days_back_ends_yesterday_because_today_is_still_filling():
    got = days_back(3, today=date(2026, 3, 10))
    assert got == [date(2026, 3, 7), date(2026, 3, 8), date(2026, 3, 9)]


@pytest.mark.asyncio
async def test_offline_history_reads_fixtures_and_never_touches_the_network(tmp_path):
    fx = tmp_path / "pageviews"
    fx.mkdir()
    (fx / "ko-top.json").write_text('{"2026-03-09": [["A", 10], ["\\ub300\\ubb38", 99]]}', encoding="utf-8")
    (fx / "ko-articles.json").write_text('{"A": {"items":[{"timestamp":"2026030900","views":4}]}}', encoding="utf-8")
    settings = Settings(offline=True, fixtures_dir=fx.parent)

    async with History(settings) as h:
        assert await h.top("ko", date(2026, 3, 9)) == [("A", 10)]  # 대문 filtered out
        assert await h.article("ko", "A", date(2026, 3, 9), date(2026, 3, 9)) == [(date(2026, 3, 9), 4)]
        assert await h.top("ko", date(2026, 3, 8)) == []  # no fixture for that day -> empty, not a crash
