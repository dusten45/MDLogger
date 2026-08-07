"""게스트 ingest 클라이언트 테스트: allowlist, idempotency, 오류 분류."""

from __future__ import annotations

import json

import pytest

from mdlogger.remote.client import HttpResponse, JsonHttpClient
from mdlogger.remote.config import RemoteConfig
from mdlogger.remote.errors import NetworkError
from mdlogger.remote.guest_ingest import (
    GUEST_INGEST_PAYLOAD_VERSION,
    GuestIngestClient,
    GuestIngestError,
    GuestIngestErrorKind,
    build_observation,
    build_withdrawal,
    current_timezone_offset_minutes,
)

CONFIG = RemoteConfig(base_url="https://example.supabase.co", anon_key="anon-key")
INSTALLATION_ID = "77777777-7777-4777-8777-777777777777"
SYNC_ID = "33333333-3333-4333-8333-333333333333"


def game_row(**overrides) -> dict:
    row = {
        "id": 1,
        "sync_id": SYNC_ID,
        "played_at": "2026-08-07T12:00:00",
        "result": "win",
        "turn_order": "second",
        "my_deck": "내 덱",
        "opp_deck": "상대 덱",
        "turns": 6,
        "end_reason": "regular",
        "score_after": 1500,
        "note": "개인 메모 — 전송 금지",
        "local_updated_at": "2026-08-07T12:00:05",
        "sync_status": "pending",
    }
    row.update(overrides)
    return row


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests: list[dict] = []

    def request(self, method, url, headers, body, timeout):
        self.requests.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "body": json.loads(body.decode()) if body else None,
            }
        )
        outcome = self.responses.pop(0)
        if isinstance(outcome, NetworkError):
            raise outcome
        return outcome


def ok_response(accepted=1, skipped=0, rejected=0, replayed=False) -> HttpResponse:
    return HttpResponse(
        status=200,
        body=json.dumps(
            {
                "batch_id": "99999999-9999-4999-8999-999999999999",
                "accepted": accepted,
                "skipped": skipped,
                "rejected": rejected,
                "replayed": replayed,
            }
        ).encode(),
    )


def make_client(*outcomes) -> tuple[GuestIngestClient, FakeTransport]:
    transport = FakeTransport(list(outcomes))
    client = GuestIngestClient(
        CONFIG,
        INSTALLATION_ID,
        client=JsonHttpClient(transport),
        client_version="0.1.0",
    )
    return client, transport


def test_build_observation_excludes_note_and_private_fields():
    observation = build_observation(game_row())

    assert observation["sync_id"] == SYNC_ID
    assert observation["played_at_local"] == "2026-08-07T12:00:00"
    assert observation["result"] == "win"
    assert observation["turns"] == 6
    for forbidden in ("note", "id", "score_after", "local_updated_at", "sync_status"):
        assert forbidden not in observation


def test_build_observation_omits_unknown_values_instead_of_guessing():
    observation = build_observation(game_row(my_deck="", turns=None))

    assert "my_deck" not in observation
    assert "turns" not in observation


def test_build_observation_requires_sync_id():
    with pytest.raises(ValueError):
        build_observation(game_row(sync_id=None))


def test_build_observation_records_timezone_offset_when_given():
    offset = current_timezone_offset_minutes()
    observation = build_observation(game_row(), timezone_offset_minutes=offset)
    assert observation["timezone_offset_minutes"] == offset


def test_build_withdrawal():
    assert build_withdrawal(SYNC_ID) == {"op": "withdraw", "sync_id": SYNC_ID}


def test_upload_batch_sends_restricted_payload_without_login():
    client, transport = make_client(ok_response())

    result = client.upload_batch([build_observation(game_row())])

    assert result.accepted == 1
    request = transport.requests[0]
    assert request["url"].endswith("/functions/v1/guest-ingest")
    # 게스트는 anon key만 사용한다. 사용자 JWT나 공유 비밀이 없다.
    assert request["headers"]["apikey"] == "anon-key"
    assert request["headers"]["Authorization"] == "Bearer anon-key"
    body = request["body"]
    assert body["installation_id"] == INSTALLATION_ID
    assert body["payload_version"] == GUEST_INGEST_PAYLOAD_VERSION
    assert body["client_version"] == "0.1.0"
    assert "challenge_token" not in body
    assert "note" not in json.dumps(body, ensure_ascii=False)


def test_upload_batch_reuses_batch_id_for_safe_retry():
    client, transport = make_client(
        NetworkError("연결 끊김"), ok_response(accepted=0, skipped=1, replayed=True)
    )
    batch_id = "99999999-9999-4999-8999-999999999999"
    observation = build_observation(game_row())

    with pytest.raises(GuestIngestError) as exc_info:
        client.upload_batch([observation], batch_id=batch_id)
    assert exc_info.value.kind is GuestIngestErrorKind.NETWORK

    result = client.upload_batch([observation], batch_id=batch_id)

    assert result.replayed
    first, second = (request["body"]["batch_id"] for request in transport.requests)
    assert first == second == batch_id


def test_upload_batch_challenge_extension_boundary():
    client, transport = make_client(
        HttpResponse(status=428, body=b'{"code":"challenge_required"}'),
        ok_response(),
    )
    observation = build_observation(game_row())

    with pytest.raises(GuestIngestError) as exc_info:
        client.upload_batch([observation])
    assert exc_info.value.kind is GuestIngestErrorKind.CHALLENGE_REQUIRED

    client.upload_batch([observation], challenge_token="one-time-token")
    assert transport.requests[1]["body"]["challenge_token"] == "one-time-token"


def test_upload_batch_rate_limit_classification():
    client, _ = make_client(
        HttpResponse(
            status=429, body=b'{"code":"rate_limited","retry_after_seconds":60}'
        )
    )

    with pytest.raises(GuestIngestError) as exc_info:
        client.upload_batch([build_observation(game_row())])

    assert exc_info.value.kind is GuestIngestErrorKind.RATE_LIMITED
    assert exc_info.value.retry_after_seconds == 60


@pytest.mark.parametrize(
    ("status", "expected_kind"),
    [
        (422, GuestIngestErrorKind.REJECTED),
        (401, GuestIngestErrorKind.REJECTED),
        (500, GuestIngestErrorKind.SERVER),
    ],
)
def test_upload_batch_error_status_classification(status, expected_kind):
    client, _ = make_client(HttpResponse(status=status, body=b'{"code":"x"}'))

    with pytest.raises(GuestIngestError) as exc_info:
        client.upload_batch([build_observation(game_row())])

    assert exc_info.value.kind is expected_kind


def test_upload_batch_rejects_empty_batch_locally():
    client, transport = make_client()
    with pytest.raises(ValueError):
        client.upload_batch([])
    assert transport.requests == []
