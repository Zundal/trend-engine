"""AI brief harness: prompt construction + grounding validation with a fake LLM (no API calls)."""

import json

from trend_engine import ai


def report():
    return {
        "region": "KR", "region_name": "대한민국", "generated_at": "2026-09-18T12:00:00+00:00",
        "clusters": [
            {"label": "청하", "query": "청하", "variants": ["청하"], "score": 150, "sources": {"google_trends": 1},
             "status": "new", "related": ["청하 응급실 이송"]},
            {"label": "두산에너 빌리티", "query": "두산에너빌리티", "variants": ["두산에너 빌리티"], "score": 90,
             "sources": {"google_trends": 2}, "status": None, "related": []},
        ],
        "content": {"youtube": [{"keyword": "청하 직캠", "category": "음악"}]},
    }


def fake_llm(payload):
    seen = {}

    def llm(system, user, schema):
        seen.update(system=system, user=user, schema=schema)
        return json.dumps(payload, ensure_ascii=False)

    return llm, seen


def test_brief_drops_ungrounded_keywords():
    llm, seen = fake_llm({
        "headline": "연예·에너지주 관심",
        "themes": [
            {"title": "연예", "category": "연예", "summary": "...", "keywords": ["청하", "아이유"]},
            {"title": "환각", "category": "기타", "summary": "...", "keywords": ["존재하지않는키워드"]},
            {"title": "원전", "category": "경제", "summary": "...", "keywords": ["두산에너빌리티"]},
        ],
        "segment_insights": [], "seoul": "", "caveats": [],
    })
    b = ai.make_brief(report(), llm)
    assert [t["title"] for t in b["themes"]] == ["연예", "원전"]  # fully-ungrounded theme removed
    assert b["themes"][0]["keywords"] == ["청하"]
    assert any("아이유" in w for w in b["warnings"])
    assert b["based_on"] == "2026-09-18T12:00:00+00:00"


def test_prompt_contains_only_collected_data():
    llm, seen = fake_llm({"headline": "", "themes": [], "segment_insights": [], "seoul": "", "caveats": []})
    ai.make_brief(report(), llm, segments={"synthetic": True, "affinity": {"청하": {"20대": 180.0, "60대+": None}}})
    assert "청하" in seen["user"] and "청하 직캠" in seen["user"]
    assert "합성" in seen["user"]  # synthetic segment data must be flagged to the model
    assert '"60대+"' not in seen["user"]  # None values stripped
    assert seen["schema"] is ai.BRIEF_SCHEMA
