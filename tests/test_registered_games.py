"""등록 계정 PostgREST games push adapter 테스트."""

from __future__ import annotations

import json

import pytest

from mdlogger.remote.client import HttpResponse, JsonHttpClient
from mdlogger.remote.config import RemoteConfig
from mdlogger.remote.games import (
    RegisteredGamesClient,
    RegisteredGamesError,
    RegisteredGamesErrorKind,
    build_registered_game,
)

CONFIG = RemoteConfig(base_url="https://example.supabase.co", anon_key="anon-key")
SYNC_ID = "33333333-3333-4333-8333-333333333333"
USER_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


class FakeTransport:
    def __init__(self, response: HttpResponse) -> None:
        self.response = response
        self.requests: list[dict] = []

    def request(self, method, url, headers, body, timeout):
        self.requests.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "body": json.loads(body.decode()),
                "timeout": timeout,
            }
        )
        return self.response


def private_payload() -> dict:
    return {
        "played_at": "2026-08-07T12:00:00",
        "result": "win",
        "turn_order": "first",
        "my_deck": "내 덱",
        "opp_deck": "상대 덱",
        "turns": 4,
        "end_reason": "regular",
        "score_after": 1500,
        "note": "개인 메모",
        "timezone_offset_minutes": 540,
        "local_updated_at": "전송 금지",
        "sync_status": "pending",
    }


def test_build_registered_game_keeps_private_note_but_excludes_local_metadata():
    row = build_registered_game(
        private_payload(),
        sync_id=SYNC_ID,
        user_id=USER_ID,
        operation="upsert",
        payload_version=1,
    )

    assert row["id"] == SYNC_ID
    assert row["user_id"] == USER_ID
    assert row["note"] == "개인 메모"
    assert row["timezone_offset_minutes"] == 540
    assert "local_updated_at" not in row
    assert "sync_status" not in row


def test_upsert_batch_uses_uuid_conflict_resolution_and_returns_versions():
    transport = FakeTransport(
        HttpResponse(
            status=201,
            body=json.dumps([{"id": SYNC_ID, "change_version": 7}]).encode(),
        )
    )
    client = RegisteredGamesClient(CONFIG, client=JsonHttpClient(transport))
    row = build_registered_game(
        private_payload(),
        sync_id=SYNC_ID,
        user_id=USER_ID,
        operation="upsert",
        payload_version=1,
    )

    result = client.upsert_batch([row], access_token="access-token")

    assert result.remote_versions == {SYNC_ID: 7}
    request = transport.requests[0]
    assert request["url"].endswith("/rest/v1/games?on_conflict=id")
    assert request["headers"]["Authorization"] == "Bearer access-token"
    assert "resolution=merge-duplicates" in request["headers"]["Prefer"]


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (401, RegisteredGamesErrorKind.AUTH_REQUIRED),
        (403, RegisteredGamesErrorKind.REJECTED),
        (422, RegisteredGamesErrorKind.REJECTED),
        (500, RegisteredGamesErrorKind.SERVER),
    ],
)
def test_upsert_batch_classifies_server_errors(status, kind):
    transport = FakeTransport(HttpResponse(status=status, body=b'{"code":"failure"}'))
    client = RegisteredGamesClient(CONFIG, client=JsonHttpClient(transport))

    with pytest.raises(RegisteredGamesError) as exc_info:
        client.upsert_batch(
            [
                build_registered_game(
                    private_payload(),
                    sync_id=SYNC_ID,
                    user_id=USER_ID,
                    operation="upsert",
                    payload_version=1,
                )
            ],
            access_token="token",
        )

    assert exc_info.value.kind is kind
