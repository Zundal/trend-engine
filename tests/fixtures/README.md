# Fixtures (harness)

`<source>/<code>.<ext>` = 업스트림 원본 응답 그대로. `Source.parse()` 와 오프라인 모드(`--offline`)의 입력.

- `code` 는 Google Trends 만 하위 지역(`KR-11`)까지, 나머지는 국가 코드(`KR`).
- 녹화 (라이브): `uv run trend-engine record --regions KR,KR-11,US,JP` → diff 검토 후 커밋.
- **합성(synthetic) 파일** — 실제 데이터 아님, API 문서 형태만 맞춘 샘플:
  - `youtube/KR.json` (`_synthetic` 필드 표시). `YOUTUBE_API_KEY` 설정 후 `record` 하면 실데이터로 교체됨.
  - 네이버 DataLab 은 파일이 없고 `segments.synthetic_response()` 가 결정적 가짜 응답을 만든다 (`synthetic: true`).
- `datalab_web/trendResult.html` — 키 없는 네이버 검색어 트렌드 웹 결과 페이지 실응답 (날씨·등산, 20대 여성).
- `shopping_insight/sample.json` — 쇼핑인사이트 실응답으로 만든 결과 (20대, 60대+, 20대 여성 × 패션의류·디지털/가전·식품). 오프라인 모드 입력.
- `melon/KR.json` — 멜론 TOP100 JSON 에서 상위 50곡만 남긴 실응답 요약 (`songs`).
- `netflix/*.json` — 글로벌 Top10 TSV 최신 주만 잘라 둔 요약 (`shows`). 나라별 파일 내용은 동일.
- `yahoo_topics/JP.json` · `hatena/JP.xml` · `nicovideo/JP.json` · `billboard_japan/JP.html` · `livedoor_trend/JP.xml` — 일본 밀도 맞춤용 실응답 (상위 N개로 자른 것 포함).
- `billboard_us/US.html` — 빌보드 Hot 100 실응답에서 차트 행(`h3`+`c-label`) 50개만 남긴 것. `official_charts/GB.html` 은 script·svg·head 를 걷어낸 실응답.
- `yahoo_tw_search/TW.html` — tw.yahoo.com 홈에서 헤더 인기 검색어 `<ul>` 만 남긴 것 (유료 노출 `kt:rev` 항목 포함, parse 가 버리는지 검사용).
- `trends24/{US,JP,GB}.html` — 맨 앞(최신) `trend-card__list` 하나만 남긴 것.
- `yahoo_realtime/JP.html` — 트렌드 `<ol>` 목록만 남긴 것.
- `yahoo_us/US.xml` · `bbc_news/GB.xml` · `kkbox_tw/TW.json` · `yahoo_tw/TW.xml` · `gnn_tw/TW.xml` · `vnexpress/VN.xml` — 실응답 그대로.
