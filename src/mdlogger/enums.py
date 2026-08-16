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

# 경기 모드 종류 (DB 저장값, 표시 라벨). event_points의 표시명은
# play_modes.display_name에서 가져오므로 여기서는 None이다 (spec §2.1).
STANDING_KINDS = [("rank", "랭크"), ("rating", "레이팅"), ("event_points", None)]

# 티어 순서 (DB 저장값, 표시 라벨). 순서가 곧 화면 배치/정렬 순서다 (spec §2.2).
RANK_TIERS = [
    ("rookie", "루키"),
    ("bronze", "브론즈"),
    ("silver", "실버"),
    ("gold", "골드"),
    ("platinum", "플래티넘"),
    ("diamond", "다이아몬드"),
    ("master", "마스터"),
]
RANK_TIER_LABELS = dict(RANK_TIERS)
RANK_TIER_INDEX = {value: i for i, (value, _) in enumerate(RANK_TIERS)}

# 랭크 단계 범위 (모든 티어 동일, P7). 단계 감소 방향 5 → 1.
RANK_DIVISION_MIN = 1
RANK_DIVISION_MAX = 5


def label(mapping: dict[str, str], value: str | None, default: str = "—") -> str:
    """저장값을 한글 라벨로. 알 수 없으면 default."""
    if value is None:
        return default
    return mapping.get(value, str(value))
