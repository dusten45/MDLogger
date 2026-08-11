"""local/staging Supabase에 대한 실제 인증·ingest 통합 테스트.

기본적으로 skip되며, 소유자가 local Supabase(`supabase start`)를 띄우고
다음 환경 변수를 설정했을 때만 실행된다.

- ``MDLOGGER_SUPABASE_URL``
- ``MDLOGGER_SUPABASE_ANON_KEY``
- ``MDLOGGER_TEST_EMAIL`` / ``MDLOGGER_TEST_PASSWORD`` (인증 테스트용,
  이메일 인증이 완료된 테스트 계정)
"""

from __future__ import annotations

import os
import uuid

import pytest

from mdlogger.auth.models import AuthError, AuthErrorKind
from mdlogger.auth.supabase_auth import SupabaseAccountService
from mdlogger.remote.config import RemoteConfig, get_remote_config
from mdlogger.remote.games import RegisteredGamesClient, build_registered_game
from mdlogger.remote.guest_ingest import GuestIngestClient, build_observation


def _config() -> RemoteConfig | None:
    return get_remote_config()


requires_supabase = pytest.mark.skipif(
    _config() is None,
    reason="MDLOGGER_SUPABASE_URL/ANON_KEY가 설정된 경우에만 실행",
)

requires_test_account = pytest.mark.skipif(
    not (
        os.environ.get("MDLOGGER_TEST_EMAIL")
        and os.environ.get("MDLOGGER_TEST_PASSWORD")
    ),
    reason="MDLOGGER_TEST_EMAIL/PASSWORD가 설정된 경우에만 실행",
)


@requires_supabase
@requires_test_account
def test_sign_in_refresh_and_sign_out_round_trip():
    config = _config()
    assert config is not None
    service = SupabaseAccountService(config)

    session = service.sign_in(
        os.environ["MDLOGGER_TEST_EMAIL"], os.environ["MDLOGGER_TEST_PASSWORD"]
    )
    assert session.account.user_id

    refreshed = service.refresh_session(session.tokens.refresh_token)
    assert refreshed.account.user_id == session.account.user_id

    service.sign_out(refreshed.tokens.access_token)

    with pytest.raises(AuthError) as exc_info:
        service.refresh_session(refreshed.tokens.refresh_token)
    assert exc_info.value.kind is AuthErrorKind.TOKEN_EXPIRED


@requires_supabase
def test_registered_games_uuid_upsert_round_trip():
    config = _config()
    assert config is not None
    auth = SupabaseAccountService(config)
    signup = auth.sign_up(
        f"sync-{uuid.uuid4().hex}@test.local", "local-test-password-123"
    )
    if signup.session is None:
        pytest.skip("local Supabase가 이메일 인증을 요구함")
    session = signup.session
    sync_id = str(uuid.uuid4())
    payload = {
        "played_at": "2026-08-07T12:00:00",
        "result": "win",
        "turn_order": "first",
        "note": "private note",
        "timezone_offset_minutes": 540,
    }
    client = RegisteredGamesClient(config)

    first = client.upsert_batch(
        [
            build_registered_game(
                payload,
                sync_id=sync_id,
                user_id=session.account.user_id,
                operation="upsert",
                payload_version=1,
            )
        ],
        access_token=session.tokens.access_token,
    )
    second = client.upsert_batch(
        [
            build_registered_game(
                {**payload, "result": "lose"},
                sync_id=sync_id,
                user_id=session.account.user_id,
                operation="upsert",
                payload_version=1,
            )
        ],
        access_token=session.tokens.access_token,
    )

    assert second.remote_versions[sync_id] > first.remote_versions[sync_id]


@requires_supabase
def test_invalid_credentials_classification():
    config = _config()
    assert config is not None
    service = SupabaseAccountService(config)

    with pytest.raises(AuthError) as exc_info:
        service.sign_in(f"missing-{uuid.uuid4().hex}@test.local", "wrong-password")
    assert exc_info.value.kind is AuthErrorKind.CREDENTIALS


@requires_supabase
def test_guest_batch_ingest_is_idempotent():
    config = _config()
    assert config is not None
    client = GuestIngestClient(config, str(uuid.uuid4()))
    observation = build_observation(
        {
            "sync_id": str(uuid.uuid4()),
            "played_at": "2026-08-07T12:00:00",
            "result": "win",
            "turn_order": "second",
            "turns": 6,
            "end_reason": "regular",
        }
    )
    batch_id = str(uuid.uuid4())

    first = client.upload_batch([observation], batch_id=batch_id)
    assert first.accepted == 1

    replay = client.upload_batch([observation], batch_id=batch_id)
    assert replay.replayed
    assert replay.accepted == 1
