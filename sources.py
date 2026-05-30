# -*- coding: utf-8 -*-
"""
소스 레지스트리 — 수집기/분석기가 공유하는 '소스별 메타데이터' 단일 출처.

여기에 한 소스의 성격(라벨/종류/스케일링 방식/단위/진행주 제외 수/품목 간
비교 가능 여부)을 등록해 두면, 수집기(collector_template.py)와 분석기는
이 딕셔너리만 참조해 동작을 맞춘다. 소스가 늘어나도 코드가 아니라 이 표만
고치면 되도록 하는 것이 목적이다.

각 소스 항목 필드 의미:
    label         : 사람이 읽는 한국어 표시명(출력/리포트 제목용).
    type          : 소스 종류 분류. "search"(검색어 트렌드) / "shopping"(쇼핑 클릭)
                    / "web_trends"(웹 검색 트렌드) / "social"(소셜 언급) /
                    "video"(영상 지표) 등. 분석기가 분기 처리에 참고.
    scaling       : ratio 값의 스케일 기준.
                    "shared_0_100"   → 한 요청 안의 모든 품목이 '공유' 0~100 상대값
                                       (같은 json 안에서는 품목 간 비교 가능).
                    "per_item_0_100" → 품목(분야)별로 '각자' 최대=100 으로 스케일
                                       (품목 간 절대 비교 무효, 시간 추세만 유효).
                    "absolute"       → 절대 수치(조회수/언급수 등, 그대로 비교 가능).
    unit          : 값의 의미 단위(주석/리포트 표기에 사용). 예: "검색 ratio",
                    "클릭 ratio", "언급 수", "조회수".
    exclude_recent: 진행 중(미완성) 최근 구간을 끝에서 몇 개 제외할지 기본값.
                    데이터가 덜 쌓인 진행 구간이 '가짜 급락'을 만드는 것을 막는다.
    cross_item    : 같은 수집본(json) 안에서 품목 간 절대 비교가 유효한지 여부.
                    scaling 과 연동되는 안내용 플래그(True/False).
"""
from __future__ import annotations

SOURCES = {
    "naver_search": {
        "label": "네이버 통합검색어 트렌드",
        "type": "search",
        "scaling": "shared_0_100",
        "unit": "검색 ratio",
        "exclude_recent": 1,
        "cross_item": True,
    },
    "naver_shopping": {
        "label": "네이버 쇼핑인사이트(분야별)",
        "type": "shopping",
        "scaling": "per_item_0_100",
        "unit": "클릭 ratio",
        "exclude_recent": 1,
        "cross_item": False,
    },
    "google_trends": {
        "label": "구글 트렌드",
        "type": "web_trends",
        "scaling": "shared_0_100",
        "unit": "검색 관심도",
        "exclude_recent": 1,
        "cross_item": True,
    },
    "reddit": {
        "label": "레딧 언급량",
        "type": "social",
        "scaling": "absolute",
        "unit": "언급 수",
        "exclude_recent": 0,
        "cross_item": True,
    },
    "youtube": {
        "label": "유튜브 지표",
        "type": "video",
        "scaling": "absolute",
        "unit": "조회수",
        "exclude_recent": 0,
        "cross_item": True,
    },
}
