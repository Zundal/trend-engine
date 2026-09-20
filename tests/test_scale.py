"""기준어 없는 전역 정렬: recover known sizes from per-request ratios alone."""

import random

from trend_engine import scale

TRUE = {"가": 1000.0, "나": 400.0, "다": 120.0, "라": 60.0, "마": 25.0,
        "바": 10.0, "사": 4.0, "아": 1.5, "자": 0.6, "차": 0.25}


def batches_from(plan, truth, noise=0.0, seed=1):
    """What DataLab gives back: each request normalised to its own biggest member."""
    rng = random.Random(seed)
    out = []
    for names in plan:
        vals = {n: truth[n] * (1 + rng.gauss(0, noise)) for n in names}
        top = max(vals.values())
        out.append({n: v / top * 100 for n, v in vals.items()})
    return out


def test_recovers_relative_sizes_across_requests_without_an_anchor():
    names = list(TRUE)
    plan = scale.plan(names, size=5, overlap=2)
    got = scale.report(batches_from(plan, TRUE), names)
    assert got["connected"] and got["rms_log_error"] < 1e-6
    ref = got["scale"]["가"] / TRUE["가"]
    for n, truth in TRUE.items():
        assert abs(got["scale"][n] / (truth * ref) - 1) < 1e-6, n


def test_survives_noisy_measurements_and_reports_the_error():
    names = list(TRUE)
    plan = scale.plan(names, size=5, overlap=2)
    got = scale.report(batches_from(plan, TRUE, noise=0.05), names)
    assert got["connected"] and 0 < got["rms_log_error"] < 0.2
    ref = got["scale"]["가"] / TRUE["가"]
    worst = max(abs(got["scale"][n] / (TRUE[n] * ref) - 1) for n in TRUE)
    assert worst < 0.25  # 5% measurement noise must not become a 25% scale error


def test_a_keyword_that_never_shared_a_request_is_reported_not_guessed():
    names = list(TRUE) + ["외톨이"]
    plan = scale.plan(list(TRUE), size=5, overlap=2)
    got = scale.report(batches_from(plan, TRUE), names)
    assert not got["connected"] and got["orphans"] == ["외톨이"]


def test_plan_keeps_every_batch_linked_to_the_next():
    names = [f"k{i}" for i in range(23)]
    plan = scale.plan(names, size=5, overlap=2)
    assert all(len(b) <= 5 for b in plan)
    for a, b in zip(plan, plan[1:]):
        assert set(a) & set(b), "consecutive batches must share keywords or the scale can't travel"
    assert set().union(*plan) == set(names)


def test_small_keywords_keep_their_ratio_instead_of_rounding_to_zero():
    """The anchor problem, in miniature: measured against a giant, 차 is 0.02% and quantises away."""
    names = list(TRUE)
    anchor_batches = [{"가": 100.0, n: round(TRUE[n] / TRUE["가"] * 100, 1)} for n in names if n != "가"]
    anchor_scale = scale.report(anchor_batches, names)["scale"]
    graph_scale = scale.report(batches_from(scale.plan(names, 5, 2), TRUE), names)["scale"]
    ratio = lambda s, a, b: s[a] / s[b]  # noqa: E731
    truth = TRUE["차"] / TRUE["자"]
    assert abs(ratio(graph_scale, "차", "자") / truth - 1) < 0.01
    assert abs(ratio(anchor_scale, "차", "자") / truth - 1) > 0.05  # rounding wrecks the small pair
