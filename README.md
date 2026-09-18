# Trend Engine

**"지금 사람들은 뭐에 관심이 있나"**를 여러 신호로 교차 검증하는 트렌드 엔진.
Google·네이버·YouTube·포털 실시간 이슈·위키백과·뉴스를 모아 하나의 랭킹으로 합치고,
**국가 / 서울 / 연령 / 성별** 단위로 쪼개 봅니다.

```
Google Trends(국가·서울) ─┐
시그널·네이트 실시간 ─────┤                     ┌─ 통합 랭킹 (NEW / ▲▼ 추이)
위키백과 조회수 ──────────┼─► 정규화·클러스터링 ─┼─ 연령·성별 affinity (네이버 DataLab)
YouTube 인기 · 뉴스 ──────┘     교차 점수         ├─ 서울 핫스팟 연령 분포 (서울 도시데이터)
                                                  └─ AI 브리핑 (Claude, 근거 검증)
```

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
| **연령·성별** 관심도 | `NAVER_CLIENT_ID` / `SECRET` (DataLab) | 세그먼트 비활성 |
| 서울 핫스팟 실시간 인구·연령 | `SEOUL_API_KEY` | 공개 sample 키로 1곳만 |
| AI 브리핑 | `ANTHROPIC_API_KEY` | 브리핑 비활성 |

## 명령어

| 명령 | 설명 |
|---|---|
| `collect -r KR [-s google_trends]` | 수집 → 통합 랭킹 (스냅샷 저장, 이전 대비 NEW/▲▼) |
| `segments -r KR --top 16 --segments "20대,30대,20대 여성"` | 상위 트렌드의 연령·성별 affinity |
| `keyword 아이폰 갤럭시 --segments "10대,20대,50대"` | 임의 키워드 그룹 비교 |
| `seoul [--places "강남역,성수카페거리"]` | 서울 핫스팟 혼잡도·연령 분포 |
| `brief -r KR` | Claude 트렌드 브리핑 |
| `doctor` | 모든 업스트림 라이브 점검 |
| `record --regions KR,KR-11,US,JP` | 라이브 응답으로 테스트 fixture 갱신 |

모든 명령은 `--json` 지원(에이전트/스크립트용), `--offline` 지원(데모/테스트용).

## 문서

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — 구조와 데이터 흐름, 점수 공식
- [docs/SOURCES.md](docs/SOURCES.md) — 소스별 범위, 키, 한계, 이용약관 주의
- [docs/SEGMENTS.md](docs/SEGMENTS.md) — 연령·성별 affinity 방법론과 해석 주의
- [docs/HARNESS.md](docs/HARNESS.md) — 테스트/오프라인/라이브 하네스
- [docs/ADDING_A_SOURCE.md](docs/ADDING_A_SOURCE.md) — 새 소스 추가 절차
- [AGENTS.md](AGENTS.md) / [CLAUDE.md](CLAUDE.md) — AI 코딩 에이전트용 작업 가이드
