# Harness

세 층으로 구성된다. 에이전트가 **네트워크 없이 빠르게 검증**하고, 필요할 때만 라이브를 확인하도록 설계했다.

## 1. 오프라인 테스트 (`uv run pytest -q`, <1초)
| 파일 | 검증 |
|---|---|
| `tests/test_contract.py` | 등록된 **모든 소스 × 모든 fixture** 에 대해 parse 계약: 비어있지 않음, rank 1..n 연속, source/region/kind 일치, 순수성, 메타데이터. 소스를 등록하고 fixture 를 넣으면 자동 포함 |
| `tests/test_normalize.py` | 한국어 매칭 규칙 + 과병합 회귀 (`아이폰16` ≠ `아이폰17`) |
| `tests/test_scoring.py` | 점수 공식 골든 값, family, 언급 가산, 추이 상태, 결정성 |
| `tests/test_segments.py` | DataLab affinity 수식을 손계산과 대조, 배치 크기, 합성 플래그 |
| `tests/test_seoul.py` | 도시데이터 파싱, sample 판별, 연령 편중 계산 |
| `tests/test_ai.py` | 가짜 LLM 으로 프롬프트 구성·근거 없는 키워드 제거 검증 (API 호출 없음) |
| `tests/test_api.py` | HTTP 전 구간 E2E (오프라인), 키 없을 때 412, 미지원 지역 degrade |

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

## AI 브리핑 평가
`validate_brief` 가 런타임 가드레일(근거 없는 키워드 제거 + `warnings`)이자 평가 지표다.
실사용에서 `warnings` 비율이 높아지면 프롬프트(`ai.SYSTEM`)를 조정한다.
