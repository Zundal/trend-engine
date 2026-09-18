# Fixtures (harness)

`<source>/<code>.<ext>` = 업스트림 원본 응답 그대로. `Source.parse()` 와 오프라인 모드(`--offline`)의 입력.

- `code` 는 Google Trends 만 하위 지역(`KR-11`)까지, 나머지는 국가 코드(`KR`).
- 녹화 (라이브): `uv run trend-engine record --regions KR,KR-11,US,JP` → diff 검토 후 커밋.
- **합성(synthetic) 파일** — 실제 데이터 아님, API 문서 형태만 맞춘 샘플:
  - `youtube/KR.json` (`_synthetic` 필드 표시). `YOUTUBE_API_KEY` 설정 후 `record` 하면 실데이터로 교체됨.
  - 네이버 DataLab 은 파일이 없고 `segments.synthetic_response()` 가 결정적 가짜 응답을 만든다 (`synthetic: true`).
- `seoul_citydata/sample.json` 은 서울 열린데이터 공개 `sample` 키 실응답(광화문·덕수궁 고정).
