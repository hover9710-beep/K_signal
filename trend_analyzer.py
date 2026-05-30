# -*- coding: utf-8 -*-
"""
K-제품 검색 트렌드 분석기 — z-score + 기울기(추세) 기반 급등/급락 판정

목적:
    data/ 폴더의 가장 최근 datalab_*.json 을 읽어, 품목별 주간 검색 ratio
    시계열에서 '마지막 완성 주'의 급등/급락 여부를 두 신호로 판정한다.
      (1) z-score  : 마지막 완성 주가 baseline 대비 얼마나 튀었는가(단발 충격).
      (2) 추세%    : 최근 WINDOW주의 선형회귀 기울기(주당 % 변화, 완만한 추세).

배경:
    마지막 주 z-score 만 보면, 두바이초콜릿처럼 여러 주에 걸쳐 천천히 진행된
    큰 변화(예: -80%)를 매주 변화폭이 작다는 이유로 "정상"으로 놓친다.
    이를 잡기 위해 단조 추세를 보는 기울기 신호를 보조로 추가한다.

입력 포맷 (datalab_collector.py 가 저장한 형태):
    {
      "collected": "YYYY-MM-DD",
      "window": {...},
      "series": { "품목명": [ {"period": "YYYY-MM-DD", "ratio": 12.3}, ... ] }
    }

판정 로직 요약:
    - 평가 대상 = '마지막 완성 주' (진행 중 주 제외 시).
    - baseline = 평가 주 이전의 완성 주들 → z = (평가주값 - 평균) / 표준편차.
    - 추세% = 최근 WINDOW주 최소제곱 기울기 / 해당 구간 평균 × 100.
    - 종합판정 = z 와 추세% 중 '더 강한 신호'를 채택.
    - 완성 주가 WINDOW+1 미만이거나 baseline std≈0 이면 "데이터부족".

실행:
    py trend_analyzer.py
    (python 금지 — py 런처 사용)
"""
from __future__ import annotations

import datetime
import glob
import html
import json
import os
import sys
import urllib.parse
from statistics import mean, pstdev

DATA_DIR = "data"

# ──────────────────────────────────────────────────────────────────────
# 분석 대상 소스 선택.
#   "search"   → data/datalab_*.json            (통합검색어 트렌드: 품목 검색 ratio)
#   "shopping" → data/shopping_categories_*.json (쇼핑인사이트: 분야별 클릭 ratio)
#   두 파일 모두 {collected, window, series:{이름:[(period,ratio)...]}} 구조가
#   동일하므로 series 만 읽으면 동일한 판정 로직을 그대로 재사용할 수 있다.
# ──────────────────────────────────────────────────────────────────────
SOURCE = "shopping"

# 소스별 파일 glob 패턴 + 수집 안내 문구
SOURCE_PATTERNS = {
    "search": ("datalab_*.json", "py datalab_collector.py"),
    "shopping": ("shopping_categories_*.json", "py shopping_collector.py"),
}

# ──────────────────────────────────────────────────────────────────────
# 진행 중(미완성)인 최근 주를 끝에서 몇 개나 제외할지.
#   기본 1: 각 품목 시계열의 '마지막 데이터 포인트' 1개를 버리고 계산한다.
#   [이유] 데이터랩의 가장 최근 주는 아직 한 주가 끝나지 않은 '진행 중 주'라
#          검색량이 덜 쌓여 있다. 이를 포함하면 실제로는 정상인데도 값이 작게
#          잡혀 '가짜 급락' 신호가 발생한다. 따라서 기본적으로 제외한다.
#   0 으로 두면 아무 주도 제외하지 않는다(모든 주를 완성 주로 취급).
# ──────────────────────────────────────────────────────────────────────
EXCLUDE_RECENT_WEEKS = 2

# ── 튜닝용 상수 ────────────────────────────────────────────────────────
#   WINDOW    : 추세(기울기) 계산에 쓰는 최근 완성 주 개수.
#   Z_HI/Z_MID: z-score 임계치(강/중).
#   TREND_HI/TREND_MID: 추세 임계치(강/중). 단위는 '주당 % 변화'.
WINDOW = 6
Z_HI = 2.0
Z_MID = 1.0
TREND_HI = 7.0
TREND_MID = 3.0

STD_EPSILON = 1e-9  # baseline std 가 이보다 작으면 사실상 0 → "데이터부족"


def find_latest_json() -> str:
    """SOURCE 에 맞는 data/ 내 파일들 중 파일명 날짜 기준 최신 경로를 돌려준다."""
    if SOURCE not in SOURCE_PATTERNS:
        sys.exit(
            f"[중단] 알 수 없는 SOURCE='{SOURCE}'. "
            f"가능한 값: {', '.join(SOURCE_PATTERNS)}"
        )
    glob_name, collect_hint = SOURCE_PATTERNS[SOURCE]
    pattern = os.path.join(DATA_DIR, glob_name)
    candidates = glob.glob(pattern)
    if not candidates:
        sys.exit(
            f"[중단] '{pattern}' 패턴에 맞는 파일이 없습니다.\n"
            f"  → 먼저 {collect_hint} 로 데이터를 수집하세요."
        )
    # 파일명에 YYYY-MM-DD 가 들어 있어 사전식 정렬이 곧 날짜 정렬과 같다.
    candidates.sort()
    return candidates[-1]


def find_latest_for(source: str) -> str | None:
    """주어진 소스 키('search'/'shopping')의 최신 파일 경로를 돌려준다(없으면 None).

    웹앱 등 import 사용처를 위해 sys.exit 대신 None 을 반환한다.
    (전역 SOURCE 기반의 find_latest_json 동작은 CLI 용으로 그대로 둔다.)
    """
    if source not in SOURCE_PATTERNS:
        return None
    glob_name, _ = SOURCE_PATTERNS[source]
    candidates = sorted(glob.glob(os.path.join(DATA_DIR, glob_name)))
    return candidates[-1] if candidates else None


def load_series(path: str) -> dict[str, list[tuple[str, float]]]:
    """JSON 을 읽어 {품목명: [(period, ratio), ...]} (period 오름차순) 으로 정리."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"[중단] '{path}' 읽기/파싱 실패: {e}")

    raw_series = payload.get("series")
    if not isinstance(raw_series, dict) or not raw_series:
        sys.exit(f"[중단] '{path}' 에 'series' 데이터가 없습니다.")

    series: dict[str, list[tuple[str, float]]] = {}
    for name, points in raw_series.items():
        cleaned = [(p["period"], float(p["ratio"])) for p in points]
        cleaned.sort(key=lambda x: x[0])
        series[name] = cleaned
    return series


def linregress_slope(values: list[float]) -> float:
    # Theil-Sen 기울기: 모든 두 점 쌍 기울기의 중앙값.
    # OLS와 달리 가장자리 단발 스파이크(마라탕 04-13=100)에 강건하다.
    import statistics
    n = len(values)
    if n < 2:
        return 0.0
    slopes = [(values[j] - values[i]) / (j - i)
              for i in range(n) for j in range(i + 1, n)]
    return statistics.median(slopes)


def _signal_level(z: float, trend: float) -> int:
    """z 와 추세% 각각을 -2..+2 단계로 환산한 뒤 '더 강한 신호'를 채택한다.

    단계: +2 급등 / +1 상승 / 0 정상 / -1 하락 / -2 급락.
    z 와 추세% 가 가리키는 단계 중 절댓값이 큰 쪽(= 더 강한 신호)을 택하고,
    절댓값이 같으면 더 큰(상승 방향) 값을 택한다.
    """

    def level_of(value: float, hi: float, mid: float) -> int:
        if value != value:  # NaN
            return 0
        if value >= hi:
            return 2
        if value >= mid:
            return 1
        if value <= -hi:
            return -2
        if value <= -mid:
            return -1
        return 0

    z_level = level_of(z, Z_HI, Z_MID)
    t_level = level_of(trend, TREND_HI, TREND_MID)
    # 더 강한(절댓값 큰) 신호 채택, 동률이면 상승 방향 우선(max).
    if abs(z_level) > abs(t_level):
        return z_level
    if abs(t_level) > abs(z_level):
        return t_level
    return max(z_level, t_level)


def classify(z: float, trend: float) -> str:
    """z-score 와 추세% 를 종합해 판정 라벨로 변환한다."""
    return {2: "급등경보", 1: "상승관찰", 0: "정상", -1: "하락관찰", -2: "급락"}[
        _signal_level(z, trend)
    ]


def analyze_one(points: list[tuple[str, float]]) -> dict:
    """한 품목 시계열을 분석해 결과 dict 를 돌려준다."""
    # 진행 중 주 제외: 끝에서 EXCLUDE_RECENT_WEEKS 개의 데이터 포인트를 버린다.
    # (0 이면 제외하지 않는다. points[:-0] 은 빈 리스트가 되므로 분기 처리.)
    weeks = points[:-EXCLUDE_RECENT_WEEKS] if EXCLUDE_RECENT_WEEKS > 0 else points

    def insufficient(reason_value: tuple[str, float] | None) -> dict:
        """노이즈 방지를 위해 판정을 보류하는 결과 dict."""
        return {
            "period": reason_value[0] if reason_value else "-",
            "value": reason_value[1] if reason_value else float("nan"),
            "baseline_mean": float("nan"),
            "z": float("nan"),
            "trend": float("nan"),
            "verdict": "데이터부족",
        }

    # 완성 주가 WINDOW+1 미만이면 추세/판정에 쓸 표본이 부족 → 데이터부족.
    if len(weeks) < WINDOW + 1:
        return insufficient(weeks[-1] if weeks else None)

    eval_period, eval_value = weeks[-1]
    baseline = [v for _, v in weeks[:-1]]

    b_mean = mean(baseline)
    b_std = pstdev(baseline)  # 모표준편차(baseline 전체를 모집단으로 봄)

    # baseline 변동성이 거의 없으면 z 가 폭발/무의미 → 데이터부족 처리.
    if b_std < STD_EPSILON:
        return insufficient((eval_period, eval_value))

    z = (eval_value - b_mean) / b_std

    # 추세%: 최근 WINDOW주의 최소제곱 기울기를 구간 평균으로 정규화 → 주당 % 변화.
    window_values = [v for _, v in weeks[-WINDOW:]]
    slope = linregress_slope(window_values)
    w_mean = mean(window_values)
    trend = (slope / w_mean * 100.0) if (w_mean and slope == slope) else float("nan")

    return {
        "period": eval_period,
        "value": eval_value,
        "baseline_mean": b_mean,
        "z": z,
        "trend": trend,
        "verdict": classify(z, trend),
    }


def sort_rows(rows: list[tuple[str, dict]]) -> list[tuple[str, dict]]:
    """종합 점수(z + 추세%) 내림차순 정렬. 데이터부족(어느 한쪽이라도 NaN)은 맨 아래."""

    def sort_key(item: tuple[str, dict]) -> float:
        z, trend = item[1]["z"], item[1]["trend"]
        if z != z or trend != trend:  # NaN → 맨 아래
            return float("-inf")
        return z + trend

    return sorted(rows, key=sort_key, reverse=True)


def analyze_series(
    series: dict[str, list[tuple[str, float]]]
) -> list[tuple[str, dict]]:
    """{이름:[(period,ratio)...]} 를 분석해 정렬된 [(이름, 결과dict)] 로 돌려준다.

    웹앱/리포트가 터미널과 '동일한 분석·정렬 로직'을 재사용하기 위한 진입점.
    """
    rows = [(name, analyze_one(points)) for name, points in series.items()]
    return sort_rows(rows)


def _fmt(value: float, width: int, decimals: int) -> str:
    """NaN 은 '-' 로, 그 외에는 소수 자리수에 맞춰 출력한다. 폭(width)은 항상 맞춘다."""
    if value != value:  # NaN 체크
        return format("-", f">{width}")
    return format(value, f">{width}.{decimals}f")


def print_table(rows: list[tuple[str, dict]]) -> None:
    """분석 결과를 종합 점수(상승 위 / 하락 아래) 순으로 표 출력한다."""
    trend_col = f"추세%(최근{WINDOW}주)"
    header = (
        f"{'품목':<14}{'평가주':<14}{'값':>8}{'baseline평균':>14}"
        f"{'z-score':>10}{trend_col:>16}  종합판정"
    )
    print(header)
    print("-" * len(header))

    # 정렬 점수 = z + 추세% (sort_rows 공통 로직). 상승이 위, 하락이 아래.
    for name, r in sort_rows(rows):
        print(
            f"{name:<14}{r['period']:<14}"
            f"{_fmt(r['value'], 8, 2)}"
            f"{_fmt(r['baseline_mean'], 14, 2)}"
            f"{_fmt(r['z'], 10, 2)}"
            f"{_fmt(r['trend'], 16, 2)}"
            f"  {r['verdict']}"
        )

    print(
        "\n※ ratio 는 같은 요청(json) 안에서 공유되는 상대값입니다. "
        "따라서 품목 간 절대 비교는 동일한 json 파일 안에서만 유효합니다."
    )
    print(
        "※ shopping 분야 ratio 는 '분야별로 각자 최대=100'으로 스케일됩니다. "
        "따라서 분야 간 절대 비교는 무효이고, 같은 분야의 시간 추세만 유효합니다."
    )


# 종합판정 → 행 색상 클래스 매핑.
#   상승(급등경보/상승관찰)=상승색, 하락(하락관찰/급락)=하락색, 정상=회색.
#   데이터부족은 흐리게(faded) 처리한다.
VERDICT_CSS_CLASS = {
    "급등경보": "rise",
    "상승관찰": "rise",
    "정상": "flat",
    "하락관찰": "fall",
    "급락": "fall",
    "데이터부족": "faint",
}


def _fmt_html(value: float, decimals: int) -> str:
    """HTML 셀용 숫자 포맷. NaN 은 '-' 로 표시한다."""
    if value != value:  # NaN 체크
        return "-"
    return format(value, f".{decimals}f")


def _coupang_cell(name: str, verdict: str, value: float) -> str:
    """'쿠팡확인' 셀 HTML 을 만든다.

    데이터부족이거나 값이 비어 있는(면세점처럼 빈) 분야는 검색해도 의미가
    없으므로 링크를 만들지 않고 '-' 로 둔다. 그 외에는 품목명을 그대로
    쿠팡 검색어로 인코딩해 새 탭으로 열리는 버튼 링크를 만든다.
    """
    is_empty = (verdict == "데이터부족") or (value != value)  # NaN 이면 빈 분야
    if is_empty:
        return '<span class="nolink">-</span>'
    query = urllib.parse.quote(name)
    url = f"https://www.coupang.com/np/search?q={query}"
    return (
        f'<a class="coupang" href="{url}" target="_blank" '
        f'rel="noopener noreferrer">쿠팡에서 보기 →</a>'
    )


def write_html_report(rows: list[tuple[str, dict]], src_path: str) -> str:
    """분석 결과를 클릭 가능한 HTML 표로 저장하고 저장 경로를 돌려준다.

    터미널 표와 동일한 정렬·데이터·판정을 그대로 사용하며, 출력 형식만 HTML 이다.
    """
    # 정렬은 sort_rows 공통 로직 사용(print_table 과 동일). 데이터부족은 맨 아래.
    sorted_rows = sort_rows(rows)

    # 평가 기준주: 데이터부족이 아닌 첫 행의 평가주(대부분 품목이 동일 주).
    eval_week = next(
        (r["period"] for _, r in sorted_rows if r["verdict"] != "데이터부족"),
        "-",
    )
    exclude_note = (
        "진행 중 주 제외 없음"
        if EXCLUDE_RECENT_WEEKS == 0
        else f"진행 중(미완성) 마지막 {EXCLUDE_RECENT_WEEKS}개 주 제외"
    )
    trend_col = f"추세%(최근{WINDOW}주)"

    # 본문 행 HTML 생성.
    body_rows = []
    for name, r in sorted_rows:
        css = VERDICT_CSS_CLASS.get(r["verdict"], "flat")
        body_rows.append(
            "      <tr class=\"{css}\">"
            "<td class=\"name\">{name}</td>"
            "<td>{period}</td>"
            "<td class=\"num\">{value}</td>"
            "<td class=\"num\">{z}</td>"
            "<td class=\"num\">{trend}</td>"
            "<td class=\"verdict\">{verdict}</td>"
            "<td class=\"coupang-cell\">{coupang}</td>"
            "</tr>".format(
                css=css,
                name=html.escape(name),
                period=html.escape(str(r["period"])),
                value=_fmt_html(r["value"], 2),
                z=_fmt_html(r["z"], 2),
                trend=_fmt_html(r["trend"], 2),
                verdict=html.escape(r["verdict"]),
                coupang=_coupang_cell(name, r["verdict"], r["value"]),
            )
        )

    # 상단 안내 한 줄: 분석 대상 / 평가 기준주 / 진행 주 제외 안내.
    summary_line = (
        f"분석 대상(SOURCE): <b>{html.escape(SOURCE)}</b> · "
        f"평가 기준주: <b>{html.escape(str(eval_week))}</b> · "
        f"{html.escape(exclude_note)}"
    )

    today = datetime.date.today().isoformat()
    generated = f"생성: {today} · 원본: {html.escape(os.path.basename(src_path))}"

    page = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>트렌드 분석 리포트 ({source})</title>
<style>
  body {{ font-family: "맑은 고딕", "Malgun Gothic", sans-serif;
          margin: 24px; color: #222; background: #fafafa; }}
  h1 {{ font-size: 20px; margin: 0 0 8px; }}
  .summary {{ font-size: 14px; color: #333; margin: 0 0 4px; }}
  .generated {{ font-size: 12px; color: #888; margin: 0 0 16px; }}
  table {{ border-collapse: collapse; width: 100%; background: #fff;
           box-shadow: 0 1px 3px rgba(0,0,0,.1); }}
  th, td {{ padding: 8px 12px; border-bottom: 1px solid #eee;
            text-align: left; font-size: 14px; }}
  th {{ background: #f0f0f0; position: sticky; top: 0; }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  td.name {{ font-weight: 600; }}
  td.verdict {{ font-weight: 600; }}
  /* 종합판정별 행 색상: 상승=붉은 계열, 하락=푸른 계열, 정상=회색 */
  tr.rise {{ background: #fdecec; }}
  tr.rise td.verdict {{ color: #c0392b; }}
  tr.fall {{ background: #eaf2fb; }}
  tr.fall td.verdict {{ color: #2255aa; }}
  tr.flat {{ background: #f6f6f6; }}
  tr.flat td.verdict {{ color: #555; }}
  tr.faint {{ background: #fff; opacity: .45; }}  /* 데이터부족: 흐리게 */
  a.coupang {{ display: inline-block; padding: 4px 10px; border-radius: 4px;
               background: #346aff; color: #fff; text-decoration: none;
               font-size: 13px; white-space: nowrap; }}
  a.coupang:hover {{ background: #1f4fd6; }}
  .nolink {{ color: #bbb; }}
  .note {{ font-size: 12px; color: #888; margin-top: 16px; line-height: 1.6; }}
</style>
</head>
<body>
  <h1>K-제품 검색 트렌드 분석 리포트</h1>
  <p class="summary">{summary}</p>
  <p class="generated">{generated}</p>
  <table>
    <thead>
      <tr>
        <th>품목</th><th>평가주</th><th>값</th><th>z-score</th>
        <th>{trend_col}</th><th>종합판정</th><th>쿠팡확인</th>
      </tr>
    </thead>
    <tbody>
{body}
    </tbody>
  </table>
  <p class="note">
    ※ ratio 는 같은 요청(json) 안에서 공유되는 상대값입니다. 품목 간 절대 비교는
    동일 json 파일 안에서만 유효합니다.<br>
    ※ shopping 분야 ratio 는 '분야별로 각자 최대=100'으로 스케일됩니다. 분야 간
    절대 비교는 무효이고, 같은 분야의 시간 추세만 유효합니다.
  </p>
</body>
</html>
""".format(
        source=html.escape(SOURCE),
        summary=summary_line,
        generated=generated,
        trend_col=html.escape(trend_col),
        body="\n".join(body_rows),
    )

    out_path = os.path.join(DATA_DIR, f"report_{SOURCE}_{today}.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(page)
    return out_path


def main() -> None:
    path = find_latest_json()
    print(f"분석 대상: SOURCE='{SOURCE}'  파일={path}")
    print(
        f"(끝에서 제외한 진행 중 주 수 EXCLUDE_RECENT_WEEKS={EXCLUDE_RECENT_WEEKS} — "
        f"{'제외 없음' if EXCLUDE_RECENT_WEEKS == 0 else f'마지막 {EXCLUDE_RECENT_WEEKS}개 주 제외'})\n"
    )

    series = load_series(path)
    rows = [(name, analyze_one(points)) for name, points in series.items()]
    print_table(rows)

    # 터미널 표는 그대로 두고, 동일한 결과를 클릭 가능한 HTML 로도 저장한다.
    out_path = write_html_report(rows, path)
    print(f"\n저장 완료 → {out_path}")


if __name__ == "__main__":
    main()
