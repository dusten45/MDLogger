"""enum 값 ↔ 한글 라벨 ↔ 색 매핑.

모든 enum 입력은 버튼/칩으로만 받으므로(오타 차단) 여기 정의된 순서가
곧 화면상의 버튼/칩 배치 순서가 된다.
"""
from __future__ import annotations

# 각 항목: (DB 저장값, 한글 라벨)
RESULTS = [("win", "승"), ("lose", "패")]
TURN_ORDERS = [("first", "선공"), ("second", "후공")]
END_REASONS = [
    ("regular", "정규 결착"),
    ("surrender", "서렌"),
    ("timeout", "시간 제한"),
    ("disconnect", "연결 두절"),
]

# 결과 색 (승=초록 / 패=빨강)
RESULT_COLORS = {"win": "#2e7d32", "lose": "#c62828"}

# 값 -> 라벨 빠른 조회
RESULT_LABELS = dict(RESULTS)
TURN_ORDER_LABELS = dict(TURN_ORDERS)
END_REASON_LABELS = dict(END_REASONS)


def label(mapping: dict[str, str], value: str | None, default: str = "—") -> str:
    """저장값을 한글 라벨로. 알 수 없으면 default."""
    if value is None:
        return default
    return mapping.get(value, str(value))
