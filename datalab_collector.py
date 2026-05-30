# -*- coding: utf-8 -*-
"""
네이버 데이터랩 통합검색어 트렌드 수집기 — K-제품 주간 검색 ratio 시계열

목적:
    네이버 데이터랩 "통합검색어 트렌드" API로 K-푸드/제품의 주간 검색 ratio
    시계열을 수집한다. 결과는 data/datalab_YYYY-MM-DD.json 으로 저장하고
    콘솔에는 품목별 주간 ratio 표를 출력한다.

API 명세 (네이버 데이터랩 / 통합검색어 트렌드):
    - URL    : POST https://openapi.naver.com/v1/datalab/search
    - 헤더   : X-Naver-Client-Id, X-Naver-Client-Secret,
               Content-Type: application/json
    - 바디   : startDate(YYYY-MM-DD), endDate(YYYY-MM-DD),
               timeUnit("date"|"week"|"month"), keywordGroups(최대 5개)
    - 응답   : results[].title / results[].data[].period / .ratio
    - ratio  : 조회 구간 내 최대 검색량을 100으로 한 "상대값"이다.
               절대 검색량(건수)이 아니라는 점에 유의.

인증키:
    - .env 에서 NAVER_CLIENT_ID, NAVER_CLIENT_SECRET 를 로드한다(직접 작성).
    - 둘 중 하나라도 없으면 즉시 중단한다(빈 값 통과 금지).

실행:
    py datalab_collector.py
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
# 수집 대상 키워드 그룹 (편집하기 쉽게 파일 상단에 둔다)
#   - groupName : 품목명(표/JSON 의 키로 쓰임)
#   - keywords  : 동의어/표기 변형을 함께 묶으면 합산 트렌드로 집계된다
#                 (예: "두바이초콜릿" + "두바이 초콜릿")
#   - 데이터랩 제약: 한 번에 최대 5개 그룹, 그룹당 키워드 최대 20개
# ──────────────────────────────────────────────────────────────────────
KEYWORD_GROUPS = [
    {"groupName": "약과", "keywords": ["약과"]},
    {"groupName": "마라탕", "keywords": ["마라탕"]},
    {"groupName": "탕후루", "keywords": ["탕후루"]},
    {"groupName": "두바이초콜릿", "keywords": ["두바이초콜릿", "두바이 초콜릿"]},
    {"groupName": "냉동김밥", "keywords": ["냉동김밥", "냉동 김밥"]},
]

API_URL = "https://openapi.naver.com/v1/datalab/search"
TIME_UNIT = "week"  # 주간 단위
WEEKS_BACK = 12  # 오늘 기준 최근 12주
DATA_DIR = "data"


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


def build_payload() -> dict:
    """요청 바디를 만든다. 기간은 오늘 기준 최근 WEEKS_BACK 주."""
    end = date.today()
    start = end - timedelta(weeks=WEEKS_BACK)
    return {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "timeUnit": TIME_UNIT,
        "keywordGroups": KEYWORD_GROUPS,
    }


def fetch_trends(client_id: str, client_secret: str, payload: dict) -> dict:
    """데이터랩 API 를 호출해 원시 JSON 응답(dict)을 돌려준다."""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
        "Content-Type": "application/json",
    }
    req = Request(API_URL, data=body, headers=headers, method="POST")

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


def organize(raw: dict) -> dict[str, list[tuple[str, float]]]:
    """원시 응답을 {품목명: [(period, ratio), ...]} 형태로 정리한다."""
    series: dict[str, list[tuple[str, float]]] = {}
    for result in raw.get("results", []):
        title = result.get("title", "")
        points = [
            (point["period"], point["ratio"])
            for point in result.get("data", [])
        ]
        # period 오름차순 정렬
        points.sort(key=lambda x: x[0])
        series[title] = points
    return series


def save_json(series: dict, window: dict) -> str:
    """data/datalab_YYYY-MM-DD.json 으로 저장하고 경로를 돌려준다."""
    os.makedirs(DATA_DIR, exist_ok=True)
    # 파일명 날짜는 '한국 시간(KST=UTC+9) 기준 오늘'로 명시 생성한다.
    # [이유] GitHub Actions 러너는 UTC라서 단순 date.today() 를 쓰면 한국보다
    #        하루 빠른 날짜로 저장돼(예: 한국 5/31 새벽 → UTC 5/30), 매주 돌려도
    #        새 스냅샷 파일이 안 쌓이는 문제가 있었다. KST 로 고정해 해결한다.
    today = datetime.now(timezone(timedelta(hours=9))).date().isoformat()
    path = os.path.join(DATA_DIR, f"datalab_{today}.json")

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
    """품목별 주간 ratio 를 정렬된 표로 콘솔에 출력한다."""
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
        "\n※ ratio 는 조회 구간 내 최대 검색량을 100 으로 한 상대값입니다 "
        "(절대 검색량이 아님)."
    )


def main() -> None:
    client_id, client_secret = load_credentials()
    payload = build_payload()

    window = {
        "startDate": payload["startDate"],
        "endDate": payload["endDate"],
        "timeUnit": payload["timeUnit"],
    }
    print(
        f"네이버 데이터랩 수집 시작 — {window['startDate']} ~ {window['endDate']} "
        f"({window['timeUnit']} 단위, 품목 {len(KEYWORD_GROUPS)}개)"
    )

    raw = fetch_trends(client_id, client_secret, payload)
    series = organize(raw)
    path = save_json(series, window)

    print_table(series)
    print(f"\n저장 완료 → {path}")


if __name__ == "__main__":
    main()
