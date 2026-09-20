# AGENTS.md — AI 코딩 에이전트 작업 가이드

이 파일은 이 저장소에서 일하는 모든 AI 에이전트(Claude Code, Codex 등)의 기준 문서다.
사람용 개요는 README.md, 설계 근거는 docs/.

## 한 줄 요약
여러 트렌드 소스 → `TrendItem` → 정규화·클러스터링·점수(`scoring.py`) → `TrendCluster` 랭킹 → SQLite 스냅샷.
세그먼트(연령·성별)는 네이버 DataLab, 10·20대 발견은 youth.py, 세대 확산은 diffusion.py.

## 명령 (모두 저장소 루트에서)
```bash
uv sync --all-extras                 # 설치
uv run pytest -q                     # 전체 테스트 (네트워크 사용 안 함, <1초)
uv run trend-engine --offline collect --json   # 네트워크 없이 엔진 전체 실행
uv run trend-engine doctor           # 라이브 업스트림 점검 (네트워크 사용)
uv run trend-engine record           # fixture 갱신 (네트워크) → git diff 검토
uv run trend-engine --offline serve --port 8765  # UI 확인
```

## 코드 지도
| 파일 | 책임 |
|---|---|
| `src/trend_engine/models.py` | `TrendItem`(소스 출력), `TrendCluster`(병합 결과), `TrendReport` |
| `src/trend_engine/sources/*.py` | 소스별 `fetch()`(I/O) + `parse()`(순수 함수). 등록은 `sources/__init__.py` |
| `src/trend_engine/normalize.py` | 한국어 키워드 키/유사도/언급 판정 |
| `src/trend_engine/scoring.py` | 병합 + 점수 공식 (docstring 이 명세) |
| `src/trend_engine/engine.py` | 소스 병렬 수집 → scoring → store |
| `src/trend_engine/segments.py` | DataLab 기준어(anchor) 정규화 affinity |
| `src/trend_engine/pageviews.py` | 위키미디어 과거 조회수(키 불필요): 지난 날짜의 인기 목록·문서별 일별 시계열 |
| `src/trend_engine/flux.py` | 관심의 속도: 순위 교체율 + 쏠림 (나라별, 자국 기준 비교) |
| `src/trend_engine/entities.py` | 언어별 같은 개체 잇기(공개 지식베이스 sitelinks, 키 불필요) — 국가 간 비교의 전제 |
| `src/trend_engine/scale.py` | 기준어 없는 전역 척도: 요청 겹침을 로그비 제약 그래프로 풀어 모든 키워드를 한 자로 |
| `src/trend_engine/kernel.py` | 세대 전달 함수: 윗세대 곡선 = 아랫세대 곡선 ⊛ h(k) 추정(비음수·평활), 시차/전달/동시분 분해 |
| `src/trend_engine/shapes.py` | 유행의 모양: 정점 앞뒤 비율로 예고형/하루형/대칭형/여운형 분류 + 재등장 교차검증 |
| `src/trend_engine/archive.py` | 일별 요약(KST) · data 브랜치 기록 · 7일/30일 기간 뷰 |
| `src/trend_engine/categories.py` | 무키 카테고리 분류: 뉴스 섹션·영상 분류·위키 분류·쇼핑 분야·핵심어 사전 투표 → 11개 분야 |
| `src/trend_engine/diffusion.py` | 세대 확산 감지: 연령별 주간 추이 → 급상승 시점·시차 → 단계 판정, 과거 사례 검증 |
| `src/trend_engine/youth.py` | 10·20대 포커스: 후보 수집 → 연령 측정 → "30대 이상 대비 N배" |
| `src/trend_engine/shopping.py` | 네이버 쇼핑인사이트: 그룹별 쇼핑 인기 검색어 (키 불필요) |
| `src/trend_engine/service.py` | API·CLI 가 공유하는 단일 파사드 |
| `src/trend_engine/api.py`, `cli.py`, `web/index.html` | 인터페이스 (의존성 없는 단일 HTML) |
| `src/trend_engine/harness.py` | `doctor`, `record` |
| `src/trend_engine/health.py` | 배포 점검 → health.json → 경고 이슈 (조용한 실패 방지) |
| `src/trend_engine/export.py` + `.github/workflows/pages.yml` | 정적 export → GitHub Pages (매시간). UI 는 `meta.json {"static": true}` 로 정적 모드 전환 |

## 반드시 지킬 불변식
1. **`Source.parse()` 는 순수 함수.** 네트워크·시간·난수 금지. fixture 로 테스트 가능해야 한다 (`tests/test_contract.py` 가 검사).
2. **테스트는 네트워크를 쓰지 않는다.** `Settings(offline=True)` 또는 가짜 poster/LLM 주입. 라이브 확인은 `doctor`.
3. **소스 하나가 죽어도 리포트는 나온다.** 예외는 `source_status` 로만 보고한다.
4. **합성 데이터는 반드시 표시한다.** 오프라인 DataLab 결과는 `synthetic: true`, 합성 fixture 는 `_synthetic` 필드. UI·AI 프롬프트 모두 이를 드러낸다.
5a. **공개되는 것은 `publish.py` 뷰만.** 대시보드 API·정적 파일에 소스 이름/언론사/소스 상태를 넣지 말 것 (`tests/test_export.py` 가 검사). 정적 파일은 암호화(.dat).
6. **API 와 CLI 는 `TrendService` 만 호출한다.** 로직을 인터페이스 레이어에 복제하지 말 것.
7. 점수 공식을 바꾸면 `scoring.py` docstring, `docs/ARCHITECTURE.md`, `tests/test_scoring.py` 골든 값을 함께 갱신.

## 자주 하는 작업
- **새 소스는 키 없이 되는 것만** (사용자 방침). 나라별 후보·차단 목록은 docs/SOURCES.md 하단 참고.
- **새 소스 추가**: `docs/ADDING_A_SOURCE.md` (Claude Code 는 `.claude/skills/add-trend-source` 스킬).
- **업스트림 포맷 변경 대응**: `doctor` 로 확인 → `record` → 실패하는 contract 테스트를 보고 `parse()` 수정.
- **새 지역**: Google geo 코드면 `config.REGIONS` 에 추가만 하면 된다 (없어도 `-r` 로 동작).
- **새 세그먼트**: `segments.AGE_GROUPS`/`GENDERS` 조합. `"20대 여성"` 같은 조합은 코드 변경 없이 `parse_segment` 가 처리.

## 완료 기준 (Definition of Done)
- `uv run pytest -q` 통과, 새 동작에는 테스트 추가.
- UI 를 바꿨다면 `E2E=1 uv run --group e2e pytest -m e2e tests/e2e` 통과 (CI 의 e2e 잡도 같은 테스트).
- `uv run trend-engine --offline collect` 정상 출력.
- UI 를 건드렸다면 `--offline serve` 로 띄워 콘솔 에러 없음 확인. 새 API 를 추가했다면 `export.py` 와 index.html 의 `staticPath()` 에도 반영 (정적 배포에서 깨지지 않게).
- 사용자에게 보이는 문구는 한국어.

## 하지 말 것
- 키/토큰을 코드·fixture·로그에 남기기 (`record` 전 fixture 에 키가 들어가는지 확인 — YouTube 응답엔 키가 없다).
- 비공식 엔드포인트(signal.bz, nate, datalab.naver.com 웹)에 고빈도 폴링. 캐시(`Store.cache_*`)와 페이싱(`WEB_PACE_SECONDS`, `PACE_SECONDS`)을 줄이지 말 것 — 429 로 막힌다.
- DataLab affinity 를 "해당 연령 검색자 비율"로 설명하기 (틀림 — docs/SEGMENTS.md).
