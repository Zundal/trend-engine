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
| `yahoo_topics` | keyword | 일본 | 불필요 | `news.yahoo.co.jp/rss/topics/{top-picks,domestic,entertainment,sports,it}.xml` | 짧은 헤드라인 ≈ 포털 이슈. KR 의 signal/nate 역할 |
| `hatena` | content | 일본 | 불필요 | `b.hatena.ne.jp/hotentry.rss` | 하테나 북마크 인기글 (RSS 1.0 RDF) |
| `nicovideo` | content | 일본 | 불필요 | `nvapi.nicovideo.jp/v1/ranking/genre/all?term=24h` (`X-Frontend-Id: 6`) | 니코니코 24h 랭킹 — 젊은 층 영상 |
| `billboard_japan` | content | 일본 | 불필요 | `billboard-japan.com/charts/detail?a=hot100` | Hot 100 HTML. KR 멜론에 대응 |
| `livedoor_trend` | content | 일본 | 불필요 | `news.livedoor.com/topics/rss/trend.xml` | 라이브도어 트렌드 토픽 |
| `billboard_us` | content | 미국 | 불필요 | `billboard.com/charts/hot-100/` | Hot 100 HTML (`h3#title-of-a-story` + `c-label`) |
| `yahoo_us` | content | 미국 | 불필요 | `news.yahoo.com/rss/` | 야후 미국 뉴스 |
| `official_charts` | content | 영국 | 불필요 | `officialcharts.com/charts/singles-chart/` | Official Singles Chart HTML |
| `bbc_news` | content | 영국 | 불필요 | `feeds.bbci.co.uk/news/rss.xml` | BBC 뉴스 헤드라인 |
| `yahoo_tw_search` | keyword | 대만 | 불필요 | `tw.yahoo.com/` 헤더 `熱搜` (`data-ylk` 의 `tts-term`) | 포털 인기 검색어 ~11개. `kt:rev`(유료 노출)는 버림. KR signal/nate 역할 |
| `kkbox_tw` | content | 대만 | 불필요 | `kma.kkbox.com/charts/api/v1/daily?terr=tw&type=song` | KKBOX 일간 차트 JSON (멜론 역할) |
| `yahoo_tw` | content | 대만 | 불필요 | `tw.news.yahoo.com/rss/` | 야후 대만 뉴스 |
| `gnn_tw` | content | 대만 | 불필요 | `gnn.gamer.com.tw/rss.xml` | 바하무트 GNN 게임 뉴스 |
| `vnexpress` | content | 베트남 | 불필요 | `vnexpress.net/rss/tin-xem-nhieu.rss` | 많이 본 뉴스 |
| `zum_issue` | keyword | 한국 | 불필요 | `zum.com/` 홈의 `issueWords` 데이터 (robots 는 홈만 허용) | AI 이슈트렌드 ~16개. 기사 묶음 기반이라 family 따로 |
| `tuoitre` · `dantri` · `thanhnien` | content | 베트남 | 불필요 | 각 사 최신 RSS | 구글 검색어의 헤드라인 확인용 (각 30개) |
| `trends24` | keyword | 일본 | 불필요 | `trends24.in/japan/` 최신 시간대 `trend-card__list` | X 트렌드 30개. robots 허용(`use=reference`). family `x_trends`. 미국·영국 페이지는 배포 서버 IP 를 Cloudflare 403 으로 막음 |
| `getdaytrends` | keyword | 미국·영국 | 불필요 | `getdaytrends.com/<나라>/` '지금' 표 2개 (`ranking trends`) | X 트렌드 30개. 배포 서버에서 열림(2026-10-26 Actions 시험). family `x_trends` |
| `yahoo_trending` | keyword | 미국·영국 | 불필요 | `uk.yahoo.com/`·`www.yahoo.com/` 홈 `subsec:trending_search` | 포털 인기 검색어. 영국은 검색어 10개, 미국은 기사 제목 5개 |
| `yahoo_realtime` | keyword | 일본 | 불필요 | `search.yahoo.co.jp/realtime` 트렌드(`_cl_link:atk`) | X 게시물 기반 화제어 20개. family `x_trends` (trends24 와 중복 집계 안 함) |
| `ettoday` | content | 대만 | 불필요 | `feeds.feedburner.com/ettoday/{star,game}` | 연예(星光雲)·게임 섹션 기사 제목 (각 25건) |
| `reddit` | content | 미국 | 불필요 | `reddit.com/r/teenagers+GenZ/hot/.rss` | 영어권 10·20대 서브레딧. **익명 한도가 낮아 US 에만** (영국도 같은 내용) |
| `kenh14` | content | 베트남 | 불필요 | `kenh14.vn/rss/home.rss` | 베트남 젊은 층 매체 |
| `steam` | content | 전 국가 | 불필요 | `ISteamChartsService/GetMostPlayedGames` + `appdetails` | 최다 플레이 게임 12개(전 세계 공통) — 게임 분야 신호 |
| `melon` | content | 한국 | 불필요 | `melon.com/chart/index.json` | 멜론 TOP50. 국내 10·20대 음악·팬덤 신호 (애플 차트 보완) |
| `netflix` | content | 전 국가 | 불필요 | `netflix.com/tudum/top10/data/all-weeks-global.tsv` | 주간 글로벌 Top10(영화·TV 40편). **Chrome UA 금지**(unsupportedbrowser). 나라별 TSV(~30MB)는 수집 주기상 제외 |
| `google_news` | content | 국가·언어 | 불필요 | `news.google.com/rss` | 개인·비상업 용도 조건 명시됨 |

## 시도했다가 뺀 것: 헤드라인 합의 키워드 (2026-10-25)
미국·영국·베트남처럼 포털 인기 검색어가 없는 나라에서, 매체 2곳 이상이 함께 쓴 고유명사를 키워드로 넣어 봤다.
같은 시점 실데이터로 비교하니 상위 20개 중 다른 소스가 확인한 이슈 수가 **늘지 않았다**(미국 5→4).
헤드라인에 나온 이슈는 이미 '헤드라인 언급'으로 확인되므로 새 확인이 생기지 않고, `Trump`·`Ukraine` 같은 상시 이름이
확인된 이슈를 밀어냈다. 이 나라들에 필요한 건 파생 키워드가 아니라 **진짜 포털 인기 검색어 피드**다.

## 배포 서버에서 막힌 소스 확인법 (2026-10-26)
로컬에서 되는 소스도 GitHub Actions IP 에선 막힐 수 있다(trends24 미국·영국 403). 새 비공식 페이지를 붙이기 전에
임시 브랜치에 push 트리거 워크플로를 올려 `curl` 로 HTTP 코드와 목록 표식 개수만 찍어 보고, 브랜치는 지운다.
같은 시점 측정(상위 20개 중 확인된 이슈): 미국 4→10, 영국 2→8 (getdaytrends + 야후 Trending).

## X 트렌드 나라 선택 (2026-10-25)
같은 시점 실데이터, 상위 20개 중 다른 소스가 확인한 이슈 수 (추가 전 → 후):
일본 4→8, 영국 2→8, 미국 5→6. 한국 7→5, 베트남 7→5 로 **오히려 줄어** 뺐다 —
한국은 팬덤 생일·투표 해시태그, 베트남은 태국 드라마 해시태그가 목록 대부분이라 확인된 이슈를 밀어낸다.
대만은 trends24 페이지가 없다(404). 대신 한국은 ZUM 이슈트렌드(7→14), 베트남은 종합지 RSS 3곳(9→13)을 더했다.
베트남 X 목록은 코인·태국 드라마 태그가 대부분이고, 베트남 언론 홈에는 키 없는 인기 검색어 블록이 없다(2026-10-25 확인).

## 과거 데이터 (랭킹 소스 아님)
| 모듈 | 키 | 내용 |
|---|---|---|
| `pageviews.py` | 불필요 | 위키미디어 REST: **지난 날짜의 인기 문서 목록**(2015~)과 **문서별 일별 조회수**. 상대값(0~100)이 아니라 **절대 조회수**라 나라 간 비교·쏠림 계산이 가능하다. 교체율·쏠림(`flux.py`)이 여기서 나온다. 지난 날짜는 변하지 않으므로 1년 캐시. |

## 세그먼트/지역 전용 (랭킹 소스 아님)
| 모듈 | 키 | 내용 |
|---|---|---|
| `segments.py` 네이버 검색어 트렌드 | 선택 (`NAVER_CLIENT_ID/SECRET`, `NAVER_API`) | 연령(11구간)·성별 상대 검색량. 요청당 5그룹. 키 없으면 **web 모드** |
| `shopping.py` 네이버 쇼핑인사이트 | 불필요 | 11개 쇼핑 분야 × 연령(10대~60대)·성별 인기 검색어 top N. **비공식 웹 엔드포인트** |
| `appcharts.py` 유료 앱 판매 순위 | 불필요 | `itunes.apple.com/{국가}/rss/toppaidapplications/limit=20/genre={분야}/json`. 나라 × 25개 분야 상위 20개, 6시간 캐시. 인앱 결제 매출은 반영하지 않는다. 구글 플레이는 분야별 인기 페이지(`/store/apps/top/category/GAME`) 응답에 유료 순위가 없어 뺐다 (2026-11-01 확인) |

## 소비 트렌드 (랭킹 소스 아님, `consumer/`) — 2026-11-18 조사
나라 × 분야별 "많이 사는 것" 순위. 모두 키 불필요. 목록(Board) 하나 = 업스트림 순위표 하나, 6시간 캐시(주간·월간 목록은 12~24시간),
실패하면 3일 안의 마지막 결과를 `stale` 로 보인다. 사이트가 막으면(403·429·5xx·봇 확인 페이지) 그 사이트는 3시간 쉰다.
공개 뷰에는 제공처 이름 없이 분야·카드 제목·기준만 나간다(`publish.public_consumer`).

| 나라 | 모듈 | 목록 |
|---|---|---|
| 공통 6개국 | `common.py` | 애플 앱 매출 순위(전체 + 14개 분야) · 영화·TV 시즌·앨범·전자책·오디오북 판매(나라마다 있는 것만) · 스팀 주간 매출(베트남 제외: 주간 차트가 없다) + 지금 판매(전체·9개 장르; 상점 검색은 빠른 연속 요청에 429 라 2초 간격, 장르는 하루 1회) · Xbox 판매 순위 |
| 한국 | `kr.py` | 네이버 플러스스토어 베스트(구매 순, 13개 연령·성별 + 10개 분야) · 11번가 베스트(13개 코너) · 옥션 분야별 베스트(29개, `corners.auction.co.kr`) · 카카오톡 선물하기(12개 분야) · 무신사(연령대 7 + 분야 11 + 인기 검색어) · 29CM(12개 분야) · 화해(급상승 12 + 연령대 4) · 컬리(11개 분야) · 알라딘 주간(15개 분야) · 예스24(국내도서·전자책·CD/LP·DVD) · 리디(일반·판타지) · KOBIS 실시간 예매율·어제 관객(CSRF 토큰 GET→POST) · NOL 티켓 예매 순위(7개 장르) |
| 일본 | `jp.py` | 가격.com 분야별 인기(22개, **관심도 순위 — 판매량 아님**) · BCN 가전 판매 집계(11개, 월간) · 오리콘 주간 추정 판매량(도서 10·음반 4·영상 2) · 패미통 게임 소프트 판매량 · 기노쿠니야 베스트셀러(4개, robots `Crawl-delay: 10` → `Board.pace`). 오리콘은 8번 연속 요청에 확인 페이지(429)를 내서 5초 간격 + 하루 1회 · eiga.com 주말 박스오피스 |
| 미국 | `usgb.py` | The Numbers 주말·일별 박스오피스 · Publishers Weekly 베스트셀러(6개) · 아마존 베스트셀러(분야별) |
| 영국 | `usgb.py` | BFI 주말 박스오피스(ODS) · Official Charts 영상물 4 + 음반 6 · 아마존 UK 베스트셀러(분야별) |
| 대만 | `twvn.py` | PChome 24h 분야별 Top(64개, 18금 상품 제외) · 金石堂 주간 베스트셀러(10개 분야, 18금 표지 제외) |
| 베트남 | — | 공통 목록만 |

**막힌 곳(쓰지 않음)**:
- 한국: G마켓 · 올리브영 · 쿠팡 · 오늘의집 · SSG · 에이블리 · CGV는 봇 차단이다. W컨셉 · 교보문고는 키가 필요하고, 지그재그 · KREAM · 다이소몰은 스크립트로만 그린다. 다나와는 `prod.` 호스트만 열리는데 형제 호스트가 Akamai라 위험해 보류했다.
- 일본: 라쿠텐 · 야후 쇼핑 · @cosme · ZOZOTOWN · Qoo10 · 드러그스토어 · 가전 양판점 · 아마존 JP는 봇 차단이다. 라쿠텐 북스 내부 API는 쓰지 않는다.
- 대만: momo · 博客來 · 誠品 · Shopee · 屈臣氏는 막혔고, Readmoo는 응답에 출판사 개인정보가 섞여 뺐다.
- 베트남: Tiki는 브라우저가 아닌 클라이언트를 403으로 막고, Shopee · Lazada · Fahasa · FPT · Thế Giới Di Động도 막혔다. 극장 흥행 집계도 없다.
- 미국 · 영국: 빌보드 200은 5MB 응답이라 픽스처로 부적합해 뺐다.

**주의**:
- 국내 가정 회선에서만 확인한 것들(무신사 · 29CM · 11번가 · NOL · 리디: Cloudflare, KOBIS · 예스24: 해외 IP)은 배포 서버(미국 IP)에서 막힐 수 있다. 막히면 health 경고에 `consumer KR: … errors` 로 보이고 지난 결과가 남는다.
- 점검은 `uv run trend-engine doctor --consumer -r KR`(목록마다 1회), 픽스처 갱신은 `record --consumer all --regions …`(나라 × 파서마다 하나, `TRIMS` 로 줄여 저장)으로 한다.

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
되는 것: 위 표 + 애플 차트(전 국가). 막힌 것: **Dcard**(대만, 403) · **니코니코 RSS**(빈 응답) ·
**TikTok 크리에이티브 센터**(로그인) · **Pinterest**(키 필요) · **디시인사이드 hit RSS**(빈 응답) ·
**PTT**(대만) — 로컬 IP 에서는 되지만 Cloudflare 가 데이터센터 IP(GitHub Actions)를 403 으로 막는다. 코드는 `sources/local.py` 에 남겨뒀고, 자체 서버에서 돌릴 때 레지스트리에 넣으면 된다.
일본은 야후 토픽(키워드) + 하테나·니코니코·빌보드재팬·라이브도어·pixiv + 애플로 KR 에 가깝게 맞췄다.
미국은 빌보드 Hot 100, 영국은 Official Charts + BBC, 대만은 KKBOX + 야후 대만 + GNN + ETtoday,
베트남은 VnExpress + Kenh14 를 더했다. 연령·성별 **실측은 여전히 한국뿐**(네이버 DataLab).

## 후보 소스 (미구현)
X/Twitter 트렌드(유료 API), TikTok Creative Center(스크래핑), 카카오 이슈.
나라별 넷플릭스 Top10 TSV(`all-weeks-countries.tsv`, ~30MB) — 주간 캐시가 생기면 검토.
