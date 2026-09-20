"""Silent failures must become visible: health report -> exit code + GitHub output."""

import json

from trend_engine.cli import main
from trend_engine.health import Health, check


def report(status, clusters=20):
    return {"source_status": status, "clusters": [{}] * clusters}


def test_missing_keys_are_not_problems_but_broken_sources_are():
    h = Health()
    h.check_report("KR", report({"a": {"ok": True, "error": None}, "b": {"ok": True, "error": None},
                                 "youtube": {"ok": False, "error": "missing config: youtube_api_key"}}))
    assert h.ok
    h.check_report("US", report({"a": {"ok": True, "error": None},
                                 "nate": {"ok": False, "error": "HTTP 500 from ..."}}, clusters=3))
    assert not h.ok
    assert any("nate" in p for p in h.problems)
    assert any("정상 소스가 1개" in p for p in h.problems) and any("3개뿐" in p for p in h.problems)


def test_check_writes_github_output_and_exit_code(tmp_path, monkeypatch):
    out = tmp_path / "gh_out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("RUN_URL", "https://example/run/1")
    p = tmp_path / "health.json"
    Health(problems=["연령·성별 분석 실패 — 429"]).write(p)
    ok, body = check(p)
    assert not ok and "429" in body and "https://example/run/1" in body
    written = out.read_text()
    assert "count=1" in written and "body<<__HEALTH__" in written
    assert main(["health-check", str(p)]) == 1

    Health().write(p)
    assert main(["health-check", str(p)]) == 0


def test_missing_health_file_is_a_problem(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    ok, body = check(tmp_path / "nope.json")
    assert not ok and "export" in body


def test_optional_source_failure_is_a_warning_not_a_problem():
    """커뮤니티 피드(ettoday 등)는 차단·개편이 잦다 — 알려는 주되 배포를 빨갛게 만들지는 않는다."""
    h = Health()
    h.check_report("TW", report({"google_trends": {"ok": True, "error": None},
                                 "google_news": {"ok": True, "error": None},
                                 "wikipedia": {"ok": True, "error": None},
                                 "ettoday": {"ok": False, "error": "HTTP 403 from https://..."}}))
    assert h.ok and not h.problems
    assert any("ettoday" in w for w in h.warnings)
