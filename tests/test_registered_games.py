"""등록 계정 versioned games/device adapter 테스트."""

from __future__ import annotations

import json

import pytest

from mdlogger.remote.client import HttpResponse, JsonHttpClient
from mdlogger.remote.config import RemoteConfig
from mdlogger.remote.games import (
    RegisteredGamesClient,
    RegisteredGamesError,
    RegisteredGamesErrorKind,
    build_game_change,
    build_registered_game,
)

CONFIG = RemoteConfig(base_url="https://example.supabase.co", anon_key="anon-key")
SYNC_ID = "33333333-3333-4333-8333-333333333333"
USER_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


class FakeTransport:
    def __init__(self, responses: list[HttpResponse]) -> None:
        self.responses = list(responses)
        self.requests: list[dict] = []

    def request(self, method, url, headers, body, timeout):
        self.requests.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "body": json.loads(body.decode()) if body else None,
                "timeout": timeout,
            }
        )
        return self.responses.pop(0)


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


def test_apply_changes_uses_versioned_rpc_and_returns_applied_and_conflict():
    transport = FakeTransport(
        [
            HttpResponse(
                status=200,
                body=json.dumps(
                    {
                        "results": [
                            {
                                "id": SYNC_ID,
                                "status": "applied",
                                "change_version": 7,
                            },
                            {
                                "id": "44444444-4444-4444-8444-444444444444",
                                "status": "conflict",
                                "current_change_version": 8,
                                "remote": {"id": "444", "change_version": 8},
                            },
                        ]
                    }
                ).encode(),
            )
        ]
    )
    client = RegisteredGamesClient(CONFIG, client=JsonHttpClient(transport))
    changes = [
        build_game_change(
            private_payload(),
            sync_id=SYNC_ID,
            operation="upsert",
            remote_version=None,
        ),
        build_game_change(
            private_payload(),
            sync_id="44444444-4444-4444-8444-444444444444",
            operation="upsert",
            remote_version=6,
        ),
    ]

    result = client.apply_changes(changes, access_token="access-token")

    assert result.remote_versions == {SYNC_ID: 7}
    assert result.results[1].status == "conflict"
    assert result.results[1].remote == {"id": "444", "change_version": 8}
    request = transport.requests[0]
    assert request["url"].endswith("/rest/v1/rpc/apply_game_changes")
    assert request["headers"]["Authorization"] == "Bearer access-token"
    assert request["body"]["sync_schema_version"] == 1
    assert request["body"]["payload_version"] == 1
    assert request["body"]["changes"][1]["expected_change_version"] == 6


def test_rate_limited_falls_back_to_retry_after_header():
    """B-4: 본문에 retry_after_seconds가 없으면 HTTP Retry-After 헤더를 쓴다."""
    transport = FakeTransport(
        [
            HttpResponse(
                status=429,
                body=json.dumps({}).encode(),
                headers={"Retry-After": "12"},
            )
        ]
    )
    client = RegisteredGamesClient(CONFIG, client=JsonHttpClient(transport))
    changes = [
        build_game_change(
            private_payload(),
            sync_id=SYNC_ID,
            operation="upsert",
            remote_version=None,
        )
    ]

    with pytest.raises(RegisteredGamesError) as exc_info:
        client.apply_changes(changes, access_token="access-token")

    assert exc_info.value.kind is RegisteredGamesErrorKind.RATE_LIMITED
    assert exc_info.value.retry_after_seconds == 12


def test_rate_limited_prefers_body_value_over_header():
    """B-4: 본문 retry_after_seconds가 정수면 헤더보다 우선한다."""
    transport = FakeTransport(
        [
            HttpResponse(
                status=429,
                body=json.dumps({"retry_after_seconds": 5}).encode(),
                headers={"Retry-After": "99"},
            )
        ]
    )
    client = RegisteredGamesClient(CONFIG, client=JsonHttpClient(transport))
    changes = [
        build_game_change(
            private_payload(),
            sync_id=SYNC_ID,
            operation="upsert",
            remote_version=None,
        )
    ]

    with pytest.raises(RegisteredGamesError) as exc_info:
        client.apply_changes(changes, access_token="access-token")

    assert exc_info.value.kind is RegisteredGamesErrorKind.RATE_LIMITED
    assert exc_info.value.retry_after_seconds == 5


def test_rate_limited_with_non_json_body_uses_header():
    """B-4: 게이트웨이가 평문 429 바디를 주면 AttributeError 없이
    Retry-After 헤더로 rate limit을 분류해야 한다."""
    transport = FakeTransport(
        [
            HttpResponse(
                status=429,
                body=b"Too Many Requests",
                headers={"Retry-After": "42"},
            )
        ]
    )
    client = RegisteredGamesClient(CONFIG, client=JsonHttpClient(transport))
    changes = [
        build_game_change(
            private_payload(),
            sync_id=SYNC_ID,
            operation="upsert",
            remote_version=None,
        )
    ]

    with pytest.raises(RegisteredGamesError) as exc_info:
        client.apply_changes(changes, access_token="access-token")

    assert exc_info.value.kind is RegisteredGamesErrorKind.RATE_LIMITED
    assert exc_info.value.retry_after_seconds == 42


def test_non_json_error_body_is_classified_without_crashing():
    """B-4: 429 이외 상태도 평문 바디에서 정상 분류되어야 한다."""
    transport = FakeTransport(
        [HttpResponse(status=500, body=b"<html>Bad Gateway</html>")]
    )
    client = RegisteredGamesClient(CONFIG, client=JsonHttpClient(transport))

    with pytest.raises(RegisteredGamesError) as exc_info:
        client.pull_changes(after_version=0, limit=10, access_token="access-token")

    assert exc_info.value.kind is RegisteredGamesErrorKind.SERVER


def test_pull_and_device_calls_use_cursor_and_version_contract():
    transport = FakeTransport(
        [
            HttpResponse(status=200, body=b'[{"id":"x","change_version":9}]'),
            HttpResponse(status=200, body=b"{}"),
            HttpResponse(status=200, body=b"{}"),
        ]
    )
    client = RegisteredGamesClient(CONFIG, client=JsonHttpClient(transport))

    pull = client.pull_changes(after_version=7, limit=100, access_token="token")
    client.register_device(
        installation_id="77777777-7777-4777-8777-777777777777",
        display_name="PC A",
        client_version="0.1.0",
        access_token="token",
    )
    client.acknowledge_device_version(
        installation_id="77777777-7777-4777-8777-777777777777",
        acknowledged_version=9,
        access_token="token",
    )

    assert pull.games[0]["change_version"] == 9
    assert "change_version=gt.7" in transport.requests[0]["url"]
    assert "order=change_version.asc" in transport.requests[0]["url"]
    assert transport.requests[1]["body"]["sync_schema_version"] == 1
    assert transport.requests[2]["body"]["acknowledged_version"] == 9


def test_applied_result_without_positive_change_version_is_rejected():
    transport = FakeTransport(
        [
            HttpResponse(
                status=200,
                body=json.dumps(
                    {"results": [{"id": SYNC_ID, "status": "applied"}]}
                ).encode(),
            )
        ]
    )
    client = RegisteredGamesClient(CONFIG, client=JsonHttpClient(transport))

    with pytest.raises(RegisteredGamesError) as exc_info:
        client.apply_changes(
            [
                build_game_change(
                    private_payload(),
                    sync_id=SYNC_ID,
                    operation="upsert",
                    remote_version=None,
                )
            ],
            access_token="token",
        )

    assert exc_info.value.kind is RegisteredGamesErrorKind.SERVER


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (401, RegisteredGamesErrorKind.AUTH_REQUIRED),
        (403, RegisteredGamesErrorKind.REJECTED),
        (422, RegisteredGamesErrorKind.REJECTED),
        (500, RegisteredGamesErrorKind.SERVER),
    ],
)
def test_apply_changes_classifies_server_errors(status, kind):
    transport = FakeTransport([HttpResponse(status=status, body=b'{"code":"failure"}')])
    client = RegisteredGamesClient(CONFIG, client=JsonHttpClient(transport))

    with pytest.raises(RegisteredGamesError) as exc_info:
        client.apply_changes(
            [
                build_game_change(
                    private_payload(),
                    sync_id=SYNC_ID,
                    operation="upsert",
                    remote_version=None,
                )
            ],
            access_token="token",
        )

    assert exc_info.value.kind is kind
