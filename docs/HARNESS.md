# Harness

세 층으로 구성된다. 에이전트가 **네트워크 없이 빠르게 검증**하고, 필요할 때만 라이브를 확인하도록 설계했다.

## 1. 오프라인 테스트 (`uv run pytest -q`, <1초)
| 파일 | 검증 |
|---|---|
| `tests/test_contract.py` | 등록된 **모든 소스 × 모든 fixture** 에 대해 parse 계약: 비어있지 않음, rank 1..n 연속, source/region/kind 일치, 순수성, 메타데이터. 소스를 등록하고 fixture 를 넣으면 자동 포함 |
| `tests/test_normalize.py` | 한국어 매칭 규칙 + 과병합 회귀 (`아이폰16` ≠ `아이폰17`) |
| `tests/test_scoring.py` | 점수 공식 골든 값, family, 언급 가산, 추이 상태, 결정성 |
| `tests/test_segments.py` | DataLab affinity 수식을 손계산과 대조, 배치 크기, 합성 플래그 |
| `tests/test_ai.py` | 가짜 LLM 으로 프롬프트 구성·근거 없는 키워드 제거 검증 (API 호출 없음) |
| `tests/test_api.py` | HTTP 전 구간 E2E (오프라인), 키 없을 때 412, 미지원 지역 degrade |

## 1b. 브라우저 E2E (`tests/e2e`, CI 의 e2e 잡)
오프라인 fixture 로 **공개용 정적 사이트(암호화)** 를 빌드 → 로컬 서버 → Chromium 으로 모든 탭 점검:
복호화, 기본 탭(10·20대), 그룹·기간 전환과 주소, 세대 확산 히트맵·과거 사례·적중률, 나라별 상세·기간, 전체 연령 표,
콘솔 에러 0, 출처 이름 노출 0, 모바일(390px) 가로 넘침 0.
```bash
uv sync --group e2e && uv run --group e2e playwright install chromium
E2E=1 uv run --group e2e pytest -m e2e tests/e2e
```

## 1c. 배포 점검·알림
export 가 `health.json` 에 문제(소스 실패, 정상 소스 < 2, 랭킹 < 10, 연령·쇼핑·10·20대·세대 확산 실패)와 경고(예비 경로 사용 등)를 남김 →
`trend-engine health-check` → 배포 워크플로의 `alert` 잡이 **빨간불 + "⚠ 트렌드 수집 경고" 이슈**(열린 동안은 본문만 갱신),
복구되면 자동으로 닫음. 사이트는 성공한 데이터로 계속 배포. 알림 경로 테스트: Actions → Deploy dashboard → Run workflow → simulate_problem.

## 2. 오프라인 실행 (`--offline` / `TREND_ENGINE_OFFLINE=1`)
`Source.collect()` 가 네트워크 대신 `tests/fixtures/<source>/<code>.<ext>` 를 `parse()` 에 넣는다.
DataLab 은 `synthetic_response()`, 서울은 sample fixture. DB 는 `data/offline.db` 로 분리.
→ UI 개발, 데모, 에이전트의 E2E 확인용.

## 3. 라이브 (`doctor`, `record`)
- `trend-engine doctor [-r KR]` — 소스별 fetch+parse 성공 여부·건수·지연(ms), DataLab/서울/Claude 키 상태. 실패 시 종료코드 1 → cron/CI 알림에 사용.
- `trend-engine record --regions KR,KR-11,US,JP` — 라이브 응답으로 fixture 덮어쓰기(파싱 0건이면 쓰지 않음). **커밋 전 diff 검토.**

## 업스트림이 깨졌을 때 절차
1. `doctor` → `fail`/`warn(parsed 0 items)` 확인
2. `record` 로 새 응답 저장
3. `pytest tests/test_contract.py -k <source>` 실패 확인 → `parse()` 수정 → 통과
4. 커밋 (fixture + 코드 함께)

