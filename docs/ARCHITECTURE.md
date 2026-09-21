# Architecture

## 데이터 흐름

```
            ┌──────────────── sources/ (fetch=I/O, parse=pure) ─────────────────┐
 region ──► │ google_trends  signal_bz  nate  wikipedia │ youtube  google_news │ (asyncio.gather)
            └────────────── keyword 신호 ───────────────┴──── content 신호 ─────┘
                                   │                              │
                                   ▼                              ▼
                     scoring.build_clusters(keyword_items, content_items, weights, previous, families)
                                   │  1) 강한 신호 순으로 greedy 클러스터링 (normalize.similar_text)
                                   │  2) 콘텐츠 제목의 키워드 언급 집계 (normalize.mentions_any)
                                   │  3) 점수 계산, 4) 이전 스냅샷과 비교해 NEW/▲/▼
                                   ▼
                         TrendReport ──► Store(SQLite: reports, clusters, cache)
                                   │
          ┌────────────────────────┼─────────────────────────┐
          ▼                        ▼                         ▼
 segments.SegmentProfiler   youth (10·20대 발견)        diffusion (세대 확산 + 백테스트)
 (Naver DataLab, 연령·성별)  shopping (쇼핑인사이트)      archive (일별 기록·기간 뷰)
          └────────────── service.TrendService ──────────────┘
                         │                    │
                     api.py (FastAPI + web/)   cli.py
```

## 두 종류의 신호
- **keyword**: 검색어 그 자체가 관심의 증거 (Google Trends, 포털 실시간 이슈, 위키백과 문서명).
- **content**: 콘텐츠 제목 (YouTube 인기 영상, 뉴스 헤드라인). 랭킹 항목이 되지 않고,
  키워드 클러스터를 **언급**하면 점수를 보태는 교차 검증 증거로 쓰인다. 원본은 별도 패널로 노출.

## 점수 공식 (`scoring.py`)
```
strength(item)  = weight(source) × (1 - (rank-1)/n)          # n = 그 소스의 항목 수
family_score    = max(strength) + 0.25 × (나머지 합)           # 같은 family = 상관된 소스
content_boost   = Σ weight(content_src) × min(언급수, 5)/5
consensus       = 1 + 0.3 × (독립 family 수 - 1)
score           = (Σ family_score + content_boost) × consensus × 100
```
- 가중치: google_trends 1.0, signal_bz 0.9, nate 0.9, youtube 0.6, google_news 0.5, wikipedia 0.4.
- signal.bz 와 Nate 는 같은 포털 이슈를 반영하므로 `family="portal_realtime"` — 둘 다 떠도 "독립 확인"으로 치지 않는다.
- 위키백과는 방송사·국가 같은 상시 인기 문서가 섞여 가중치를 낮췄다.

## 매칭 규칙 (`normalize.py`)
- 키: NFKC → 소문자 → 공백·기호 제거 (`두산에너 빌리티` == `두산에너빌리티`).
- 같은 관심사 판정: 키 동일 / 짧은 쪽이 긴 쪽에 포함(길이비 ≥0.4, 최소 길이) / 2-gram Dice ≥0.8 / 단어 2개 이상·60% 이상 겹침.
- 너무 짧은 키(ASCII 3자 미만, 한글 2자 미만)는 포함 매칭 금지 — `m`, `ai` 가 모든 제목에 걸리는 것 방지.

## 기록 (archive.py)
- 하루 = KST 자정 기준. `archive.daily_trends` 가 그날 스냅샷을 키워드별 {label, hours, best_rank, avg_score} 로 요약.
- `archive.finalize` 가 끝난 날만 파일로 씀 (멱등). CI 에서는 `data` 브랜치 체크아웃(`archive/`)에 쓰고 커밋.
- 기간 뷰: `period_trends` (exposure = Σ hours × avg_score 로 정렬, 날짜별 최고 순위 series, 기간 중 처음 등장 = NEW),
  `period_segments` (그룹별로 평균 초과(>100)로 top5 에 든 날 수 → 평균 배수).
- 연령·쇼핑 스냅샷은 `record_daily_extras` 로 하루 마지막 값을 보관 → finalize 때 파일로.
- 쇼핑 30일은 네이버 쇼핑인사이트 30일 창을 직접 조회(하루 1회 캐시) → 기록 없이도 바로 제공.
- 캐시 DB 는 `Store.prune()` 으로 원본 payload 3일, 순위 45일만 유지.

## 공개 데이터 (publish.py)
- 대시보드용 API 와 정적 사이트는 `publish.public_*` 뷰만 내보낸다: 소스 이름·언론사·소스 상태를 뺀 중립 형태
  (`clusters[].mentions` 는 평탄화된 제목 목록, `videos` / `news` 로 이름 변경). 원본은 CLI `--json` 으로만.
- 정적 사이트 파일은 `api/<name>.dat` = base64(IV‖AES-256-GCM 암호문). 키는 `TREND_ENGINE_DATA_KEY`
  (GitHub Secret, 64 hex) 이며 빌드된 index.html 에 주입되어 브라우저(WebCrypto)가 복호화한다 → **https 필수**.
- 키가 페이지에 들어가므로 "캐주얼한 열람 방지"이지 접근 제어가 아니다.
- 영상·뉴스 링크 주소는 DOM 에 넣지 않고 클릭 시 메모리에서 연다 (hover 시 주소 비노출).

## 저장소
- `reports`: 리포트 JSON 전체 (재현·디버깅용).
- `clusters`: (report_id, rank, key) — `/api/history` 순위 추이.
- `cache`: DataLab 응답(6h), 세그먼트·쇼핑·10·20대(3h)·세대 확산(20h) 결과, 국면 믿음(`belief:v1`, 60일), 일별 스냅샷(`daily:*`, 기록되면 archive 로).
- 이전 스냅샷 기준: 30분 이상 지난 최신 리포트 (없으면 직전 리포트).

## 확장 지점
| 하고 싶은 것 | 위치 |
|---|---|
| 소스 추가 | `sources/` + 레지스트리 + fixture (docs/ADDING_A_SOURCE.md) |
| 지역 추가 | `config.REGIONS` |
| 세그먼트 조합 | `segments.parse_segment` ("20대 여성", "20대+30대 남성") |
| 점수 조정 | `Source.weight`, `Source.family`, `scoring.py` 상수 |
| 주기 수집 | `trend-engine collect` 를 cron/launchd 로 (스냅샷이 쌓여야 ▲▼ 추이가 생김) |
