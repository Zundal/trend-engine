from datetime import date, timedelta

from trend_engine import insight
from trend_engine.publish import public_insight


def snap(at, *clusters):
    return {"generated_at": at, "clusters": list(clusters)}


def cl(key, sources=None, mentions=None, label=None, related=None, variants=None):
    return {"key": key, "label": label or key, "sources": sources or {}, "mentions": mentions or {},
            "related": related or [], "variants": variants or [label or key]}


T0, T1, T2, T3 = ("2026-10-26T00:00:00+00:00", "2026-10-26T01:00:00+00:00",
                  "2026-10-26T04:00:00+00:00", "2026-10-26T05:00:00+00:00")


def test_origin_names_the_first_signal_and_its_lead():
    snaps = [snap(T0, cl("other", {"nate": 1})),
             snap(T1, cl("lula", {"getdaytrends": 3})),
             snap(T2, cl("lula", {"getdaytrends": 2, "yahoo_trending": 4})),
             snap(T3, cl("lula", {"getdaytrends": 1, "yahoo_trending": 1, "google_trends": 2}, {"bbc_news": ["Lula wins"]}))]
    o = insight.origin(cl("lula"), snaps)
    assert [p["signal"] for p in o["path"]] == ["SNS", "포털", "검색 급상승", "뉴스·콘텐츠"]
    assert o["first"] == "SNS" and o["lead_hours"] == 3.0


def test_origin_is_unknown_when_already_there_at_window_start():
    o = insight.origin(cl("x"), [snap(T0, cl("x", {"nate": 1})), snap(T1, cl("x", {"nate": 1, "google_trends": 1}))])
    assert o["first"] is None and o["lead_hours"] is None


def test_origin_is_unknown_on_a_tie():
    o = insight.origin(cl("x"), [snap(T0, cl("y")), snap(T1, cl("x", {"nate": 1, "google_trends": 1}))])
    assert o["first"] is None


def test_leads_counts_who_was_first_across_issues():
    origins = [{"window_start": T0, "path": [{"signal": "SNS", "at": T1}, {"signal": "포털", "at": T2}]}] * 3
    origins += [{"window_start": T0, "path": [{"signal": "포털", "at": T1}, {"signal": "SNS", "at": T3}]}]
    (row,) = insight.leads(origins)
    assert row["signal"] == "SNS" and row["before"] == "포털" and row["n"] == 4 and row["share"] == 0.75


def test_why_picks_the_headline_others_agree_with_not_the_shared_name():
    c = cl("lula", label="Lula", related=["Lula wins Brazil runoff vote", "Lula seen at a cafe"],
           mentions={"bbc_news": ["Brazil runoff: Lula wins vote narrowly"], "yahoo_us": ["Bolsonaro concedes runoff vote to Lula"]})
    w = insight.why(c)
    assert "runoff" in w["line"] and w["support"] == 3 and w["titles"] == 4 and w["outlets"] == 3
    assert insight.why(cl("none")) is None


def test_life_phases():
    rows = [{"generated_at": T0, "rank": 9}, {"generated_at": T1, "rank": 6}, {"generated_at": T3, "rank": 2}]
    assert insight.life(rows, T3)["phase"] == "막 등장"
    later = "2026-10-26T12:00:00+00:00"
    rows2 = rows + [{"generated_at": "2026-10-26T06:00:00+00:00", "rank": 3}, {"generated_at": later, "rank": 8}]
    l = insight.life(rows2, later)
    assert l["phase"] == "내려가는 중" and l["peak_rank"] == 2 and l["returns"] == 0
    back = "2026-10-29T00:00:00+00:00"
    assert insight.life(rows2 + [{"generated_at": back, "rank": 5}], back)["phase"] == "재등장"
    assert insight.life(rows, later)["phase"] == "순위 밖"


def test_links_join_issues_in_the_same_headline_and_skip_hubs():
    a = cl("ufc", label="UFC", mentions={"n": ["최두호, UFC 331 계체 통과", "UFC 331 대진 확정"]})
    b = cl("최두호", label="최두호", mentions={"n": ["최두호 복귀전 승리"]})
    c = cl("유주상", label="유주상", related=["유주상·최두호 동반 출격"])
    lone = cl("날씨", label="날씨", related=["내일 비"])
    per, groups = insight.links([a, b, c, lone])
    assert {x["key"] for x in per["최두호"]} == {"ufc", "유주상"}
    assert "날씨" not in per
    assert groups and set(groups[0]["keys"]) == {"ufc", "최두호", "유주상"}
    hub = cl("vn", label="Việt Nam", related=[f"Việt Nam tin {i}" for i in range(12)])
    x = cl("x", label="Hà Nội", related=["Hà Nội và Việt Nam"])
    per2, _ = insight.links([hub, x])
    assert per2 == {}


def series(today, recent, last_year, usual=100, start_days=400):
    out = []
    for k in range(start_days, -1, -1):
        d = today - timedelta(days=k)
        v = usual
        if k < 7:
            v = recent
        elif 360 <= k <= 370:
            v = last_year
        out.append((d, v))
    return out


def test_season_labels():
    today = date(2026, 10, 25)
    assert insight.season(series(today, 5000, 4000), today)["label"] == "매년 이맘때 오는 관심"
    assert insight.season(series(today, 5000, 100), today)["label"] == "작년 이맘때는 조용했음"
    assert insight.season(series(today, 120, 120), today)["label"].startswith("평소와 비슷한")
    fresh = [(d, 0 if d < today - timedelta(days=30) else v) for d, v in series(today, 5000, 0)]
    assert insight.season(fresh, today)["label"] == "작년엔 문서가 없던 새 관심"
    assert insight.season(series(today, 5000, 0, start_days=100), today) is None


def test_build_and_public_view_carry_no_source_names():
    rep = {"region": "US", "generated_at": T3,
           "clusters": [cl("lula", {"getdaytrends": 1, "yahoo_trending": 2}, {"bbc_news": ["Lula wins"]}, label="Lula")]}
    out = public_insight(insight.build(rep, [snap(T0, cl("other")), snap(T1, cl("lula", {"getdaytrends": 3})), rep],
                                       {"lula": [{"generated_at": T3, "rank": 1}]}, {}))
    text = repr(out)
    assert "lula" in out["items"] and out["items"]["lula"]["origin"]["first"] == "SNS"
    assert not any(s in text for s in ("getdaytrends", "yahoo_trending", "bbc_news"))
