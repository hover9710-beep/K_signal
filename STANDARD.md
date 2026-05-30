# KtrendAnalyzer 표준 (STANDARD)

여러 소스(네이버 검색/쇼핑, 구글 트렌드, 레딧, 유튜브 등)를 한 분석기로
다루기 위한 **데이터 스키마 / 레지스트리 / 수집기·분석기 계약**을 정의한다.
새 소스를 추가할 때는 코드가 아니라 가능한 한 이 표준에 맞추기만 하면 된다.

> 실행은 모두 `py <파일>.py` 기준(파이썬 런처). `python` 직접 호출 금지.

---

## 1. 표준 출력 스키마

모든 수집기는 `data/<SOURCE>_<오늘날짜>.json` 에 아래 형태로 저장한다.

```json
{
  "source": "naver_shopping",
  "collected": "2026-05-31",
  "window": { "startDate": "2026-03-08", "endDate": "2026-05-31", "timeUnit": "week" },
  "period": "week",
  "meta": { "label": "...", "type": "...", "scaling": "...", "unit": "...", "exclude_recent": 1, "cross_item": false },
  "series": {
    "패션의류": [["2026-03-08", 94.87], ["2026-03-15", 98.92]],
    "면세점":   []
  }
}
```

필드 의미:

| 필드 | 의미 |
| --- | --- |
| `source` | 소스 키. `sources.py` 의 `SOURCES` 키와 동일. |
| `collected` | 수집 실행 날짜(YYYY-MM-DD). |
| `window` | 수집 기간. `startDate`, `endDate`, `timeUnit`. |
| `period` | 시계열 구간 단위(= `window.timeUnit`). |
| `meta` | `SOURCES[source]` 사본(소스 성격을 데이터에 함께 보존). |
| `series` | `{이름: [[period, ratio], ...]}`. period 오름차순. 빈 항목은 `[]`. |

- `series` 의 각 포인트는 `[period(str "YYYY-MM-DD"), ratio(number)]`.
- 데이터가 없는 항목(예: 면세점)은 **빈 리스트**로 두며 조용히 누락시키지 않는다.

---

## 2. 소스 레지스트리 (`sources.py`)

`SOURCES` 딕셔너리가 소스별 메타데이터의 **단일 출처**다. 필드 의미:

| 필드 | 의미 |
| --- | --- |
| `label` | 사람이 읽는 한국어 표시명(출력/리포트 제목). |
| `type` | 소스 종류. `search` / `shopping` / `web_trends` / `social` / `video` 등. |
| `scaling` | 값 스케일 기준. 아래 3종. |
| `unit` | 값의 의미 단위. 예: `검색 ratio`, `클릭 ratio`, `언급 수`, `조회수`. |
| `exclude_recent` | 진행 중(미완성) 최근 구간을 끝에서 몇 개 제외할지 기본값. |
| `cross_item` | 같은 수집본 안에서 품목 간 절대 비교가 유효한지(True/False). |

`scaling` 값:

- `shared_0_100` : 한 요청 안 모든 품목이 **공유** 0~100 상대값 → 같은 json 안에서는 품목 간 비교 가능.
- `per_item_0_100` : 품목(분야)별로 **각자** 최대=100 → 품목 간 절대 비교 무효, 시간 추세만 유효.
- `absolute` : 절대 수치(조회수/언급수 등) → 그대로 비교 가능.

현재 등록된 소스: `naver_search`, `naver_shopping`, `google_trends`, `reddit`, `youtube`.

---

## 3. 수집기 계약 (`collector_template.py`)

새 수집기는 `collector_template.py` 를 복사해 만든다. 반드시 지킬 것:

1. 상단 `SOURCE` 를 `SOURCES` 에 등록된 키로 설정.
2. `meta` 는 `SOURCES[SOURCE]` 에서 가져온다(수집기가 임의로 정의하지 않음).
3. `fetch_series(creds, window)` 를 구현하고 **`{이름: [[period, ratio], ...]}`** 를 반환(period 오름차순).
4. 저장은 `save_json()` 의 **표준 스키마**를 그대로 사용.
5. 오류 처리: 요청/응답 오류는 각각 명시적으로 잡아 코드+메시지를 출력하고 중단.
   **조용한 except 로 빈 값 통과 금지.**
6. 의존성: 표준 라이브러리 + `python-dotenv` 만. 요청은 `urllib`.
7. 마지막에 표 출력 + `저장 완료 →` 한 줄 출력.

---

## 4. 분석기 계약 (`trend_analyzer.py`)

- 분석기는 `series` 만 읽고 동일한 판정 로직(z-score + Theil-Sen 추세%)을 적용한다.
- 진행 중 구간 제외 수는 소스의 `meta.exclude_recent` 를 기본으로 따른다
  (현재 분석기의 `EXCLUDE_RECENT_WEEKS` 상수는 다음 단계에서 이 값과 연동 예정).
- `scaling` / `cross_item` 에 따라 "품목 간 비교 가능 여부" 안내 문구를 다르게 출력한다.
- 빈 시계열·표본 부족은 `데이터부족` 으로 안전 처리(노이즈 방지).

> 참고: 현 수집기/분석기(`datalab_collector.py`, `shopping_collector.py`,
> `trend_analyzer.py`)는 이 표준으로의 **마이그레이션 대상**이며, 본 문서 작성
> 시점에는 아직 표준 스키마로 전환되지 않았다(다음 단계에서 적용).

---

## 5. 새 소스 추가 절차

1. `sources.py` 의 `SOURCES` 에 새 키와 메타데이터(위 필드)를 추가.
2. `collector_template.py` 를 `<소스명>_collector.py` 로 복사.
3. `SOURCE` 를 새 키로 바꾸고 `fetch_series()` 를 구현.
4. `py <소스명>_collector.py` 실행 → `data/<소스명>_<날짜>.json` 생성 확인.
5. `py trend_analyzer.py` 로 분석(소스 선택 방식은 분석기 마이그레이션 단계에서 확정).
