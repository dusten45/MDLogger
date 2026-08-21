#!/usr/bin/env python3
"""스트레스 부하 생성기: 로컬 프로필 DB에 N건의 pending 게임 기록을 생성한다.

배경: `docs/session-handoff.md` ②-2 — 장시간 offline/online 전환 + 대량(1,000건)
동기화 스트레스. `tests/test_sync_engine.py::test_large_1000_game_sync_completes`
매트릭스를 hosted Supabase에 대해 재현하기 위한 준비물이다.

동작:
- 게스트(기본) 또는 등록 계정의 **로컬 프로필 DB**에 주어진 수의 게임 기록을
  생성해 `sync_outbox`에 pending으로 등록한다. UI 입력과 동일한 경로
  (`GameService.insert_game` → `db.insert_game` → sync_outbox)를 따른다.
- **동기화는 하지 않는다.** 오프라인에서 기록이 쌓인 것과 동일한 상태를 재현한 뒤,
  앱을 온라인(`MDLOGGER_SUPABASE_URL`/`MDLOGGER_SUPABASE_ANON_KEY` 설정)으로
  띄우면 기존 자동 게스트 업로드/양방향 동기화가 pending을 서버로 보낸다.
- 실제 사용자 데이터를 건드리지 않도록, 반드시 스크래치 `MDLOGGER_DATA_DIR`로
  지정한 디렉터리에서 앱·스크립트를 함께 써야 한다.

사용(전체 절차는 `docs/operations/runbook.md` §2.1):

    export MDLOGGER_DATA_DIR=/tmp/mdlogger-stress          # 스크래치 격리
    uv run python scripts/add_stress_games.py --count 1000 # 게스트 1,000건
    # → 이후 앱을 온라인으로 띄워서 업로드 확인
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mdlogger import db  # noqa: E402
from mdlogger.game_service import GameService  # noqa: E402
from mdlogger.paths import DATA_DIR  # noqa: E402
from mdlogger.profiles import (  # noqa: E402
    ProfileContext,
    ProfileKind,
    ProfileManager,
)


def _sample_at(played_at: str, index: int) -> dict:
    """분석 허용 관측치가 비지 않도록 값이 섞이는 샘플 기록(Payload v2)."""
    result = "win" if index % 2 == 0 else "lose"
    points_before = (index * 100) % 20000
    points_after = points_before + (1000 if result == "win" else -500)
    return {
        "played_at": played_at,
        "result": result,
        "turn_order": "first" if index % 3 != 0 else "second",
        "my_deck": f"스트레스 덱 {index % 5}",
        "opp_deck": f"상대 덱 {index % 7}",
        "turns": 3 + (index % 6),
        "end_reason": ("regular", "surrender", "timeout")[index % 3],
        "standing_kind": "event_points",
        "play_context_id": "dc_cup_2026_08",
        "event_points_before": max(0, points_before),
        "event_points_after": max(0, points_after),
        "note": f"stress {index}",
    }


def _open_profile(
    manager: ProfileManager, kind: str, user_id: str | None, display_name: str
) -> tuple[ProfileContext, Path]:
    if kind == ProfileKind.GUEST.value:
        profile = manager.guest()
    else:
        if not user_id:
            raise SystemExit("오류: --kind registered는 --user-id(UUID)가 필요합니다.")
        profile = manager.registered(user_id, display_name)
    manager.prepare_database(profile)
    return profile, profile.database_path


def _counts(db_path: Path) -> tuple[int, int]:
    connection = db.connect(db_path)
    try:
        games = int(
            connection.execute(
                "SELECT COUNT(*) FROM games WHERE deleted_at IS NULL"
            ).fetchone()[0]
        )
        outbox = int(
            connection.execute(
                "SELECT COUNT(*) FROM sync_outbox WHERE "
                "game_sync_id NOT IN (SELECT sync_id FROM games "
                "WHERE sync_status = 'conflict')"
            ).fetchone()[0]
        )
        return games, outbox
    finally:
        connection.close()


def _write_sync_ids(db_path: Path, output: Path) -> None:
    connection = db.connect(db_path)
    try:
        rows = connection.execute(
            "SELECT sync_id FROM games WHERE deleted_at IS NULL ORDER BY id"
        ).fetchall()
    finally:
        connection.close()
    output.write_text("".join(f"{row['sync_id']}\n" for row in rows), encoding="utf-8")
    print(f"sync_id 목록({len(rows)}건) 저장: {output}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="로컬 프로필 DB에 스트레스 부하(pending 게임 기록) 생성"
    )
    default_data_dir = os.environ.get("MDLOGGER_DATA_DIR", "").strip() or str(DATA_DIR)
    parser.add_argument(
        "--data-dir",
        default=default_data_dir,
        help="프로필 DB의 데이터 디렉터리(기본: MDLOGGER_DATA_DIR 또는 앱 기본 경로)",
    )
    parser.add_argument(
        "--count", type=int, default=1000, help="생성할 기록 수(기본 1000)"
    )
    parser.add_argument(
        "--kind",
        choices=[ProfileKind.GUEST.value, ProfileKind.REGISTERED.value],
        default=ProfileKind.GUEST.value,
        help="프로필 종류(기본 guest)",
    )
    parser.add_argument(
        "--user-id",
        default=None,
        help="등록 계정 user ID(UUID). --kind registered일 때 필수",
    )
    parser.add_argument(
        "--display-name",
        default="테스트 계정",
        help="등록 계정 표시 이름(--kind registered 전용)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="생성한 sync_id를 저장할 파일 경로(서버 정확 비교용, 선택)",
    )
    args = parser.parse_args()

    if args.count < 0:
        print(
            "오류: --count는 0 이상이어야 합니다(0 = 생성 없이 개수만 표시).",
            file=sys.stderr,
        )
        return 1

    data_dir = Path(args.data_dir).expanduser().resolve()
    manager = ProfileManager(data_dir=data_dir)
    profile, db_path = _open_profile(
        manager, args.kind, args.user_id, args.display_name
    )

    before_games, before_outbox = _counts(db_path)
    print(
        f"[{profile.kind.value}] 경로: {db_path}\n"
        f"생성 전 — games={before_games}, pending outbox={before_outbox}"
    )
    if before_games:
        print(
            "참고: 이미 기록이 있어 부하가 누적됩니다. "
            "깨끗한 결과를 원하면 새 스크래치 디렉터리를 쓰세요.",
            file=sys.stderr,
        )

    base = datetime.now() - timedelta(minutes=args.count)
    games = GameService.open(db_path)
    try:
        for index in range(args.count):
            played_at = (base + timedelta(minutes=index)).isoformat(timespec="seconds")
            games.insert_game(_sample_at(played_at, index))
    finally:
        games.close()

    after_games, after_outbox = _counts(db_path)
    print(
        f"생성 완료 — games={after_games}(+{after_games - before_games}), "
        f"pending outbox={after_outbox}(+{after_outbox - before_outbox})"
    )

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        _write_sync_ids(db_path, args.output)

    print(
        "이후 절차: 앱을 온라인으로 띄워 자동 업로드/동기화를 확인하세요. "
        "(docs/operations/runbook.md §2.1)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
