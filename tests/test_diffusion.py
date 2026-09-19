"""세대 확산 감지: weekly roll-up, per-age take-off, stage classification, anchor volume."""

from datetime import date, timedelta

from trend_engine import diffusion as dif
from trend_engine.config import Settings
from trend_engine.segments import SegmentProfiler

START = date(2026, 1, 5)  # a Monday


def curve(rise_week: int, weeks: int = 17, base: float = 5.0, top: float = 100.0, fall_after: int | None = None):
    """Daily points: flat `base`, jumps to `top` from rise_week (optionally falls back later)."""
    pts = []
    for d in range(weeks * 7):
        w = d // 7
        on = w >= rise_week and (fall_after is None or w < fall_after)
        pts.append(((START + timedelta(days=d)).strftime("%Y%m%d"), top if on else base))
    return pts


def ages(**rise):
    return {a: curve(rise[a.replace("+", "p")]) for a in dif.AGE_NAMES}


def test_weekly_rolls_up_and_smooths():
    ws = dif.weekly(curve(2, weeks=4))
    assert [w for w, _ in ws] == [START + timedelta(weeks=i) for i in range(4)]
    assert ws[0][1] == 35.0 and ws[2][1] == (35 + 35 + 700) / 3  # 3-week trailing mean


def test_diffusion_in_progress_reports_lag():
    r = dif.analyze(ages(**{"10대": 6, "20대": 5, "30대": 7, "40대": 9, "50대": 10, "60대p": 11}))
    assert r["stage"] == "확산 중"
    assert r["lags"]["20대"] == 0 and r["lags"]["40대"] >= dif.LAG_WEEKS
    assert r["old_lag_weeks"] == r["lags"]["40대"]


def test_simultaneous_news_shock():
    r = dif.analyze(ages(**{k: 8 for k in ("10대", "20대", "30대", "40대", "50대", "60대p")}))
    assert r["stage"] == "전 연령 동시" and r["old_lag_weeks"] is None


def test_waiting_when_only_young_boom():
    series = {a: curve(10) if a in ("10대", "20대") else curve(99) for a in dif.AGE_NAMES}
    assert dif.analyze(series)["stage"] == "확산 대기"


def test_steady_interest_is_not_a_boom():
    flat = [((START + timedelta(days=d)).strftime("%Y%m%d"), 50.0 + (d % 3)) for d in range(119)]
    r = dif.analyze({a: flat for a in dif.AGE_NAMES})
    assert r["stage"] == "상시 관심"


def test_past_boom():
    series = {a: curve(3, fall_after=6) for a in dif.AGE_NAMES}
    assert dif.analyze(series)["stage"] == "지나감"


def test_thin_older_ages_do_not_count():
    series = {a: curve(99) if a in ("10대", "20대") else curve(10) for a in dif.AGE_NAMES}
    loud = dif.analyze(series, volume_pct={a: 1.0 for a in dif.AGE_NAMES})
    assert loud["stage"] == "윗세대 상승"
    thin = dif.analyze(series, volume_pct={a: (1.0 if a in ("10대", "20대") else 0.001) for a in dif.AGE_NAMES})
    assert thin["stage"] == "상시 관심" and thin["ages"]["60대+"]["thin"] is True


def test_older_rising_after_young_adopted_is_flagged():
    series = {a: [((START + timedelta(days=d)).strftime("%Y%m%d"), 50.0) for d in range(119)] if a in ("10대", "20대")
              else curve(12) for a in dif.AGE_NAMES}
    vol = {"10대": 0.5, "20대": 0.1, "30대": 0.02, "40대": 0.015, "50대": 0.01, "60대+": 0.006}
    r = dif.analyze(series, volume_pct=vol)
    assert r["stage"] == "윗세대 상승" and r["young_steady"] is True


async def test_fetch_series_batches_with_anchor_and_volume():
    calls = []

    async def poster(body):
        calls.append(body)
        return {"results": [{"title": g["groupName"], "data": [{"period": "20260105", "ratio": 50.0 if g["groupName"] == "날씨" else 5.0}]}
                            for g in body["keywordGroups"]]}

    prof = SegmentProfiler(Settings(), poster=poster)
    series, vol = await dif.fetch_series(prof, {f"k{i}": [f"k{i}"] for i in range(5)}, "2026-01-05", "2026-01-05")
    assert len(calls) == len(dif.AGES) * 2  # ceil(5/4) batches per age
    assert all(b["keywordGroups"][0]["groupName"] == "날씨" and len(b["keywordGroups"]) <= 5 for b in calls)
    assert vol["k0"]["20대"] == 10.0  # 5 / 50 * 100
    assert set(series["k4"]) == set(dif.AGE_NAMES)


def test_tracked_keywords_prefers_today():
    today = {"groups": {"10대": [{"keyword": "A"}, {"keyword": "B"}], "20대": [{"keyword": "A"}]}}
    month = {"by_segment": {"10대": [{"keyword": "C"}, {"keyword": "B"}]}}
    assert dif.tracked_keywords(today, month) == ["A", "B", "C"]


def test_partial_weeks_are_dropped():
    # starts on a Wednesday and ends on a Tuesday: only the 2 complete Mon–Sun weeks remain
    pts = [((START + timedelta(days=d)).strftime("%Y%m%d"), 10.0) for d in range(2, 23)]
    ws = dif.weekly(pts)
    assert [w for w, _ in ws] == [START + timedelta(weeks=1), START + timedelta(weeks=2)]
    assert all(v == 70.0 for _, v in ws)
