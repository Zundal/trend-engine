"""Static export (GitHub Pages) produces every file the dashboard's static mode reads."""

import json

from trend_engine.export import export_site


async def test_export_offline(service, tmp_path):
    lines = await export_site(service, tmp_path, ["KR", "KR-11"], brief_regions=["KR"])
    api = tmp_path / "api"
    meta = json.loads((api / "meta.json").read_text())
    assert meta["static"] is True
    assert [r["code"] for r in meta["regions"]] == ["KR", "KR-11"]
    for code in ("KR", "KR-11"):
        rep = json.loads((api / f"report-{code}.json").read_text())
        assert rep["region"] == code and rep["clusters"]
        hist = json.loads((api / f"history-{code}.json").read_text())
        assert set(hist) == {c["key"] for c in rep["clusters"]}
        assert json.loads((api / f"segments-{code}.json").read_text())["synthetic"] is True  # offline
    assert not (api / "brief-KR.json").exists()  # no ANTHROPIC_API_KEY -> no brief, no failure
    assert json.loads((api / "seoul.json").read_text())["places"]
    assert (tmp_path / "index.html").exists() and (tmp_path / ".nojekyll").exists()
    assert any("report KR" in line for line in lines)
