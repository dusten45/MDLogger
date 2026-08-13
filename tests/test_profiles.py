"""계정별 로컬 프로필 격리와 비파괴 legacy DB 전환 테스트."""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from mdlogger.game_service import GameService
from mdlogger.profiles import ProfileKind, ProfileManager, ProfileOwnershipError

ACCOUNT_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
ACCOUNT_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def sample(note: str) -> dict:
    return {
        "played_at": "2026-08-07T10:00:00",
        "result": "win",
        "turn_order": "first",
        "my_deck": "테스트 덱",
        "opp_deck": "상대 덱",
        "turns": 4,
        "end_reason": "regular",
        "score_after": 1500,
        "note": note,
    }


def open_profile(manager: ProfileManager, profile) -> GameService:
    manager.prepare_database(profile)
    return GameService.open(profile.database_path)


def test_guest_profile_persists_ids_and_copies_legacy_db_without_deleting_source(
    tmp_path: Path,
):
    legacy_path = tmp_path / "games.db"
    legacy = GameService.open(legacy_path)
    legacy.insert_game(sample("legacy"))
    legacy.close()

    first_manager = ProfileManager(tmp_path)
    first_guest = first_manager.guest()
    guest_games = open_profile(first_manager, first_guest)

    row = guest_games.get_last_game()
    assert row is not None
    assert row["note"] == "legacy"
    guest_games.close()

    second_guest = ProfileManager(tmp_path).guest()
    assert second_guest.local_profile_id == first_guest.local_profile_id
    assert second_guest.installation_id == first_guest.installation_id
    assert legacy_path.exists()
    assert first_guest.database_path == tmp_path / "guest" / "games.db"

    with sqlite3.connect(first_guest.database_path) as connection:
        metadata = connection.execute(
            "SELECT owner_id, profile_kind FROM database_metadata WHERE id=1"
        ).fetchone()
    assert metadata == (first_guest.local_profile_id, ProfileKind.GUEST.value)


def test_last_profile_and_data_consent_persist_without_secrets(tmp_path: Path):
    manager = ProfileManager(tmp_path)
    account = manager.registered(ACCOUNT_A, "a@test.local")

    assert manager.last_profile() is None
    assert not manager.has_data_consent("duel-data-v1")

    manager.accept_data_consent("duel-data-v1")
    manager.remember_profile(account)

    restored_manager = ProfileManager(tmp_path)
    restored = restored_manager.last_profile()
    assert restored is not None
    assert restored.remote_user_id == ACCOUNT_A
    assert restored.display_name == "a@test.local"
    assert restored.consent_version == "duel-data-v1"
    assert restored_manager.has_data_consent("duel-data-v1")

    state_text = (tmp_path / "global" / "profiles.json").read_text()
    assert "password" not in state_text
    assert "access_token" not in state_text
    assert "refresh_token" not in state_text


def test_session_state_updates_on_remember_and_logout(tmp_path: Path):
    """로그인 시 'authenticated'가 기록되고, 프로필을 열지 않는 로그아웃 경로에서는
    set_session_state로 'signed_out'을 기록한다."""
    manager = ProfileManager(tmp_path)
    account = manager.registered(ACCOUNT_A, "a@test.local")

    manager.accept_data_consent("duel-data-v1")
    manager.remember_profile(account)
    profile = manager.last_profile()
    assert profile is not None
    assert profile.session_state == "authenticated"

    manager.set_session_state("signed_out")
    profile = manager.last_profile()
    assert profile is not None
    assert profile.session_state == "signed_out"

    restored_manager = ProfileManager(tmp_path)
    restored = restored_manager.last_profile()
    assert restored is not None
    assert restored.session_state == "signed_out"


def test_old_state_without_session_state_defaults_to_authenticated(tmp_path: Path):
    """session_state 필드가 없는 기존 상태 파일은 기본값 'authenticated'로 읽는다."""
    manager = ProfileManager(tmp_path)
    manager.accept_data_consent("duel-data-v1")
    manager.remember_profile(manager.registered(ACCOUNT_A, "a@test.local"))
    state_path = tmp_path / "global" / "profiles.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.pop("session_state", None)
    state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    restored_manager = ProfileManager(tmp_path)
    restored = restored_manager.last_profile()
    assert restored is not None
    assert restored.session_state == "authenticated"


def test_failed_consent_write_does_not_accept_only_in_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    manager = ProfileManager(tmp_path)

    def fail_write(state) -> None:
        raise ProfileOwnershipError("write failed")

    monkeypatch.setattr(manager, "_write_state", fail_write)
    with pytest.raises(ProfileOwnershipError, match="write failed"):
        manager.accept_data_consent("duel-data-v1")

    assert not manager.has_data_consent("duel-data-v1")


def test_guest_and_two_registered_profiles_are_fully_isolated(tmp_path: Path):
    manager = ProfileManager(tmp_path)
    guest = manager.guest()
    account_a = manager.registered(ACCOUNT_A, "계정 A")
    account_b = manager.registered(ACCOUNT_B, "계정 B")

    assert account_a.database_path != account_b.database_path
    assert ACCOUNT_A not in str(account_a.database_path)

    for profile, note in (
        (guest, "guest"),
        (account_a, "account-a"),
        (account_b, "account-b"),
    ):
        games = open_profile(manager, profile)
        games.insert_game(sample(note))
        games.close()

    for profile, note in (
        (guest, "guest"),
        (account_a, "account-a"),
        (account_b, "account-b"),
    ):
        games = open_profile(manager, profile)
        rows = games.get_all_games()
        assert len(rows) == 1
        assert rows[0]["note"] == note
        games.close()


def test_database_owned_by_account_a_is_rejected_for_account_b(tmp_path: Path):
    manager = ProfileManager(tmp_path)
    account_a = manager.registered(ACCOUNT_A, "계정 A")
    account_b = manager.registered(ACCOUNT_B, "계정 B")
    manager.prepare_database(account_a)

    account_b.database_path.parent.mkdir(parents=True)
    shutil.copy2(account_a.database_path, account_b.database_path)

    with pytest.raises(ProfileOwnershipError, match="다른 프로필"):
        manager.prepare_database(account_b)

    with sqlite3.connect(account_b.database_path) as connection:
        metadata = connection.execute(
            "SELECT owner_id, profile_kind FROM database_metadata WHERE id=1"
        ).fetchone()
    assert metadata == (ACCOUNT_A, ProfileKind.REGISTERED.value)
