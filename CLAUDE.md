@AGENTS.md

## Claude Code 전용 메모
- 새 소스 추가 요청이면 `add-trend-source` 스킬(`.claude/skills/add-trend-source/SKILL.md`)을 따른다.
- AI 브리핑 코드(`ai.py`)는 Anthropic Python SDK 사용. 모델 기본값 `claude-opus-5`
  (`TREND_ENGINE_AI_MODEL` 로 변경), 구조화 출력 `output_config.format`, 거절 시 서버측 fallback(`fallbacks: "default"`).
  SDK 사용법을 바꿀 때는 기억에 의존하지 말고 `claude-api` 스킬로 최신 문서를 확인할 것.
- UI 검증은 `uv run trend-engine --offline serve --port 8765` 후 브라우저로 확인.
