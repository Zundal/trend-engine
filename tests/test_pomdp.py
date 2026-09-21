"""POMDP over diffusion stages: filtering, learning, alert gating and measurement allocation."""

import random
from datetime import date, timedelta

from trend_engine import pomdp

WAIT, SPREAD, UP, ALL, PAST, FLAT = pomdp.VERDICTS


def test_matrices_are_stochastic_and_labels_match_prior():
    for row in pomdp.PRIOR_T + pomdp.PRIOR_O:
        assert abs(sum(row) - 1) < 1e-9 and all(v > 0 for v in row)
    # the phase names are defined by which verdict each phase mostly produces
    assert [pomdp.VERDICTS[max(range(6), key=lambda j: row[j])] for row in pomdp.PRIOR_O] == \
        [FLAT, WAIT, SPREAD, ALL, PAST]


def test_update_moves_belief_toward_the_observed_phase():
    b = pomdp.Belief.initial()
    for _ in range(3):
        b = b.update(WAIT, days=7)
    assert b.phase == "청년 상승" and b.confidence > 0.6
    b2 = b.update(SPREAD, days=7).update(SPREAD, days=7)
    assert b2.phase == "확산"


def test_one_noisy_verdict_does_not_flip_a_confident_belief():
    b = pomdp.Belief.initial()
    for _ in range(5):
        b = b.update(WAIT, days=7)
    flipped = b.update(FLAT, days=1)  # a single "상시 관심" the next day
    assert flipped.phase == "청년 상승"  # still — that is the whole point
    assert flipped.confidence < b.confidence  # but less sure


def test_days_between_runs_scale_the_transition():
    b = pomdp.Belief.initial()
    for _ in range(5):
        b = b.update(WAIT, days=7)
    week = b.predict(days=7)
    day = b.predict(days=1)
    assert day.b[1] > week.b[1] > b.predict(days=28).b[1]  # more time -> more diffusion of belief
    assert abs(sum(week.b) - 1) < 1e-9


def test_belief_roundtrips_through_json():
    b = pomdp.Belief.initial().update(SPREAD, days=7)
    d = b.to_dict()
    assert set(d) >= {"b", "phase", "confidence", "updated", "streak"}
    back = pomdp.Belief.from_dict(d)
    assert all(abs(x - y) < 1e-3 for x, y in zip(back.b, b.b)) and back.phase == b.phase


def _sample(T, O, n, rnd):
    s = 0
    out = []
    for _ in range(n):
        s = rnd.choices(range(len(T)), T[s])[0]
        out.append(rnd.choices(range(len(O[0])), O[s])[0])
    return out


def test_fit_learns_from_sequences_but_keeps_labels():
    rnd = random.Random(7)
    # planted world: 청년 상승 phase lasts much longer than the prior thinks
    T = [row[:] for row in pomdp.PRIOR_T]
    T[1] = [0.01, 0.95, 0.02, 0.01, 0.01]
    seqs = [_sample(T, pomdp.PRIOR_O, 40, rnd) for _ in range(60)]
    m = pomdp.fit(seqs, iterations=30)
    assert m.T[1][1] > pomdp.PRIOR_T[1][1] + 0.05  # moved toward the data
    assert m.sequences == 60 and m.label_locked is False
    for i, row in enumerate(m.O):  # labels still mean what the prior says
        assert max(range(6), key=lambda j: row[j]) == max(range(6), key=lambda j: pomdp.PRIOR_O[i][j])
    for row in m.T + m.O:
        assert abs(sum(row) - 1) < 1e-9


def test_fit_with_no_data_returns_the_prior():
    m = pomdp.fit([])
    assert m.T == pomdp.PRIOR_T and m.O == pomdp.PRIOR_O and m.sequences == 0


def test_fit_reverts_when_labels_would_flip():
    # every sequence says "상시 관심" then "확산 대기" forever: EM wants to relabel; we refuse
    seqs = [[5] * 3 + [0] * 30 for _ in range(30)]
    m = pomdp.fit(seqs, iterations=50, prior_weight=0.1)
    assert m.label_locked is True
    assert m.O == pomdp.PRIOR_O


def test_filter_sequence_is_causal_and_scores_flips():
    verdicts = [FLAT, WAIT, FLAT, WAIT, WAIT, WAIT, FLAT, WAIT, WAIT, SPREAD, SPREAD]
    phases = pomdp.filter_sequence(verdicts)
    assert len(phases) == len(verdicts)
    assert pomdp.flips(verdicts) > pomdp.flips(phases)  # smoother than the raw verdicts
    # causal: a prefix gives the same phases
    assert pomdp.filter_sequence(verdicts[:5]) == phases[:5]


def test_plan_holds_pending_keywords_and_rests_settled_ones():
    today = date(2026, 9, 21)
    pending = pomdp.Belief.initial()
    for _ in range(4):
        pending = pending.update(WAIT, days=7)
    settled = pomdp.Belief.initial()
    for _ in range(6):
        settled = settled.update(FLAT, days=7)
    settled = settled.stamp(date(2026, 9, 20))
    pending = pending.stamp(date(2026, 9, 20))
    beliefs = {"뜨는중": pending, "게임": settled, "옛것": settled.stamp(date(2026, 9, 1))}
    got = pomdp.plan(beliefs, ["게임", "새후보1", "옛것", "새후보2", "새후보3"], pinned=["내브랜드"], limit=5, today=today)
    assert got[0] == "내브랜드" and got[1] == "뜨는중"  # pinned, then held (not even a candidate today)
    assert "게임" not in got  # settled and measured yesterday: rest
    assert "옛것" in got  # settled but not measured for 3 weeks: due again
    assert len(got) == 5 and len(set(got)) == 5


def test_plan_without_beliefs_is_the_candidate_order():
    assert pomdp.plan({}, ["a", "b", "c"], pinned=["p"], limit=3, today=date(2026, 9, 21)) == ["p", "a", "b"]


def test_gate_only_passes_confident_alert_phases():
    b = pomdp.Belief.initial()
    assert pomdp.gate(b) is False
    for _ in range(3):
        b = b.update(SPREAD, days=7)
    assert pomdp.gate(b) is True
    assert pomdp.gate(None) is True  # no belief yet -> old behaviour


# --- 1. a day's observation is a seventh of a week's evidence ---------------------------------
def test_seven_daily_observations_weigh_about_one_weekly_one():
    weekly = pomdp.Belief.initial().update(WAIT, days=7)
    daily = pomdp.Belief.initial()
    for _ in range(7):
        daily = daily.update(WAIT, days=1)
    assert abs(daily.b[1] - weekly.b[1]) < 0.08
    seven_weeks = pomdp.Belief.initial()
    for _ in range(7):
        seven_weeks = seven_weeks.update(WAIT, days=7)
    assert seven_weeks.b[1] > daily.b[1] + 0.15  # seven weeks of evidence is far more than seven days
    assert daily.update(WAIT, days=30).b[1] <= pomdp.Belief(daily.b).update(WAIT, days=7).b[1] + 1e-9  # a gap caps at one observation


# --- 2. weekly sequences out of daily archive stages ----------------------------------------
def test_weekly_sequences_sample_one_verdict_per_week_and_break_on_gaps():
    d0 = date(2026, 6, 1)  # Monday
    days = [(d0 + timedelta(days=i), FLAT if i < 14 else WAIT) for i in range(28)]
    days += [(d0 + timedelta(days=70 + i), WAIT) for i in range(14)]  # six weeks later: a new run
    seqs = pomdp.weekly_sequences({"k": days})
    assert seqs == [[5, 5, 0, 0], [0, 0]]
    assert pomdp.weekly_sequences({"k": days[:3]}) == []  # a single week is no sequence


# --- 4. held keywords cannot crowd out every candidate ------------------------------------------
def test_plan_caps_held_keywords_to_half_the_budget():
    today = date(2026, 9, 21)
    b = pomdp.Belief.initial()
    for _ in range(4):
        b = b.update(WAIT, days=7)
    beliefs = {f"held{i}": b.stamp(today) for i in range(10)}
    got = pomdp.plan(beliefs, ["c1", "c2", "c3", "c4"], pinned=[], limit=8, today=today)
    assert sum(1 for k in got if k.startswith("held")) == 4 and got[-4:] == ["c1", "c2", "c3", "c4"]


# --- 5. alert policies on one sequence --------------------------------------------------------
def test_simulate_alerts_gated_policy_fires_no_more_than_the_raw_one():
    verdicts = [FLAT, WAIT, FLAT, WAIT, FLAT, WAIT, WAIT, WAIT, SPREAD, SPREAD, PAST]
    raw, gated = pomdp.simulate_alerts(verdicts)
    assert raw == [1, 3, 5, 8]  # every re-entry of an alert stage
    assert set(gated) <= set(raw) and len(gated) < len(raw)
