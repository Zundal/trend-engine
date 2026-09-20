# Sources

| id | 종류 | 범위 | 키 | 엔드포인트 | 비고 |
|---|---|---|---|---|---|
| `google_trends` | keyword | 모든 Google geo (KR, **KR-11 서울**, US, JP…) | 불필요 | `trends.google.com/trending/rss?geo=` | 공식 RSS. 대략 검색량(`200+`) 포함. 항목 ~10개 |
| `signal_bz` | keyword | 한국 | 불필요 | `api.signal.bz/news/realtime` | **비공식**. 포털 이슈 키워드 top10 |
| `nate` | keyword | 한국 | 불필요 | `nate.com/js/data/jsonLiveKeywordDataV1.js` | **비공식**, EUC-KR. 짧은 검색어 필드 제공(DataLab 에 사용) |
| `wikipedia` | keyword | 언어별 | 불필요 | Wikimedia pageviews top (전일) | 상시 인기 문서 섞임 → 가중치 0.4 |
| `youtube` | content | 국가 | `YOUTUBE_API_KEY` | YouTube Data API v3 `videos.list chart=mostPopular` | 일 할당량 10,000 unit, 호출당 1 unit |
| `apple_charts` | content | 모든 나라 | 불필요 | `itunes.apple.com/{국가}/rss/topsongs · topfreeapplications` | 나라별 인기 음악·무료 앱 20개씩. 해외 10·20대 신호가 약한 곳을 보완하고 카테고리(음악/테크) 근거로 쓰임 |
| `pixiv` | content | 일본 | 불필요 | `pixiv.net/ranking.php?mode=daily&format=json` (Referer 필요) | 일간 일러스트 랭킹 — 일본 10·20대 애니·게임 팬덤 신호 |
| `ettoday` | content | 대만 | 불필요 | `feeds.feedburner.com/ettoday/{star,game}` | 연예(星光雲)·게임 섹션 기사 제목 (각 25건) |
| `reddit` | content | 미국 | 불필요 | `reddit.com/r/teenagers+GenZ/hot/.rss` | 영어권 10·20대 서브레딧. **익명 한도가 낮아 US 에만** (영국도 같은 내용) |
| `kenh14` | content | 베트남 | 불필요 | `kenh14.vn/rss/home.rss` | 베트남 젊은 층 매체 |
| `steam` | content | 전 국가 | 불필요 | `ISteamChartsService/GetMostPlayedGames` + `appdetails` | 최다 플레이 게임 12개(전 세계 공통) — 게임 분야 신호 |
| `google_news` | content | 국가·언어 | 불필요 | `news.google.com/rss` | 개인·비상업 용도 조건 명시됨 |

## 과거 데이터 (랭킹 소스 아님)
| 모듈 | 키 | 내용 |
|---|---|---|
| `pageviews.py` | 불필요 | 위키미디어 REST: **지난 날짜의 인기 문서 목록**(2015~)과 **문서별 일별 조회수**. 상대값(0~100)이 아니라 **절대 조회수**라 나라 간 비교·쏠림 계산이 가능하다. 교체율·쏠림(`flux.py`)이 여기서 나온다. 지난 날짜는 변하지 않으므로 1년 캐시. |

## 세그먼트/지역 전용 (랭킹 소스 아님)
| 모듈 | 키 | 내용 |
|---|---|---|
| `segments.py` 네이버 검색어 트렌드 | 선택 (`NAVER_CLIENT_ID/SECRET`, `NAVER_API`) | 연령(11구간)·성별 상대 검색량. 요청당 5그룹. 키 없으면 **web 모드** |
| `shopping.py` 네이버 쇼핑인사이트 | 불필요 | 11개 쇼핑 분야 × 연령(10대~60대)·성별 인기 검색어 top N. **비공식 웹 엔드포인트** |

## 네이버 경로 자동 전환
`Settings.naver_modes`: 키가 있으면 [공식 API(hub) → 웹], 없으면 [웹]. 한 경로가 실패하면 다음 경로로 자동 재시도하고,
배포 점검(health)에 "예비 경로로 대체" 경고를 남긴다. 둘 다 실패하면 경고 이슈가 열린다.

## 네이버 키 없는 모드 (web)
- 검색어 트렌드: `datalab.naver.com` 의 공개 웹 폼과 같은 흐름 (`POST /qcHash.naver` → `GET /keyword/trendResult.naver?hashKey=` 의 `graph_data`).
  응답 수치는 공식 API 와 동일(요청 내 최대=100).
- 쇼핑인사이트: `POST /shoppingInsight/getCategoryKeywordRank.naver` (cid, age=10..60, gender=f/m).
- **요청 간격을 지켜야 한다.** 폼 페이지를 매번 다시 열거나 몰아서 보내면 HTTP 429 → 이후 요청이 느려진다.
  구현: 세션당 폼 1회 방문, 순차 호출, 검색어 트렌드 2.5초 / 쇼핑 1초 간격, 429 시 Retry-After 또는 20·40·80초 대기.
- 비공식 경로라 예고 없이 막히거나 바뀔 수 있다 → `doctor` 로 감시, 막히면 키(API HUB)로 전환.
- 네이버 이용약관상 자동화된 수집이 제한될 수 있다. 개인·연구용 저빈도 사용을 전제로 하며, 상업적 사용이면 공식 API 를 쓸 것.

## 네이버에 대해
- **2026-07-31 부터 검색어 트렌드 신규 키는 NAVER API HUB(네이버 클라우드 플랫폼)에서만 발급.**
  엔드포인트 `https://naverapihub.apigw.ntruss.com/search-trend/v1/search`,
  헤더 `X-NCP-APIGW-API-KEY-ID` / `X-NCP-APIGW-API-KEY`. 요청·응답 본문은 기존 DataLab 과 동일.
  기존 개발자센터 키(`openapi.naver.com`, `X-Naver-Client-*`)는 2027-06-30 까지 → `NAVER_API=legacy`.
- 네이버 실시간 검색어는 2021년 폐지. 대체로 **포털 이슈 키워드(시그널·네이트)** + **DataLab(연령·성별)** 조합을 쓴다.
- DataLab 은 "무엇이 뜨는지"를 발견해주지 않는다 — 다른 소스가 발견한 키워드를 **프로파일링**하는 용도.
- 쇼핑인사이트(카테고리별 연령 클릭 추이)도 같은 키로 쓸 수 있다 → 향후 소스 후보.

## 이용 시 주의
- 비공식 엔드포인트는 예고 없이 바뀐다. `trend-engine doctor` 로 주기 점검하고, 깨지면 `record` → contract 테스트로 수정.
- 고빈도 폴링 금지. 수집 주기는 10~30분 권장.
- 각 서비스 이용약관(특히 Google News RSS 의 비상업 조건)을 상업적 사용 전 확인할 것.

## 나라별 키 없는 플랫폼 조사 결과 (2026-09-20)
되는 것: 위 표 + 애플 차트(전 국가). 막힌 것: **Dcard**(대만, 403) · **니코니코 RSS**(빈 응답) · **야후 재팬 실시간**(자바스크립트) ·
**TikTok 크리에이티브 센터**(로그인) · **Pinterest**(키 필요) · **디시인사이드 hit RSS**(빈 응답) ·
**PTT**(대만) — 로컬 IP 에서는 되지만 Cloudflare 가 데이터센터 IP(GitHub Actions)를 403 으로 막는다. 코드는 `sources/local.py` 에 남겨뒀고, 자체 서버에서 돌릴 때 레지스트리에 넣으면 된다.
일본은 pixiv + 애플로, 대만은 ETtoday + 애플로 보완했고, 베트남은 Kenh14 로 채웠다. 연령·성별 **실측은 여전히 한국뿐**.

## 후보 소스 (미구현)
X/Twitter 트렌드(유료 API), TikTok Creative Center(스크래핑), 네이버 쇼핑인사이트, 멜론/지니 차트, 넷플릭스 Top10(주간 공개 데이터), Reddit, 카카오 이슈.
