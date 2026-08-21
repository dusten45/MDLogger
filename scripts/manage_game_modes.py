"""관리자(개발자) 전용 game_modes 기준정보 관리 CLI (service-role key, 옵션 a).

서버 ``game_modes``는 모드/시즌 기준정보의 원본이고, 로컬 ``play_modes``는 그
클라이언트 캐시다(B2). 이 스크립트는 개발자·운영자가 Supabase hosted project의
``game_modes``를 관리할 때 사용한다(spec §6.7, 1-G).

service-role key는 Supabase 서버 환경 변수 전용이며 클라이언트/사용자 빌드에
포함되지 않는다. 이 스크립트는 일반 사용자 빌드에 포함하지 않는다.

환경 변수:
  MDLOGGER_SUPABASE_URL       Supabase project URL (예: https://xxx.supabase.co)
  MDLOGGER_SERVICE_ROLE_KEY   service-role key (서버 전용, 절대 커밋 금지)

사용 예:
  python scripts/manage_game_modes.py list
  python scripts/manage_game_modes.py upsert rank-2026-09 rank "랭크" rank_2026_09 --season-label 26.09
  python scripts/manage_game_modes.py upsert dc-cup-2026-08 event_points "26.08 DC컵" dc_cup_2026_08 --inactive
  python scripts/manage_game_modes.py delete wcq-2026
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(f"환경 변수 {name}이(가) 설정되지 않았습니다.", file=sys.stderr)
        sys.exit(1)
    return value


def _request(method: str, url: str, payload: dict | None, key: str) -> dict | list:
    """service-role key로 Supabase REST/RPC 요청을 보낸다."""
    if not url.startswith("https://") and not url.startswith("http://"):
        print(f"지원하지 않는 URL 스킴입니다: {url}", file=sys.stderr)
        sys.exit(1)
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=body, method=method)
    for name, value in headers.items():
        request.add_header(name, value)
    try:
        with urllib.request.urlopen(request, timeout=15.0) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        raw = error.read()
        print(
            f"요청 실패 (HTTP {error.code}): {raw.decode('utf-8', 'replace')}",
            file=sys.stderr,
        )
        sys.exit(1)
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def _rpc(url: str, key: str, function: str, payload: dict) -> dict:
    result = _request("POST", f"{url}/rest/v1/rpc/{function}", payload, key)
    if not isinstance(result, dict):
        print("RPC 응답 형식이 올바르지 않습니다.", file=sys.stderr)
        sys.exit(1)
    return result


def cmd_list(url: str, key: str) -> None:
    rows = _request(
        "GET",
        f"{url}/rest/v1/game_modes?select=id,standing_kind,display_name,"
        "play_context_id,sort_order,is_active,season_label&order=sort_order.asc",
        None,
        key,
    )
    if not isinstance(rows, list):
        print("목록 응답 형식이 올바르지 않습니다.", file=sys.stderr)
        sys.exit(1)
    for row in rows:
        active = "활성" if row.get("is_active") else "비활성"
        print(
            f"{row.get('id')}\t{row.get('standing_kind')}\t{row.get('display_name')}"
            f"\t{row.get('play_context_id')}\t{row.get('sort_order')}\t{active}"
            f"\t{row.get('season_label') or ''}"
        )


def cmd_upsert(args: argparse.Namespace, url: str, key: str) -> None:
    result = _rpc(
        url,
        key,
        "manage_game_modes",
        {
            "operation": "upsert",
            "mode_id": args.id,
            "standing_kind": args.standing_kind,
            "display_name": args.display_name,
            "play_context_id": args.play_context_id,
            "sort_order": args.sort_order,
            "is_active": not args.inactive,
            "season_label": args.season_label,
        },
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_delete(args: argparse.Namespace, url: str, key: str) -> None:
    result = _rpc(
        url,
        key,
        "manage_game_modes",
        {"operation": "delete", "mode_id": args.id},
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="game_modes 기준정보 관리 (service-role)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="모드 목록 조회")

    p_upsert = sub.add_parser("upsert", help="모드 생성/수정")
    p_upsert.add_argument("id")
    p_upsert.add_argument("standing_kind", choices=["rank", "rating", "event_points"])
    p_upsert.add_argument("display_name")
    p_upsert.add_argument("play_context_id")
    p_upsert.add_argument("--sort-order", type=int, default=0)
    p_upsert.add_argument("--season-label")
    p_upsert.add_argument("--inactive", action="store_true", help="비활성으로 저장")

    p_delete = sub.add_parser("delete", help="모드 삭제")
    p_delete.add_argument("id")

    args = parser.parse_args()
    url = _env("MDLOGGER_SUPABASE_URL").rstrip("/")
    key = _env("MDLOGGER_SERVICE_ROLE_KEY")

    if args.command == "list":
        cmd_list(url, key)
    elif args.command == "upsert":
        cmd_upsert(args, url, key)
    elif args.command == "delete":
        cmd_delete(args, url, key)


if __name__ == "__main__":
    main()
