# Trend Engine

**"지금 사람들은 무엇에 관심이 있나"**를 단일 소스에 기대지 않고 여러 공개 신호로 교차 검증하는 트렌드 엔진입니다.
검색 급상승·포털 실시간 이슈·위키백과 조회수·인기 동영상·뉴스·쇼핑 검색어를 하나로 묶어 점수를 매기고, **국가 / 연령 / 성별 / 세대 확산(10·20대 → 40대+)** 단위로 쪼개 보여줍니다.

- **라이브 대시보드**: [https://trend.todoli.lat](https://trend.todoli.lat)
- **RSS 변화 알림 피드**: [https://trend.todoli.lat/feed.xml](https://trend.todoli.lat/feed.xml)
- **무키(Keyless) 기본 동작**: API 키 없이도 한국·미국·일본·대만·베트남·영국 등 국가별 트렌드, 연령·성별 관심도, 쇼핑 검색어, 세대 확산 분석이 바로 동작합니다.

```
검색 급상승 · 포털 실시간 이슈 · 위키백과 ─┐                        ┌─ 한눈에: 오늘의 핵심 요약 브리핑
인기 동영상 · 뉴스 · 앱/음악/게임 차트 ────┼─► 정규화·교차 점수 ────┼─ 10·20대: 30대 이상보다 유독 찾는 것 (배수·베이지안 수축)
연령·성별 검색량 · 쇼핑 인기 검색어 ───────┘   + 테마 묶기·신규성   ├─ 세대 확산: 10·20대 → 윗세대로 번지나 (POMDP·전달 함수)
                                               + 일별 아카이브      ├─ 나라별: 실시간 / 7일 / 30일 랭킹 · 국가 간 전파 · 유행 모양
                                                                    └─ 전체 연령: 이슈 × 연령·성별 히트맵 & 고유 쇼핑어
```

---

## AI 에이전트 스킬 (Skills) 설치 및 사용

Claude Code, Cursor, Codex 등 AI 코딩 에이전트에서 `trend-engine`을 스킬로 바로 내려받아 사용할 수 있습니다.

### 1. Skills CLI(`npx skills`)로 한 줄 설치

```bash
# 실시간 트렌드·연령별 관심도·세대 확산 조회 스킬 설치 (전역)
npx skills add Zundal/trend-engine@trend-engine -g -y

# (기여자용) 새로운 트렌드 데이터 소스를 추가·수리하는 스킬 설치
npx skills add Zundal/trend-engine@add-trend-source -g -y

# 저장소 내 모든 스킬 확인
npx skills add Zundal/trend-engine --list
```

### 2. 수동 설치 (Claude Code / Cursor)

```bash
mkdir -p ~/.claude/skills/trend-engine
curl -fsSL https://raw.githubusercontent.com/Zundal/trend-engine/main/skills/trend-engine/SKILL.md \
  -o ~/.claude/skills/trend-engine/SKILL.md
```

### 3. 포함 스킬 목록

| 스킬 이름 | 경로 | 용도 |
|---|---|---|
| `trend-engine` | [`skills/trend-engine/SKILL.md`](skills/trend-engine/SKILL.md) | 에이전트가 CLI(`--json`)와 Python API로 국가별 트렌드, 10·20대 급상승 키워드, 세대 확산 단계, 연령·성별 관심도를 조회·해석 |
| `add-trend-source` | [`skills/add-trend-source/SKILL.md`](skills/add-trend-source/SKILL.md) | 새 트렌드 소스를 추가하거나 업스트림 포맷 변경 시 `parse()` 및 contract 테스트를 수리 |

---

## 핵심 엔진 특징

단순 크롤링 합산이 아니라, 통계적 왜곡과 노이즈를 걸러내는 자체 알고리즘을 탑재하고 있습니다 (상세: [`docs/ENGINE.md`](docs/ENGINE.md)).

1. **교차 검증 점수 & 소스 패밀리 보정 (`scoring.py`, `normalize.py`)**
   - 한국어 띄어쓰기·조사·문장형 헤드라인 차이를 정규화해 같은 이슈를 병합하고, 관련 기사와 동시 언급으로 **테마(`build_themes`)** 단위로 한 번 더 묶습니다.
   - 같은 원천을 공유하는 소스(예: 포털 실시간 2곳)는 함께 떠도 중복 독립 확인 보너스를 주지 않습니다.
   - **신규성 감쇠(Novelty)**: 최근 30일 중 자주 등장한 상시 키워드(날씨·방송사 등)는 점수를 낮추고 오늘 새로 뜬 이슈를 위로 올립니다.
2. **기준어(Anchor) 정규화 연령·성별 Affinity (`segments.py`)**
   - 요청마다 최댓값=100으로 재정규화되고 5개씩만 묶이는 검색 트렌드 한계를 **기준어(`날씨`) 동시 투입**으로 해결해, 수십 개 키워드를 동일한 척도(`100 = 전체 평균`)에서 비교합니다.
3. **10·20대 발견 & 베이지안 수축 (`youth.py`)**
   - 오늘의 이슈·인기 영상 태그·10·20대 쇼핑 고유어로 후보 풀을 넓힌 뒤 **30대 이상 대비 배수**를 측정합니다.
   - 표본 검색량이 극소수인 키워드가 우연히 높은 배수로 튀는 현상을 **베이지안 수축(`배수^w`)**으로 억제합니다.
4. **세대 확산 감지 · POMDP 누적 판단 · 전달 함수 (`diffusion.py`, `pomdp.py`, `kernel.py`)**
   - 10·20대에서 먼저 뜬 유행이 40대 이상으로 번지는지 주간 추이에서 판정합니다 (`확산 대기` → `확산 중` → `윗세대 상승`).
   - 워크포워드 백테스트(과거 시점 판정 → 4주·8주 뒤 실제 확산 채점)와 과거 유행 7종(하이볼·요아정·두바이쫀득쿠키·탕후루 vs 먹태깡·포켓몬빵·러닝크루) 검증을 화면에 투명하게 공개합니다.
   - 하루치 노이즈에 흔들리지 않도록 **부분관측 마르코프 결정과정(POMDP)**으로 국면 확률을 갱신하고, **세대 전달 함수 $h(k)$**로 시차·전달 강도·동시 반응 비율을 분해합니다.
5. **국가 간 전파 · 관심의 속도 · 유행의 모양 (`entities.py`, `flux.py`, `shapes.py`)**
   - **국가 간 전파**: 공개 지식베이스 sitelinks로 언어별 동일 개체를 잇고, 가장 먼저 등장한 나라를 기준으로 다른 언어권에 몇 주 뒤 전파되는지 측정합니다.
   - **관심의 속도**: 각 나라의 최근 90일 중앙값 대비 오늘의 순위 교체율과 상위 10개 조회 쏠림을 비교합니다.
   - **유행의 모양**: 정점 ±7일 분포로 `예고형` / `하루형` / `대칭형` / `여운형` 4분류(1년 뒤 재등장률 교차 검증 완료).
6. **무키 증거 투표 카테고리 분류 (`categories.py`)**
   - 뉴스 섹션·영상 분류·위키 분류·쇼핑 분야·핵심어 사전 등 5종의 독립 증거 투표로 11개 분야(`연예·방송`, `음악`, `게임`, `스포츠`, `패션·뷰티`, `음식`, `테크·IT`, `경제·재테크`, `정치·사회`, `생활·건강`, `기타`)를 자동 분류합니다.

---

## 빠른 시작 (Quick Start)

Python 3.11+ 와 [`uv`](https://docs.astral.sh/uv/)만 있으면 API 키 없이 즉시 실행됩니다.

```bash
# 1. 의존성 설치
uv sync --all-extras

# 2. 실시간 트렌드 수집 및 랭킹 출력
uv run trend-engine collect                # 한국 (KR)
uv run trend-engine collect -r KR-11       # 서울
uv run trend-engine collect -r US          # 미국 (JP, TW, VN, GB 등 Google geo 코드 지원)
uv run trend-engine collect -r KR --json   # AI 에이전트·스크립트용 JSON 출력

# 3. 연령·성별 관심도 및 쇼핑 검색어
uv run trend-engine segments -r KR --top 14 --segments "10대,20대,30대,40대,50대,60대+"
uv run trend-engine keyword 아이폰 갤럭시 --segments "10대,20대,50대"
uv run trend-engine shopping --segments "20대 여성,60대+"

# 4. 웹 대시보드 실행
uv run trend-engine serve --port 8765            # 라이브 대시보드 (http://127.0.0.1:8765)
uv run trend-engine --offline serve --port 8765  # 네트워크 없이 내장 fixture로 즉시 데모
```

### 선택적 환경 변수 (`.env`)

키가 필요한 기능은 `.env.example`을 `.env`로 복사해 설정합니다. 키가 없어도 해당 소스만 건너뛰고 전체 리포트와 대시보드는 정상 동작합니다.

| 기능 | 환경 변수 | 키 없을 때 동작 |
|---|---|---|
| Google 트렌드, 포털 실시간, 위키백과, Google 뉴스 | 불필요 | 기본 활성화 |
| 국가별 커뮤니티·차트 (일본 pixiv, 대만 PTT, 미국 Reddit, 베트남 Kenh14, 앱/음악/게임 차트) | 불필요 | 기본 활성화 |
| 연령·성별 관심도 (네이버 DataLab) | 선택 (`NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`) | 키 없으면 DataLab 웹 엔드포인트로 자동 폴백 |
| 연령·성별 쇼핑 인기 검색어 (네이버 쇼핑인사이트) | 불필요 | 기본 활성화 |
| YouTube 국가별 인기 동영상 | `YOUTUBE_API_KEY` | YouTube 패널만 비활성화 |

---

## 대시보드 화면 구성

단일 무빌드 HTML(`src/trend_engine/web/index.html`)로 동작하며, 다크모드(`light-dark()`), 부드러운 탭 전환(View Transitions API), 모바일 터치 팝오버(Popover API), 키워드별 딥링크 공유를 지원합니다.

| 탭 | 주요 내용 |
|---|---|
| **한눈에** (`#glance`) | 첫 화면. 한국 1위 이슈, 10·20대 1위 키워드, 윗세대로 번지는 키워드, 해외 1위 요약 브리핑 + 항목 클릭 시 해당 탭 상세로 즉시 이동 |
| **10·20대** (`#youth`) | `10대` / `20대` / `10·20대 남녀` × `[지금 \| 7일 \| 30일]` 기준 30대 이상 대비 배수 랭킹, 10대 vs 20대 비교, 분야별 타일·매트릭스, 3주 연속 증가 키워드 |
| **세대 확산** (`#diffusion`) | 단계별(`확산 대기` · `확산 중` · `윗세대 상승`) 현황, 연령(6줄) × 주간 히트맵, 워크포워드 백테스트 적중률, 과거 유행 7건 검증, 세대 전달 함수 표 |
| **나라별** (`#country`) | 국가별 `[실시간 \| 7일 \| 30일]` 이슈 순위 및 상세(한국은 연령·성별 관심도 포함), 인기 앱·동영상·뉴스, 순위 교체율·쏠림, 국가 간 전파, 유행의 모양 |
| **전체 연령** (`#age`) | 오늘의 이슈 × 연령·성별 히트맵(`100 = 전체 평균`), 임의 키워드 직접 비교, 선택한 그룹이 유독 찾는 이슈 및 고유 쇼핑 검색어 |

---

## CLI 명령어 레퍼런스

모든 명령어는 `--json`(구조화 출력)과 `--offline`(네트워크 없이 내장 fixture 사용) 플래그를 지원합니다.

| 명령어 | 설명 |
|---|---|
| `trend-engine collect -r KR [-s google_trends]` | 트렌드 수집 및 통합 랭킹 계산 (SQLite 스냅샷 저장, 이전 대비 `NEW`/`▲`/`▼`) |
| `trend-engine segments -r KR --top 16 --segments "20대,30대"` | 상위 트렌드의 연령·성별 검색 affinity (`100 = 전체 평균`) |
| `trend-engine keyword 키워드1 키워드2 --segments "10대,20대,50대"` | 지정한 키워드들의 연령·성별 검색 affinity 직접 비교 |
| `trend-engine shopping [--segments "20대 여성,60대+"]` | 그룹별 쇼핑 인기 검색어 및 그룹 고유 검색어(`★`) 조회 |
| `trend-engine serve [--host 127.0.0.1] [--port 8000]` | FastAPI 백엔드 + 웹 대시보드 서버 실행 |
| `trend-engine export --out site --regions KR,US,JP` | GitHub Pages 배포용 암호화 정적 사이트(`api/*.dat`) 및 `feed.xml` 생성 |
| `trend-engine health-check [health.json]` | 정적 export 점검 결과 확인 (이상 발생 시 종료코드 `1`) |
| `trend-engine doctor [-r KR]` | 모든 업스트림 소스의 라이브 연결·파싱 상태 점검 |
| `trend-engine record [--regions KR,KR-11,US,JP]` | 라이브 응답으로 `tests/fixtures/` 갱신 |

---

## 알림(Watchlist) & 일별 아카이브

- **워치리스트 알림 (`watchlist.txt`)**: 루트의 `watchlist.txt`에 키워드를 한 줄씩 적어두면 매일 우선 추적되며, **상태가 바뀔 때만**(확산 단계 진입, 10·20대 2배 돌파, 정점 4주 이내 예상, 워치리스트 첫 등장) 대시보드 알림 카드와 RSS(`feed.xml`), 선택적 Slack 웹훅(`SLACK_WEBHOOK_URL`)으로 발송됩니다.
- **일별 아카이브 (`data` 브랜치)**: 매시간 스냅샷은 캐시 DB에, 끝난 날(KST 기준)의 일별 요약은 저장소 `data` 브랜치(`날짜/trends-국가.json`, `segments.json`, `shopping.json`)에 자동 커밋되어 7일·30일 기간 뷰와 백테스트에 사용됩니다.

---

## 정적 배포 (GitHub Pages)

`.github/workflows/pages.yml`이 매시간 데이터를 수집해 `trend-engine export`로 정적 사이트를 빌드하고 GitHub Pages에 배포합니다.

- **사슬형 매시 실행 (`next-run.yml`)**: GitHub Actions의 cron 스케줄 누락을 방지하기 위해, 배포 완료 후 `next-run.yml`이 `hourly` 환경의 대기 타이머(50분)를 거쳐 다음 실행을 체인으로 호출합니다.
- **소스 중립성 & AES-256-GCM 암호화**: 공개 사이트에 배포되는 데이터(`api/*.dat`)는 개별 데이터 소스 식별자를 제거한 뒤(`publish.py`) `TREND_ENGINE_DATA_KEY`(64자리 hex)로 암호화되며, 브라우저의 WebCrypto API로 복호화됩니다 (`tests/test_export.py`로 검증).

### 배포 설정 방법
1. **Settings → Pages → Source**: `GitHub Actions` 선택
2. **Settings → Environments**: `hourly` 환경 생성 후 **Wait timer 50분** 설정
3. **Settings → Secrets and variables → Actions**: `TREND_ENGINE_DATA_KEY`(필수, 64자리 hex) 및 선택적 API 키(`YOUTUBE_API_KEY`, `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET`, `SLACK_WEBHOOK_URL`) 등록
4. **Actions → Deploy dashboard → Run workflow**로 첫 실행 시작

---

## 테스트 및 개발 검증

테스트는 네트워크를 전혀 사용하지 않으며 1초 내외로 실행됩니다.

```bash
# 단위·계약·암호화 누출 테스트 전체 실행 (네트워크 미사용)
uv run pytest -q

# Playwright 실제 브라우저 E2E 테스트 (복호화·전 탭 렌더링·콘솔 에러·다크/라이트 대비 검사)
uv run --group e2e playwright install chromium
E2E=1 uv run --group e2e pytest -m e2e tests/e2e -q

# 라이브 업스트림 점검 (네트워크 사용)
uv run trend-engine doctor
```

---

## 상세 설계 문서

- [`docs/ENGINE.md`](docs/ENGINE.md) — **엔진 핵심 알고리즘** (테마 묶기, 교차 점수, 기준어 정규화, 10·20대 베이지안 수축, 세대 확산 백테스트, POMDP, 세대 전달 함수, 유행의 모양, 국가 간 전파)
- [`docs/POMDP.md`](docs/POMDP.md) — 부분관측 마르코프 결정과정(POMDP) 국면 믿음 갱신·Baum-Welch 재학습·알림 게이트
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — 전체 아키텍처, 데이터 흐름, 점수 공식 명세
- [`docs/SOURCES.md`](docs/SOURCES.md) — 국가별 데이터 소스 범위, 키 유무, 한계 및 차단 목록
- [`docs/SEGMENTS.md`](docs/SEGMENTS.md) — 연령·성별 affinity 산출 수식과 해석 시 주의사항
- [`docs/HARNESS.md`](docs/HARNESS.md) — 오프라인/라이브 테스트 하네스(`doctor`, `record`)
- [`docs/ADDING_A_SOURCE.md`](docs/ADDING_A_SOURCE.md) — 새 트렌드 소스 추가 절차
- [`AGENTS.md`](AGENTS.md) / [`CLAUDE.md`](CLAUDE.md) — AI 코딩 에이전트 작업 가이드 및 불변식
