# -*- coding: utf-8 -*-
"""
네이버 데이터랩 쇼핑인사이트 수집기 — 분야별 클릭 트렌드(+인기 검색어 TODO)

목적:
    네이버 데이터랩 "쇼핑인사이트" API로
      (1) 대분류(분야)별 주간 클릭 ratio 트렌드를 수집한다.  ← 이번 단계 구현
      (2) 분야별 인기 검색어 TOP5 를 수집한다.              ← 다음 단계(골격만)

API 명세 (네이버 데이터랩 / 쇼핑인사이트 분야별 트렌드):
    - URL    : POST https://openapi.naver.com/v1/datalab/shopping/categories
    - 헤더   : X-Naver-Client-Id, X-Naver-Client-Secret,
               Content-Type: application/json
    - 바디   : startDate(YYYY-MM-DD), endDate(YYYY-MM-DD),
               timeUnit("date"|"week"|"month"),
               category=[{"name": 이름, "param": [카테고리코드]}, ...] (한 번에 여러 개)
    - 응답   : results[].title / results[].data[].period / .ratio
    - ratio  : 조회 구간 내 최대 클릭량을 100 으로 한 "상대값"(절대 클릭수 아님).

인증키:
    - .env 에서 NAVER_CLIENT_ID, NAVER_CLIENT_SECRET 를 로드한다(직접 작성).
    - 둘 중 하나라도 없으면 즉시 중단한다(빈 값 통과 금지).

실행:
    py shopping_collector.py
    (python 금지 — py 런처 사용)
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv

# ──────────────────────────────────────────────────────────────────────
# 수집 대상 대분류(분야) 목록 — 편집하기 쉽게 상단에 둔다.
#   (name, param코드). 이름은 우리가 임의로 붙이는 라벨이며, 응답 title 과
#   대조해 코드↔이름 매핑이 맞는지 눈으로 검증할 수 있다.
# ──────────────────────────────────────────────────────────────────────
CATEGORIES = [
    ("패션의류", "50000000"),
    ("패션잡화", "50000001"),
    ("화장품미용", "50000002"),
    ("디지털가전", "50000003"),
    ("가구인테리어", "50000004"),
    ("출산육아", "50000005"),
    ("식품", "50000006"),
    ("스포츠레저", "50000007"),
    ("생활건강", "50000008"),
    ("여가생활편의", "50000009"),
    ("면세점", "50000010"),
]

CATEGORY_URL = "https://openapi.naver.com/v1/datalab/shopping/categories"
TIME_UNIT = "week"  # 주간 단위
WEEKS_BACK = 12  # 오늘 기준 최근 12주
DATA_DIR = "data"

# 데이터랩 쇼핑인사이트는 한 요청의 category 배열을 '최대 3개'까지만 허용한다
# (초과 시 400: "category -> should NOT have more than 3 items").
# 따라서 분야 목록을 3개씩 끊어 여러 번 호출한 뒤 결과를 합친다.
CHUNK_SIZE = 3


def load_credentials() -> tuple[str, str]:
    """.env 에서 네이버 API 인증키를 로드한다. 없으면 명확히 중단."""
    load_dotenv()
    client_id = os.getenv("NAVER_CLIENT_ID")
    client_secret = os.getenv("NAVER_CLIENT_SECRET")

    missing = [
        name
        for name, value in (
            ("NAVER_CLIENT_ID", client_id),
            ("NAVER_CLIENT_SECRET", client_secret),
        )
        # 키 자체가 없거나, 공백뿐인 빈 값도 누락으로 취급한다
        if not (value and value.strip())
    ]
    if missing:
        sys.exit(
            "[중단] .env 에 다음 값이 없습니다: "
            + ", ".join(missing)
            + "\n  → .env 파일에 NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 를 채워주세요."
        )

    return client_id.strip(), client_secret.strip()


def get_window() -> dict:
    """수집 기간(window)을 만든다. 오늘 기준 최근 WEEKS_BACK 주."""
    end = date.today()
    start = end - timedelta(weeks=WEEKS_BACK)
    return {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "timeUnit": TIME_UNIT,
    }


def _post(url: str, client_id: str, client_secret: str, payload: dict) -> dict:
    """공통 POST 요청. 원시 JSON(dict)을 돌려준다. 오류는 명확히 출력 후 중단."""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
        "Content-Type": "application/json",
    }
    req = Request(url, data=body, headers=headers, method="POST")

    try:
        with urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
    except HTTPError as e:
        # 4xx/5xx — 인증 실패(401), 파라미터 오류(400) 등. 응답 본문도 함께 출력.
        detail = ""
        try:
            detail = e.read().decode("utf-8")
        except Exception:
            pass
        sys.exit(f"[중단] HTTPError {e.code}: {e.reason}\n  응답: {detail}")
    except URLError as e:
        # 네트워크/DNS/연결 실패 등
        sys.exit(f"[중단] URLError: {e.reason}")

    return json.loads(raw)


def _chunks(items: list, size: int):
    """리스트를 size 개씩 끊어 순회한다."""
    for i in range(0, len(items), size):
        yield items[i : i + size]


def fetch_category_trends(
    client_id: str, client_secret: str, window: dict
) -> dict[str, list[tuple[str, float]]]:
    """분야별 주간 클릭 트렌드를 수집해 {분야명: [(period, ratio), ...]} 로 정리.

    분야 목록을 CHUNK_SIZE 개씩 끊어 여러 번 호출한 뒤 합친다.
    """
    series: dict[str, list[tuple[str, float]]] = {}

    for chunk in _chunks(CATEGORIES, CHUNK_SIZE):
        payload = {
            "startDate": window["startDate"],
            "endDate": window["endDate"],
            "timeUnit": window["timeUnit"],
            "category": [{"name": name, "param": [code]} for name, code in chunk],
        }
        raw = _post(CATEGORY_URL, client_id, client_secret, payload)

        for result in raw.get("results", []):
            # 응답의 title 은 우리가 보낸 name 을 그대로 돌려준다. 그대로 키로 쓴다.
            title = result.get("title", "")
            points = [
                (point["period"], point["ratio"])
                for point in result.get("data", [])
            ]
            points.sort(key=lambda x: x[0])  # period 오름차순
            series[title] = points

    return series


def fetch_top_keywords(client_id: str, client_secret: str, window: dict) -> dict:
    """[TODO] 분야별 인기 검색어 TOP5 수집 — 다음 단계에서 구현.

    NOTE:
        분야 내 '인기 검색어 순위'는 위의 분야별 트렌드 API
        (.../shopping/categories) 와는 다른 별도 스펙이다.
        데이터랩 쇼핑인사이트의 키워드 관련 엔드포인트
        (.../shopping/category/keywords 등)는 '특정 키워드들의 클릭 추이'를
        주는 것이지 '인기 검색어 TOP N 순위'를 그대로 돌려주는 API 가 아니다.
        따라서 정확한 순위 API 스펙(엔드포인트/파라미터/응답 필드)을 확정한 뒤
        구현한다. 지금은 골격만 두어 후속 작업 위치를 명확히 한다.

    구현 시 예상 흐름:
        1) 각 분야 코드별로 인기 검색어 순위 요청.
        2) 상위 5개(keyword, rank[, ratio]) 추출.
        3) {분야명: [(rank, keyword), ...]} 형태로 정리해 반환.
    """
    # 아직 미구현: 빈 결과를 반환한다(조용한 통과가 아니라 명시적 빈 dict).
    return {}


def save_json(series: dict, window: dict) -> str:
    """data/shopping_categories_YYYY-MM-DD.json 으로 저장하고 경로를 돌려준다."""
    os.makedirs(DATA_DIR, exist_ok=True)
    # 파일명 날짜는 '한국 시간(KST=UTC+9) 기준 오늘'로 명시 생성한다.
    # [이유] GitHub Actions 러너는 UTC라서 단순 date.today() 를 쓰면 한국보다
    #        하루 빠른 날짜로 저장돼(예: 한국 5/31 새벽 → UTC 5/30), 매주 돌려도
    #        새 스냅샷 파일이 안 쌓이는 문제가 있었다. KST 로 고정해 해결한다.
    today = datetime.now(timezone(timedelta(hours=9))).date().isoformat()
    path = os.path.join(DATA_DIR, f"shopping_categories_{today}.json")

    payload = {
        "collected": today,
        "window": window,
        "series": {
            name: [{"period": period, "ratio": ratio} for period, ratio in points]
            for name, points in series.items()
        },
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def print_table(series: dict[str, list[tuple[str, float]]]) -> None:
    """분야별 주간 ratio 를 정렬된 표로 콘솔에 출력한다."""
    # 응답에 들어온 분야명을 그대로 출력 → 코드↔이름 매핑 검증용.
    print(f"\n응답에 포함된 분야({len(series)}개): {', '.join(series.keys())}")

    for name, points in series.items():
        print(f"\n[{name}]")
        if not points:
            print("  (데이터 없음)")
            continue
        print(f"  {'주(period)':<14}{'ratio':>10}")
        print(f"  {'-' * 12:<14}{'-' * 8:>10}")
        for period, ratio in points:
            print(f"  {period:<14}{ratio:>10.2f}")

    print(
        "\n※ ratio 는 조회 구간 내 최대 클릭량을 100 으로 한 상대값입니다 "
        "(절대 클릭수가 아님)."
    )


def main() -> None:
    client_id, client_secret = load_credentials()
    window = get_window()

    print(
        f"네이버 쇼핑인사이트 분야 트렌드 수집 시작 — "
        f"{window['startDate']} ~ {window['endDate']} "
        f"({window['timeUnit']} 단위, 분야 {len(CATEGORIES)}개, "
        f"{CHUNK_SIZE}개씩 분할 호출)"
    )

    series = fetch_category_trends(client_id, client_secret, window)
    path = save_json(series, window)

    print_table(series)

    # 2단계(인기 검색어 TOP5)는 아직 골격만 — 명시적으로 안내.
    _ = fetch_top_keywords(client_id, client_secret, window)
    print("\n[알림] 2단계 '분야별 인기 검색어 TOP5'는 아직 미구현(골격만)입니다.")

    print(f"\n저장 완료 → {path}")


if __name__ == "__main__":
    main()
