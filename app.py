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

import json
import os

from flask import Flask, jsonify, render_template, request

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
# 한글 키워드가 \uXXXX 로 이스케이프되지 않고 UTF-8 그대로 나가도록 한다(외부 소비 편의).
app.json.ensure_ascii = False

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


# ══════════════════════════════════════════════════════════════════════
# 외부용 읽기 전용 JSON API — GET /api/trending
#
#   목적 : 동대문 등 외부 사이트가 '최신 수집분의 인기 키워드'를 가져가도록
#          공개 JSON 을 제공한다. DB(=data/ 의 json)만 읽고, 요청 시 크롤링이나
#          외부(네이버) 호출은 절대 하지 않는다(수집은 별도 주간 배치가 담당).
#
#   소스 : 네이버 데이터랩 '통합검색어 트렌드'(datalab_*.json)만 사용한다.
#          이 소스는 scaling=shared_0_100(cross_item=True)라 같은 수집본 안에서
#          품목 간 ratio 비교가 유효하므로 '인기 순위'를 매기는 것이 타당하다.
#          (쇼핑인사이트는 분야별 각자 0~100 스케일이라 순위 비교가 무효 → 제외)
#
#   기준주: trend_analyzer 의 EXCLUDE_RECENT_WEEKS 를 그대로 재사용해, 아직
#          덜 쌓인 '진행 중 주'를 제외한 '마지막 완성 주'를 순위/전주대비 기준으로
#          삼는다(가짜 급락 방지, 대시보드·분석기와 동일 기준).
# ══════════════════════════════════════════════════════════════════════

# 인기 키워드 랭킹의 소스(sources.py 키). 검색어 트렌드는 품목 간 비교가 유효하다.
TRENDING_SOURCE_PATTERN = "search"      # trend_analyzer.SOURCE_PATTERNS 의 키
TRENDING_SOURCE_META = "naver_search"   # sources.py SOURCES 의 키
NAVER_DATALAB_URL = "https://datalab.naver.com/"

DEFAULT_LIMIT = 10
MAX_LIMIT = 100

# 주간 수집이라 자주 바뀌지 않는다. 1시간 공개 캐시(동대문 사이트/프록시가 캐싱).
TRENDING_CACHE_SECONDS = 3600


def _parse_limit(raw: str | None) -> int:
    """?limit= 을 1..MAX_LIMIT 로 안전 파싱한다(잘못된 값은 기본값)."""
    if raw is None:
        return DEFAULT_LIMIT
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_LIMIT
    return max(1, min(MAX_LIMIT, value))


def _reference_weeks(points: list[tuple[str, float]]) -> tuple[str, float, float | None] | None:
    """진행 중 주(EXCLUDE_RECENT_WEEKS)를 제외한 '마지막 완성 주'와 그 전주 값을 돌려준다.

    반환: (기준주 period, 기준주 ratio, 전주 ratio | None). 완성 주가 없으면 None.
    분석기와 동일한 제외 규칙을 재사용해 순위·전주대비의 기준을 일치시킨다.
    """
    weeks = points[:-EXCLUDE_RECENT_WEEKS] if EXCLUDE_RECENT_WEEKS > 0 else points
    if not weeks:
        return None
    ref_period, ref_value = weeks[-1]
    prev_value = weeks[-2][1] if len(weeks) >= 2 else None
    return ref_period, ref_value, prev_value


def _read_collected(path: str) -> str | None:
    """수집 json 의 상단 'collected'(수집일자)만 가볍게 읽어 돌려준다(없으면 None)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    return payload.get("collected")


def build_trending(limit: int) -> dict:
    """최신 검색어 트렌드 수집본에서 인기 키워드 상위 N개를 JSON 뷰모델로 만든다.

    - 순위: 마지막 완성 주 ratio 내림차순(= 그 수집본 안에서의 상대 인기).
    - 전주 대비 변동: 기준주 ratio - 전주 ratio (절대) 와 % 를 함께 제공.
    - 종합판정(verdict)은 analyze_series 를 재사용해 덤으로 붙인다(로직 복붙 금지).
    파일이 없으면 예외를 던진다(라우트에서 503 으로 변환).
    """
    path = find_latest_for(TRENDING_SOURCE_PATTERN)
    if not path:
        raise FileNotFoundError("수집된 검색어 트렌드 데이터가 없습니다.")

    meta = SOURCES[TRENDING_SOURCE_META]
    collected = _read_collected(path)
    series = load_series(path)  # data/ 만 읽는다(외부 호출 없음)

    # 종합판정 매핑(재사용). analyze_series 는 z/추세 기반 판정을 이미 계산한다.
    verdicts = {name: r["verdict"] for name, r in analyze_series(series)}

    ranked: list[dict] = []
    for name, points in series.items():
        ref = _reference_weeks(points)
        if ref is None:
            continue  # 완성 주가 하나도 없으면 순위에서 제외(조용한 누락 아님: 값 부재)
        ref_period, ref_value, prev_value = ref
        if prev_value not in (None, 0):
            wow_change = round(ref_value - prev_value, 2)
            wow_change_pct = round((ref_value - prev_value) / prev_value * 100.0, 1)
        else:
            wow_change = None
            wow_change_pct = None
        ranked.append(
            {
                "keyword": name,
                "category": meta["label"],          # 소스 라벨(원본에 키워드별 분류 없음)
                "collected_date": collected,        # 수집일자
                "value": round(ref_value, 2),       # 기준주 검색 ratio
                "prev_value": round(prev_value, 2) if prev_value is not None else None,
                "wow_change": wow_change,            # 전주 대비 변동(절대)
                "wow_change_pct": wow_change_pct,    # 전주 대비 변동(%)
                "verdict": verdicts.get(name),
            }
        )

    # 인기순(기준주 ratio) 내림차순 → 상위 N 만 잘라 순위 부여.
    ranked.sort(key=lambda r: r["value"], reverse=True)
    top = ranked[:limit]
    for i, item in enumerate(top, start=1):
        item["rank"] = i

    # 기준일 = 어떤 품목이든 첫 번째로 확정되는 '마지막 완성 주'(대개 모든 품목 동일).
    reference_week = next(
        (
            r[0]
            for points in series.values()
            if (r := _reference_weeks(points)) is not None
        ),
        None,
    )

    return {
        "source": "네이버 데이터랩 (통합검색어 트렌드)",
        "source_url": NAVER_DATALAB_URL,
        "collected_date": collected,     # 수집일자
        "reference_week": reference_week,  # 기준일(순위·전주대비의 기준이 된 완성 주)
        "scaling": meta["scaling"],
        "value_unit": (
            f"{meta['unit']} — 네이버 데이터랩 상대지수. 같은 수집본 안에서만 품목 간 비교가 유효합니다."
        ),
        "note": (
            "값(value)은 네이버 데이터랩이 제공하는 상대 검색 ratio 입니다. "
            "순위와 전주 대비 변동은 아직 덜 집계된 진행 중 주를 제외한 "
            f"'마지막 완성 주'({reference_week}) 기준입니다."
        ),
        "limit": limit,
        "count": len(top),
        "items": top,
    }


def _apply_public_headers(resp, cache_seconds: int):
    """공개 읽기 전용 API용 CORS + 캐시 헤더를 응답에 붙인다.

    - CORS: 동대문 등 외부 사이트에서 브라우저로 직접 호출하므로 GET 을 전면 허용.
    - 캐시: 주간 수집이라 자주 바뀌지 않으므로 public 캐시로 부하를 줄인다.
    """
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    resp.headers["Cache-Control"] = f"public, max-age={cache_seconds}"
    return resp


@app.route("/api/trending", methods=["GET", "OPTIONS"])
def api_trending():
    """GET /api/trending?limit=10 — 최신 수집분 인기 키워드 상위 N개(읽기 전용 JSON).

    출처(네이버 데이터랩)와 기준일(수집일자·기준 완성 주)을 함께 담아 반환한다.
    data/ 의 json 만 읽으며 요청 시 외부 호출·크롤링을 하지 않는다.
    """
    if request.method == "OPTIONS":  # CORS preflight
        return _apply_public_headers(app.make_default_options_response(), TRENDING_CACHE_SECONDS)

    limit = _parse_limit(request.args.get("limit"))
    try:
        payload = build_trending(limit)
    except FileNotFoundError as e:
        resp = jsonify({"error": str(e)})
        resp.status_code = 503  # 아직 수집 전 — 서비스 준비 안 됨
        # 데이터 없음 응답은 캐시하지 않는다(수집되면 곧 바뀌므로).
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp
    except Exception as e:  # 조용한 실패 금지 — 오류를 JSON 으로 노출
        resp = jsonify({"error": f"데이터 처리 중 오류: {e}"})
        resp.status_code = 500
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["Access-Control-Allow-Origin"] = "*"
        return resp

    return _apply_public_headers(jsonify(payload), TRENDING_CACHE_SECONDS)


if __name__ == "__main__":
    # 로컬은 5000, 배포(Render 등)는 환경변수 PORT 를 사용. 외부 바인딩 0.0.0.0.
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
