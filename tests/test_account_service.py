"""Supabase 계정 서비스 adapter와 오류 분류 테스트 (mock transport)."""

from __future__ import annotations

import json

import pytest

from mdlogger.auth.models import AuthError, AuthErrorKind
from mdlogger.auth.supabase_auth import SupabaseAccountService
from mdlogger.remote.client import HttpResponse, JsonHttpClient
from mdlogger.remote.config import RemoteConfig
from mdlogger.remote.errors import NetworkError

CONFIG = RemoteConfig(base_url="https://example.supabase.co", anon_key="anon-key")
USER_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


class FakeTransport:
    """준비된 응답을 돌려주고 요청을 기록하는 mock transport."""

    def __init__(self, responses: list[HttpResponse | NetworkError]):
        self.responses = list(responses)
        self.requests: list[dict] = []

    def request(self, method, url, headers, body, timeout):
        self.requests.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "body": json.loads(body.decode()) if body else None,
                "timeout": timeout,
            }
        )
        outcome = self.responses.pop(0)
        if isinstance(outcome, NetworkError):
            raise outcome
        return outcome


def json_response(status: int, payload: dict) -> HttpResponse:
    return HttpResponse(status=status, body=json.dumps(payload).encode())


def make_service(*outcomes) -> tuple[SupabaseAccountService, FakeTransport]:
    transport = FakeTransport(list(outcomes))
    return SupabaseAccountService(CONFIG, JsonHttpClient(transport)), transport


def session_payload(email_confirmed: bool = True) -> dict:
    return {
        "access_token": "access-1",
        "refresh_token": "refresh-1",
        "expires_in": 3600,
        "user": {
            "id": USER_ID,
            "email": "a@test.local",
            "email_confirmed_at": "2026-08-07T10:00:00Z" if email_confirmed else None,
        },
    }


def test_sign_in_returns_session_and_sends_anon_key_only():
    service, transport = make_service(json_response(200, session_payload()))

    session = service.sign_in("a@test.local", "pw")

    assert session.account.user_id == USER_ID
    assert session.tokens.access_token == "access-1"
    assert session.tokens.refresh_token == "refresh-1"
    request = transport.requests[0]
    assert request["url"].endswith("/auth/v1/token?grant_type=password")
    assert request["headers"]["apikey"] == "anon-key"
    assert "Authorization" not in request["headers"]
    assert request["timeout"] > 0


def test_tokens_never_leak_via_repr():
    service, _ = make_service(json_response(200, session_payload()))
    session = service.sign_in("a@test.local", "pw")

    for rendered in (repr(session), repr(session.tokens), str(session)):
        assert "access-1" not in rendered
        assert "refresh-1" not in rendered


def test_sign_up_without_session_requires_email_verification():
    service, _ = make_service(
        json_response(
            200,
            {"id": USER_ID, "email": "a@test.local", "email_confirmed_at": None},
        )
    )

    result = service.sign_up("a@test.local", "pw")

    assert result.session is None
    assert result.needs_email_verification


def test_sign_up_with_immediate_session():
    service, _ = make_service(json_response(200, session_payload()))

    result = service.sign_up("a@test.local", "pw")

    assert result.session is not None
    assert not result.needs_email_verification


def test_refresh_uses_refresh_grant():
    service, transport = make_service(json_response(200, session_payload()))

    service.refresh_session("refresh-0")

    request = transport.requests[0]
    assert request["url"].endswith("/auth/v1/token?grant_type=refresh_token")
    assert request["body"] == {"refresh_token": "refresh-0"}


def test_sign_out_sends_bearer_access_token():
    service, transport = make_service(HttpResponse(status=204))

    service.sign_out("access-1")

    request = transport.requests[0]
    assert request["url"].endswith("/auth/v1/logout")
    assert request["headers"]["Authorization"] == "Bearer access-1"


def test_resend_verification_email():
    service, transport = make_service(json_response(200, {"message_id": "m1"}))

    service.resend_verification_email("a@test.local")

    request = transport.requests[0]
    assert request["url"].endswith("/auth/v1/resend")
    assert request["body"] == {"type": "signup", "email": "a@test.local"}


def test_request_password_reset_uses_recover_endpoint():
    service, transport = make_service(json_response(200, {}))

    service.request_password_reset("a@test.local")

    request = transport.requests[0]
    assert request["url"].endswith("/auth/v1/recover")
    assert request["body"] == {"email": "a@test.local"}


def export_payload() -> dict:
    return {
        "user_id": USER_ID,
        "exported_at": "2026-08-09T00:00:00Z",
        "profile": {"display_name": "Alice"},
        "games": [{"id": "g1", "result": "win"}],
        "devices": [
            {
                "id": "d1",
                "installation_id": "11111111-1111-4111-8111-111111111111",
                "display_name": "PC A",
                "client_version": "0.2.0",
                "created_at": "2026-08-07T00:00:00Z",
                "last_seen_at": "2026-08-09T00:00:00Z",
                "last_acknowledged_version": 7,
            }
        ],
    }


def test_export_account_data_calls_rpc_and_parses_export():
    service, transport = make_service(json_response(200, export_payload()))

    data = service.export_account_data("access-1")

    request = transport.requests[0]
    assert request["url"].endswith("/rest/v1/rpc/export_account_data")
    assert request["headers"]["Authorization"] == "Bearer access-1"
    assert list(data.games) == [{"id": "g1", "result": "win"}]
    assert data.profile == {"display_name": "Alice"}
    assert len(data.devices) == 1
    assert data.devices[0].display_name == "PC A"
    assert data.devices[0].last_acknowledged_version == 7


def test_list_devices_parses_rows():
    service, transport = make_service(json_response(200, export_payload()["devices"]))

    devices = service.list_devices("access-1")

    assert len(devices) == 1
    assert devices[0].installation_id == "11111111-1111-4111-8111-111111111111"
    assert devices[0].client_version == "0.2.0"


def test_revoke_device_posts_installation_id():
    service, transport = make_service(json_response(200, {}))

    service.revoke_device("access-1", "11111111-1111-4111-8111-111111111111")

    request = transport.requests[0]
    assert request["url"].endswith("/rest/v1/rpc/revoke_device")
    assert request["body"] == {
        "installation_id": "11111111-1111-4111-8111-111111111111"
    }


def test_sign_out_all_devices_returns_revoked_count():
    service, transport = make_service(json_response(200, {"revoked_devices": 3}))

    count = service.sign_out_all_devices("access-1")

    assert count == 3
    assert transport.requests[0]["url"].endswith("/rest/v1/rpc/revoke_all_devices")


def test_delete_account_calls_edge_function():
    service, transport = make_service(
        json_response(
            200,
            {
                "code": "account_deleted",
                "user_id": USER_ID,
                "deleted_games": 12,
                "deleted_devices": 2,
                "deleted_profiles": 1,
                "deleted_auth_user": USER_ID,
            },
        )
    )

    result = service.delete_account("access-1")

    request = transport.requests[0]
    assert request["url"].endswith("/functions/v1/account-delete")
    assert request["headers"]["Authorization"] == "Bearer access-1"
    assert result.deleted_games == 12
    assert result.deleted_devices == 2
    assert result.deleted_auth_user is True


def test_delete_account_forbids_target_mismatch():
    service, transport = make_service(json_response(403, {"code": "target_mismatch"}))

    with pytest.raises(AuthError) as exc_info:
        service.delete_account("access-1")

    assert exc_info.value.code == "target_mismatch"


def test_delete_account_rejects_malformed_success():
    service, transport = make_service(json_response(200, {"code": "other"}))

    with pytest.raises(AuthError) as exc_info:
        service.delete_account("access-1")

    assert exc_info.value.kind is AuthErrorKind.SERVER_REJECTED


def test_account_operations_require_missing_session_raises_token_expired():
    service, transport = make_service(json_response(401, {}))

    with pytest.raises(AuthError) as exc_info:
        service.list_devices("access-1")

    assert exc_info.value.kind is AuthErrorKind.TOKEN_EXPIRED


@pytest.mark.parametrize(
    ("status", "error_code", "expected_kind"),
    [
        (400, "invalid_credentials", AuthErrorKind.CREDENTIALS),
        (400, "email_not_confirmed", AuthErrorKind.EMAIL_UNVERIFIED),
        (400, "refresh_token_not_found", AuthErrorKind.TOKEN_EXPIRED),
        (400, "refresh_token_already_used", AuthErrorKind.TOKEN_EXPIRED),
        (403, "session_not_found", AuthErrorKind.TOKEN_EXPIRED),
        (500, "unexpected_failure", AuthErrorKind.SERVER_REJECTED),
    ],
)
def test_error_classification(status, error_code, expected_kind):
    service, _ = make_service(
        json_response(status, {"error_code": error_code, "msg": "err"})
    )

    with pytest.raises(AuthError) as exc_info:
        service.sign_in("a@test.local", "pw")

    assert exc_info.value.kind is expected_kind
    assert exc_info.value.code == error_code


def test_network_failure_is_classified_as_network():
    service, _ = make_service(NetworkError("연결 실패"))

    with pytest.raises(AuthError) as exc_info:
        service.sign_in("a@test.local", "pw")

    assert exc_info.value.kind is AuthErrorKind.NETWORK


def test_malformed_success_body_is_server_rejected():
    service, _ = make_service(json_response(200, {"access_token": "only"}))

    with pytest.raises(AuthError) as exc_info:
        service.sign_in("a@test.local", "pw")

    assert exc_info.value.kind is AuthErrorKind.SERVER_REJECTED
