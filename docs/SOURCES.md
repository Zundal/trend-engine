# Sources

| id | 종류 | 범위 | 키 | 엔드포인트 | 비고 |
|---|---|---|---|---|---|
| `google_trends` | keyword | 모든 Google geo (KR, **KR-11 서울**, US, JP…) | 불필요 | `trends.google.com/trending/rss?geo=` | 공식 RSS. 대략 검색량(`200+`) 포함. 항목 ~10개 |
| `signal_bz` | keyword | 한국 | 불필요 | `api.signal.bz/news/realtime` | **비공식**. 포털 이슈 키워드 top10 |
| `nate` | keyword | 한국 | 불필요 | `nate.com/js/data/jsonLiveKeywordDataV1.js` | **비공식**, EUC-KR. 짧은 검색어 필드 제공(DataLab 에 사용) |
| `wikipedia` | keyword | 언어별 | 불필요 | Wikimedia pageviews top (전일) | 상시 인기 문서 섞임 → 가중치 0.4 |
| `youtube` | content | 국가 | `YOUTUBE_API_KEY` | YouTube Data API v3 `videos.list chart=mostPopular` | 일 할당량 10,000 unit, 호출당 1 unit |
| `google_news` | content | 국가·언어 | 불필요 | `news.google.com/rss` | 개인·비상업 용도 조건 명시됨 |

## 세그먼트/지역 전용 (랭킹 소스 아님)
| 모듈 | 키 | 내용 |
|---|---|---|
| `segments.py` 네이버 검색어 트렌드 | `NAVER_CLIENT_ID/SECRET` (+`NAVER_API`) | 연령(11구간)·성별·기기별 상대 검색량. 요청당 5그룹 |
| `seoul.py` 서울 실시간 도시데이터(인구) | `SEOUL_API_KEY` | 핫스팟 120여 곳의 혼잡도, 성별·10세 단위 연령 비율, 거주/비거주, 예측 |

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

## 후보 소스 (미구현)
X/Twitter 트렌드(유료 API), TikTok Creative Center(스크래핑), 네이버 쇼핑인사이트, 멜론/지니 차트, 넷플릭스 Top10(주간 공개 데이터), Reddit, 카카오 이슈.
