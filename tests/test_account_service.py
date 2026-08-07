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
