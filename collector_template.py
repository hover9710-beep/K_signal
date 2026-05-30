# -*- coding: utf-8 -*-
"""
수집기 표준 골격(템플릿) — 새 소스 수집기를 만들 때 이 파일을 복사해 채운다.

목적:
    모든 소스 수집기가 '동일한 출력 스키마'로 data/ 에 저장하도록 통일한다.
    이렇게 하면 분석기(trend_analyzer.py)는 소스가 무엇이든 series 만 읽어
    같은 판정 로직을 재사용할 수 있다.

표준 출력 스키마 (data/<SOURCE>_<오늘날짜>.json):
    {
      "source":    "<SOURCE>",            # 소스 키 (sources.py 의 SOURCES 키)
      "collected": "YYYY-MM-DD",          # 수집 실행 날짜
      "window":    {"startDate","endDate","timeUnit"},  # 수집 기간
      "period":    "week",                # 시계열 구간 단위(window.timeUnit 와 동일)
      "meta":      {... SOURCES[SOURCE] ...},            # 소스 메타데이터 사본
      "series":    {"이름": [[period, ratio], ...], ...} # 핵심 시계열
    }

사용법:
    1) 이 파일을 <소스명>_collector.py 로 복사.
    2) 상단 SOURCE 를 sources.py 에 등록된 키로 변경.
    3) fetch_series() 를 소스 API 에 맞게 구현.
    (python 금지 — py 런처 사용)
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta

from dotenv import load_dotenv

from sources import SOURCES

# ──────────────────────────────────────────────────────────────────────
# 이 수집기가 담당할 소스 키. 반드시 sources.py 의 SOURCES 에 등록돼 있어야 한다.
# ──────────────────────────────────────────────────────────────────────
SOURCE = "여기에_소스명"

WEEKS_BACK = 12  # 오늘 기준 최근 N주(소스에 맞게 조정)
DATA_DIR = "data"


def get_meta() -> dict:
    """SOURCES 에서 이 소스의 메타데이터를 가져온다. 미등록이면 명확히 중단."""
    if SOURCE not in SOURCES:
        sys.exit(
            f"[중단] SOURCE='{SOURCE}' 가 sources.py 의 SOURCES 에 없습니다.\n"
            f"  → 가능한 키: {', '.join(SOURCES)}"
        )
    return SOURCES[SOURCE]


def load_credentials() -> dict:
    """.env 에서 자격증명을 로드한다(소스에 따라 불필요할 수 있음).

    필요한 키가 있으면 아래에서 검사하고, 없으면 sys.exit 로 중단한다
    (조용히 빈 값 통과 금지). 자격증명이 필요 없는 소스는 빈 dict 를 반환.
    """
    load_dotenv()
    # 예시) 네이버 계열이면 아래처럼 검사한다. 불필요하면 통째로 제거.
    #   client_id = os.getenv("NAVER_CLIENT_ID")
    #   client_secret = os.getenv("NAVER_CLIENT_SECRET")
    #   missing = [n for n, v in (("NAVER_CLIENT_ID", client_id),
    #                             ("NAVER_CLIENT_SECRET", client_secret))
    #              if not (v and v.strip())]
    #   if missing:
    #       sys.exit("[중단] .env 에 다음 값이 없습니다: " + ", ".join(missing))
    #   return {"client_id": client_id.strip(), "client_secret": client_secret.strip()}
    return {}


def get_window() -> dict:
    """수집 기간(window)을 만든다. 오늘 기준 최근 WEEKS_BACK 주, 주간 단위."""
    end = date.today()
    start = end - timedelta(weeks=WEEKS_BACK)
    return {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "timeUnit": "week",
    }


def fetch_series(creds: dict, window: dict) -> dict[str, list[list]]:
    """[TODO] 소스 API 를 호출해 시계열을 수집한다 — 소스별로 구현.

    반환형(표준): {이름: [[period, ratio], ...], ...}
        - period 는 "YYYY-MM-DD" 문자열, ratio 는 숫자.
        - 각 시계열은 period 오름차순으로 정렬해 반환할 것.

    구현 지침:
        - 요청/응답 오류는 각각 명시적으로 잡아 코드+메시지를 출력하고 중단한다.
          (조용한 except 금지: except 로 삼키고 빈 값 통과시키지 말 것)
        - 외부 라이브러리는 dotenv 만. 요청은 표준 라이브러리(urllib) 사용.
    """
    raise NotImplementedError(
        f"fetch_series() 가 아직 구현되지 않았습니다 (SOURCE='{SOURCE}'). "
        "소스 API 에 맞게 구현하세요."
    )


def save_json(series: dict, window: dict, meta: dict) -> str:
    """표준 스키마로 data/<SOURCE>_<오늘날짜>.json 저장 후 경로를 돌려준다."""
    os.makedirs(DATA_DIR, exist_ok=True)
    today = date.today().isoformat()
    path = os.path.join(DATA_DIR, f"{SOURCE}_{today}.json")

    payload = {
        "source": SOURCE,
        "collected": today,
        "window": window,
        "period": window["timeUnit"],
        "meta": meta,
        "series": {
            name: [[period, ratio] for period, ratio in points]
            for name, points in series.items()
        },
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def print_table(series: dict[str, list[list]], meta: dict) -> None:
    """수집된 시계열을 정렬된 표로 출력한다."""
    print(f"\n수집된 항목({len(series)}개): {', '.join(series.keys())}")
    for name, points in series.items():
        print(f"\n[{name}]")
        if not points:
            print("  (데이터 없음)")
            continue
        print(f"  {'구간(period)':<14}{'값':>10}")
        print(f"  {'-' * 12:<14}{'-' * 8:>10}")
        for period, ratio in points:
            print(f"  {str(period):<14}{ratio:>10.2f}")
    print(f"\n※ 값 단위: {meta['unit']} / 스케일: {meta['scaling']}")


def main() -> None:
    meta = get_meta()
    creds = load_credentials()
    window = get_window()

    print(
        f"[{meta['label']}] 수집 시작 — "
        f"{window['startDate']} ~ {window['endDate']} ({window['timeUnit']} 단위)"
    )

    series = fetch_series(creds, window)
    path = save_json(series, window, meta)
    print_table(series, meta)
    print(f"\n저장 완료 → {path}")


if __name__ == "__main__":
    main()
