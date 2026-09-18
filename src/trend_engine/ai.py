"""AI trend briefing with Claude: groups today's clusters into themes and explains who cares.

Grounding contract (enforced by `validate_brief`, tested in tests/test_ai.py):
  every keyword the model cites must exist in the input clusters; anything else is dropped
  and reported in `warnings`. The model only sees collected data — it must not invent trends.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from .normalize import norm_key, similar

SYSTEM = """당신은 한국 트렌드 애널리스트입니다. 주어진 수집 데이터만 근거로 '지금 사람들의 관심'을 요약합니다.
규칙:
- 입력에 없는 키워드·사실을 만들지 마세요. keywords 필드에는 입력 clusters 의 label 을 그대로 쓰세요.
- 연령/성별 인사이트는 segments(affinity 지수, 100=평균)가 있을 때만 쓰고, 없으면 segment_insights 를 비우세요.
- 사건·사고, 정치, 연예, 스포츠, 경제, 테크, 생활 등 성격이 다른 관심사를 구분하세요.
- 간결한 한국어. 과장 금지."""

BRIEF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "themes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "category": {"type": "string"},
                    "summary": {"type": "string"},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title", "category", "summary", "keywords"],
                "additionalProperties": False,
            },
        },
        "segment_insights": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "segment": {"type": "string"},
                    "insight": {"type": "string"},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["segment", "insight", "keywords"],
                "additionalProperties": False,
            },
        },
        "seoul": {"type": "string"},
        "caveats": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["headline", "themes", "segment_insights", "seoul", "caveats"],
    "additionalProperties": False,
}


class LLM(Protocol):
    def __call__(self, system: str, user: str, schema: dict[str, Any]) -> str: ...


def build_prompt(report: dict[str, Any], segments: dict[str, Any] | None, seoul: dict[str, Any] | None,
                 top_n: int = 25) -> str:
    clusters = []
    for c in report["clusters"][:top_n]:
        entry = {"label": c["label"], "score": c["score"], "sources": list(c["sources"]),
                 "status": c.get("status"), "news": c.get("related", [])[:2]}
        if segments and c["query"] in segments.get("affinity", {}):
            entry["segments"] = {k: v for k, v in segments["affinity"][c["query"]].items() if v is not None}
        clusters.append(entry)
    payload: dict[str, Any] = {"region": report["region_name"], "generated_at": report["generated_at"], "clusters": clusters}
    yt = report.get("content", {}).get("youtube", [])[:15]
    if yt:
        payload["youtube_popular"] = [{"title": v["keyword"], "category": v.get("category")} for v in yt]
    if segments and segments.get("synthetic"):
        payload["segment_note"] = "segments 는 오프라인 합성 데이터입니다. 인사이트로 쓰지 말고 caveats 에 명시하세요."
    if seoul and seoul.get("places"):
        payload["seoul_hotspots"] = [
            {"place": p["name"], "congestion": p["congestion"], "dominant_group": p.get("dominant_group"),
             "sample": p.get("sample")}
            for p in seoul["places"]
        ]
    return "다음 수집 데이터로 트렌드 브리핑을 작성하세요.\n\n" + json.dumps(payload, ensure_ascii=False, indent=1)


def validate_brief(brief: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    """Drop keywords that are not grounded in the report's clusters."""
    known = [norm_key(v) for c in report["clusters"] for v in [c["label"], c["query"], *c.get("variants", [])]]
    warnings: list[str] = []

    def grounded(kws: list[str]) -> list[str]:
        keep = []
        for k in kws:
            if any(similar(norm_key(k), kk) for kk in known):
                keep.append(k)
            else:
                warnings.append(f"ungrounded keyword dropped: {k}")
        return keep

    for t in brief.get("themes", []):
        t["keywords"] = grounded(t.get("keywords", []))
    for s in brief.get("segment_insights", []):
        s["keywords"] = grounded(s.get("keywords", []))
    brief["themes"] = [t for t in brief.get("themes", []) if t["keywords"]]
    brief["warnings"] = warnings
    return brief


def claude_llm(api_key: str = "", model: str = "claude-opus-5") -> LLM:
    import anthropic  # optional dependency: pip install 'trend-engine[ai]'

    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()

    def call(system: str, user: str, schema: dict[str, Any]) -> str:
        response = client.beta.messages.create(
            model=model,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": schema}},
            # Server-side refusal fallback: re-runs a declined request on Anthropic's recommended model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if response.stop_reason == "refusal":
            raise RuntimeError("Claude declined to produce the brief (stop_reason=refusal)")
        if response.stop_reason == "max_tokens":
            raise RuntimeError("brief truncated (max_tokens)")
        return next(b.text for b in response.content if b.type == "text")

    return call


def make_brief(report: dict[str, Any], llm: LLM, segments: dict[str, Any] | None = None,
               seoul: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = llm(SYSTEM, build_prompt(report, segments, seoul), BRIEF_SCHEMA)
    brief = validate_brief(json.loads(raw), report)
    brief["region"] = report["region"]
    brief["based_on"] = report["generated_at"]
    return brief
