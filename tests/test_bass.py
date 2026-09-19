"""Bass model: recovers known parameters and forecasts an older age's peak from partial data."""

from datetime import date, timedelta

from trend_engine import bass

W0 = date(2026, 1, 5)
WEEKS = [W0 + timedelta(weeks=i) for i in range(30)]


def curve(p, q, t0, m=1000.0, n=30, base=5.0):
    return [base + m * bass.shape(p, q, i - t0) for i in range(n)]


def test_fit_recovers_peak_timing():
    p, q, t0 = 0.02, 0.6, 4
    f = bass.fit(curve(p, q, t0))
    true_peak = t0 + bass.peak_time(p, q)
    assert abs((f["t0"] + bass.peak_time(f["p"], f["q"])) - true_peak) <= 1.0
    assert f["r2"] > 0.95


def test_forecasts_older_peak_before_it_happens():
    p, q = 0.02, 0.6
    young = curve(p, q, 2)
    old_full = curve(p, q, 9)            # older age: same shape, 7 weeks later
    true_peak = 9 + bass.peak_time(p, q)
    cut = 12                             # we only see the older age's early rise
    fc = bass.forecast(WEEKS[:cut], young[:cut + 6], {"50대": old_full[:cut]})
    got = fc["ages"]["50대"]
    assert got["method"] == "lag"
    predicted = (date.fromisoformat(got["peak"]) - W0).days / 7
    assert abs(predicted - true_peak) <= 2.0


def test_young_peak_uses_observation_once_past_and_bass_while_rising():
    full = curve(0.02, 0.6, 2)
    assert bass.young_peak(full)[1] == "observed"
    rising = curve(0.02, 0.6, 2)[:7]      # still climbing
    pk, how = bass.young_peak(rising)
    assert how == "bass" and abs(pk - (2 + bass.peak_time(0.02, 0.6))) <= 1.5


def test_typical_lag_when_older_has_not_started():
    young = curve(0.02, 0.6, 2)
    fc = bass.forecast(WEEKS, young, {"60대+": [5.0] * 30}, typical_lag={"60대+": 4})
    assert fc["ages"]["60대+"]["method"] == "typical" and fc["ages"]["60대+"]["lag_vs_young"] == 4


def test_no_forecast_without_a_young_rise():
    assert bass.forecast(WEEKS, [5.0] * 30, {"50대": [5.0] * 30})["ages"] == {}
