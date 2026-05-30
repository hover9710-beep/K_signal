# -*- coding: utf-8 -*-
"""
Flask 웹 대시보드 — K-제품 트렌드 분석 결과를 웹페이지로 보여준다.

특징:
    - 분석 로직은 trend_analyzer.py 를 그대로 import 해 '재사용'한다(복붙 금지).
      (z-score, Theil-Sen 추세%, 진행 주 제외, 종합판정 모두 동일 로직)
    - data/ 에서 네이버 검색(datalab_*.json) / 쇼핑인사이트
      (shopping_categories_*.json) 의 최신 파일을 각각 읽어 분석한 뒤,
      두 소스 결과 표를 한 페이지에 표시한다.
    - 소스별 메타데이터(sources.py 의 SOURCES)에서 cross_item/scaling/unit 을
      가져와 '품목 간 비교 가능 여부' 안내 문구를 함께 보여준다.

로컬 실행:
    py app.py            →  http://127.0.0.1:5000

배포(Render 등):
    환경변수 PORT 로 포트 주입, host="0.0.0.0" 으로 외부 바인딩.
"""
from __future__ import annotations

import os

from flask import Flask, render_template

# trend_analyzer 의 분석 로직을 그대로 재사용한다(로직 복붙 금지).
from trend_analyzer import (
    EXCLUDE_RECENT_WEEKS,
    VERDICT_CSS_CLASS,
    WINDOW,
    _fmt_html,
    analyze_series,
    find_latest_for,
    load_series,
)
from sources import SOURCES

app = Flask(__name__)

# ──────────────────────────────────────────────────────────────────────
# 화면에 표시할 소스 목록.
#   pattern_key : trend_analyzer.SOURCE_PATTERNS 의 키(파일 glob 선택용).
#   meta_key    : sources.py SOURCES 의 키(라벨/스케일링/비교가능 여부 등).
# ──────────────────────────────────────────────────────────────────────
SOURCE_VIEWS = [
    {"pattern_key": "search", "meta_key": "naver_search"},
    {"pattern_key": "shopping", "meta_key": "naver_shopping"},
]


def _cross_item_note(meta: dict) -> str:
    """meta(scaling/cross_item)를 사람이 읽는 '비교 가능 여부' 안내 문구로 변환."""
    if meta.get("cross_item"):
        return (
            "같은 수집본(json) 안에서는 품목 간 절대 비교가 유효합니다 "
            f"(스케일: {meta['scaling']})."
        )
    return (
        "분야별로 각자 최대=100 으로 스케일되므로 분야 간 절대 비교는 무효이고, "
        f"같은 분야의 시간 추세만 유효합니다 (스케일: {meta['scaling']})."
    )


def build_source_view(pattern_key: str, meta_key: str) -> dict:
    """한 소스에 대해 최신 파일을 찾아 분석하고, 템플릿용 뷰모델을 만든다.

    파일이 없거나 읽기/분석 중 오류가 나도 서버가 죽지 않도록 방어적으로 처리하고,
    소스별 에러 메시지를 뷰모델에 담아 화면에 노출한다(조용한 실패 금지).
    """
    meta = SOURCES[meta_key]
    view = {
        "meta_key": meta_key,
        "label": meta["label"],
        "unit": meta["unit"],
        "scaling": meta["scaling"],
        "cross_item": meta["cross_item"],
        "note": _cross_item_note(meta),
        "rows": [],
        "eval_week": "-",
        "source_file": None,
        "error": None,
    }

    path = find_latest_for(pattern_key)
    if not path:
        view["error"] = "수집된 데이터 파일이 없습니다. 먼저 수집기를 실행하세요."
        return view

    view["source_file"] = os.path.basename(path)
    try:
        series = load_series(path)
        analyzed = analyze_series(series)
    except SystemExit as e:
        # load_series 는 CLI 용으로 sys.exit 를 쓰므로 웹에서는 잡아서 표시한다.
        view["error"] = f"데이터 분석 실패: {e}"
        return view
    except Exception as e:  # 예기치 못한 오류도 조용히 넘기지 않고 화면에 표시
        view["error"] = f"데이터 분석 중 오류: {e}"
        return view

    # 평가 기준주: 데이터부족이 아닌 첫 행의 평가주(대부분 품목이 동일 주).
    view["eval_week"] = next(
        (r["period"] for _, r in analyzed if r["verdict"] != "데이터부족"), "-"
    )

    for name, r in analyzed:
        view["rows"].append(
            {
                "name": name,
                "period": r["period"],
                "value": _fmt_html(r["value"], 2),
                "z": _fmt_html(r["z"], 2),
                "trend": _fmt_html(r["trend"], 2),
                "verdict": r["verdict"],
                "css": VERDICT_CSS_CLASS.get(r["verdict"], "flat"),
            }
        )
    return view


@app.route("/")
def index():
    """두 소스의 최신 분석 결과를 한 페이지에 표시한다(기본 화면, 필터 없음)."""
    sources = [
        build_source_view(v["pattern_key"], v["meta_key"]) for v in SOURCE_VIEWS
    ]
    exclude_note = (
        "진행 중 주 제외 없음"
        if EXCLUDE_RECENT_WEEKS == 0
        else f"진행 중(미완성) 마지막 {EXCLUDE_RECENT_WEEKS}개 주 제외"
    )
    return render_template(
        "index.html",
        sources=sources,
        window=WINDOW,
        exclude_note=exclude_note,
    )


if __name__ == "__main__":
    # 로컬은 5000, 배포(Render 등)는 환경변수 PORT 를 사용. 외부 바인딩 0.0.0.0.
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
