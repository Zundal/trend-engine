# 새 소스 추가하기

예: 멜론 차트를 keyword 소스로 추가.

1. **`src/trend_engine/sources/melon.py`**
   ```python
   class Melon(Source):
       name = "melon"            # fixture 디렉터리 이름과 동일
       label = "멜론 차트"
       kind = "keyword"          # 검색어/이름이면 keyword, 콘텐츠 제목이면 content
       weight = 0.5              # 0 < w ≤ 1. 다른 소스와 비교해 신뢰도/대표성으로 결정
       family = ""               # 기존 소스와 같은 원천을 반영하면 같은 family 지정
       regions = frozenset({"KR", "KR-11"})   # None = 모든 지역
       requires = ()             # Settings 필드명 (키 필요 시). config.Settings/.env.example 에도 추가
       fixture_ext = "json"

       async def fetch(self, client, region, settings):
           return await get_text(client, "https://...")   # 원본 그대로 반환

       def parse(self, raw, region):                        # 순수 함수!
           ...
           return rerank(items)                             # rank 1..n
   ```
2. **등록**: `sources/__init__.py` 의 `REGISTRY` 리스트에 추가.
3. **fixture**: `uv run trend-engine record --regions KR` (또는 수동으로 `tests/fixtures/melon/KR.json`).
   키가 없어 합성 fixture 를 만들었다면 `_synthetic` 표시 + `tests/fixtures/README.md` 에 기록.
4. **테스트**: `uv run pytest -q` — contract 테스트가 자동으로 새 소스를 검사한다. 파싱 특이사항(인코딩, 필터링)은 별도 테스트 추가.
5. **문서**: `docs/SOURCES.md` 표에 한 줄, 대시보드 약칭이 필요하면 `web/index.html` 의 `SRC` 맵.
6. **확인**: `uv run trend-engine doctor`, `uv run trend-engine --offline collect`.
