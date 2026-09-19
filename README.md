# Trend Engine

**"지금 사람들은 뭐에 관심이 있나"**를 여러 신호로 교차 검증하는 트렌드 엔진.
Google·네이버·YouTube·포털 실시간 이슈·위키백과·뉴스를 모아 하나의 랭킹으로 합치고,
**국가 / 서울 / 연령 / 성별** 단위로 쪼개 봅니다.

```
Google Trends · 포털 실시간 이슈 · 위키백과 ─┐                       ┌─ 10·20대: 30대 이상보다 유독 찾는 것 (연령별 검색)
인기 동영상 · 뉴스 ─────────────────────────┼─► 정규화·교차 점수 ──┼─ 세대 확산: 10·20대 → 윗세대로 번지나 (+ 적중률)
네이버 연령별 검색 · 쇼핑 인기어 ────────────┘   + 매일 기록        ├─ 나라별: 실시간 / 7일 / 30일 랭킹
                                                                   └─ 전체 연령: 연령·성별 관심·쇼핑
```

## 화면

- **10·20대** (첫 화면, 한국) — 10대 / 20대 / 10대·20대 여성·남성 × [지금 | 7일 | 30일]:
  **30대 이상보다 유독 더 찾는 것** (오늘 이슈 + 인기 영상 태그 + 10·20대 쇼핑어를 후보로 연령별 검색량 측정),
  오늘 이슈 중 더 관심 있는 것, 쇼핑 관심, 10대 vs 20대 한눈에 비교
- **세대 확산** (한국) — 10·20대가 유독 찾는 키워드가 **윗세대로 번지는지** 매일 판정
  (확산 대기 → 확산 중 "40대+가 N주 뒤 따라옴" / 윗세대 상승 / 전 연령 동시 / 상시 관심). 연령 6줄 × 주 단위 히트맵,
  과거 유행 7개(하이볼·요아정·두바이쫀득쿠키·탕후루 = 확산형, 먹태깡·포켓몬빵·러닝크루 = 동시형)로 방법 검증
- **나라별** — 나라 × [실시간 | 7일 | 30일]. 실시간은 지금 랭킹(NEW/▲▼), 7일·30일은 기간 동안 오래·높게 뜬 이슈와 날짜별 순위 그래프
- **전체 연령** (한국) — 그룹(10대~60대+, 남성·여성, 20대 여성·남성) × [7일 | 30일]: 그 그룹이 평균보다 더 관심 보인 이슈(며칠, 몇 배) · 쇼핑 관심 · 그룹 비교표

## 기록 (저장)

매시간 스냅샷은 캐시 DB 에, **끝난 날(KST)의 요약은 저장소 `data` 브랜치**에 커밋됩니다 (`날짜/trends-국가.json`, `segments.json`, `shopping.json`).
캐시가 날아가도 기록은 남고, 7일·30일 보기는 이 기록 + 오늘 데이터로 계산됩니다. 로컬은 `data/archive/`.

## 빠른 시작

```bash
uv sync --all-extras               # Python 3.11+
uv run trend-engine collect        # 한국 트렌드 (키 없이 동작)
uv run trend-engine collect -r KR-11   # 서울
uv run trend-engine collect -r US      # 미국 (Google geo 코드면 무엇이든)
uv run trend-engine serve          # 대시보드 http://127.0.0.1:8000
uv run trend-engine --offline serve    # 네트워크 없이 녹화 데이터로 데모
```

키가 필요한 기능은 `.env.example` → `.env` 복사 후 채우세요. 키가 없으면 해당 기능만 꺼지고 나머지는 그대로 동작합니다.

| 기능 | 키 | 없으면 |
|---|---|---|
| Google 트렌드(국가·서울), 시그널/네이트 실시간, 위키백과, Google 뉴스 | 불필요 | — |
| YouTube 국가별 인기 영상 | `YOUTUBE_API_KEY` | YouTube 패널 비활성 |
| **연령·성별** 관심도 (네이버 검색어 트렌드) | 불필요 — 키 없으면 데이터랩 웹 사용, 키(`NAVER_CLIENT_ID/SECRET`) 있으면 공식 API | — |
| **연령·성별 쇼핑 인기 검색어** (네이버 쇼핑인사이트) | 불필요 | — |

## 배포 (GitHub Pages)

`.github/workflows/pages.yml` 이 **매시간** 수집 → `trend-engine export` 로 정적 JSON 생성 → Pages 배포.
스냅샷 DB 는 Actions 캐시로 이어받아 추이(NEW/▲▼)가 누적됩니다.

1. 저장소 Settings → Pages → Source: **GitHub Actions**
2. (선택) Settings → Secrets and variables → Actions 에 `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`,
   `YOUTUBE_API_KEY`(선택: `NAVER_CLIENT_ID`/`NAVER_CLIENT_SECRET`) 추가 → 다음 실행부터 반영
3. Actions → Deploy dashboard → Run workflow (즉시 1회 실행)

공개 사이트의 데이터 파일은 소스 정보를 제거한 뒤 AES-256-GCM 으로 암호화되어(`api/*.dat`) 브라우저에서 복호화됩니다
(키: 저장소 Secret `TREND_ENGINE_DATA_KEY`, 64자리 hex). https 로만 열립니다.

정적 배포에서는 "직접 키워드 분석"과 "새로 수집" 버튼이 숨겨집니다 (서버가 필요하므로 `trend-engine serve` 사용).

## 명령어

| 명령 | 설명 |
|---|---|
| `collect -r KR [-s google_trends]` | 수집 → 통합 랭킹 (스냅샷 저장, 이전 대비 NEW/▲▼) |
| `segments -r KR --top 16 --segments "20대,30대,20대 여성"` | 상위 트렌드의 연령·성별 affinity |
| `keyword 아이폰 갤럭시 --segments "10대,20대,50대"` | 임의 키워드 그룹 비교 |
| `shopping [--segments "20대 여성,60대+"]` | 그룹별 쇼핑 인기 검색어 (★ = 그 그룹만의 관심) |
| `health-check health.json` | export 점검 결과 확인 (문제 있으면 종료코드 1) |
| `doctor` | 모든 업스트림 라이브 점검 |
| `record --regions KR,KR-11,US,JP` | 라이브 응답으로 테스트 fixture 갱신 |
| `export --out site --regions KR,KR-11,US` | GitHub Pages 용 정적 사이트 생성 |

모든 명령은 `--json` 지원(에이전트/스크립트용), `--offline` 지원(데모/테스트용).

## 문서

- [docs/ENGINE.md](docs/ENGINE.md) — **우리만의 엔진 로직** (교차 점수·기준어 정규화·10·20대 발견·세대 확산+백테스트·카테고리 투표)

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — 구조와 데이터 흐름, 점수 공식
- [docs/SOURCES.md](docs/SOURCES.md) — 소스별 범위, 키, 한계, 이용약관 주의
- [docs/SEGMENTS.md](docs/SEGMENTS.md) — 연령·성별 affinity 방법론과 해석 주의
- [docs/HARNESS.md](docs/HARNESS.md) — 테스트/오프라인/라이브 하네스
- [docs/ADDING_A_SOURCE.md](docs/ADDING_A_SOURCE.md) — 새 소스 추가 절차
- [AGENTS.md](AGENTS.md) / [CLAUDE.md](CLAUDE.md) — AI 코딩 에이전트용 작업 가이드
