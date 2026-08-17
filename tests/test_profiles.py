"""계정별 로컬 프로필 격리와 비파괴 legacy DB 전환 테스트."""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from mdlogger import profiles as profiles_module
from mdlogger.game_service import GameService
from mdlogger.profiles import (
    ProfileError,
    ProfileKind,
    ProfileManager,
    ProfileOwnershipError,
)

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
        "standing_kind": "event_points",
        "play_context_id": "dc_cup_2026_08",
        "event_points_before": 0,
        "event_points_after": 1500,
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


def test_reset_local_data_removes_all_app_data_and_creates_a_new_profile(
    tmp_path: Path,
):
    manager = ProfileManager(tmp_path)
    guest = manager.guest()
    registered = manager.registered(ACCOUNT_A, "계정 A")
    guest_games = open_profile(manager, guest)
    guest_games.insert_game(sample("guest"))
    guest_games.close()
    registered_games = open_profile(manager, registered)
    registered_games.insert_game(sample("registered"))
    registered_games.close()

    manager.accept_data_consent("duel-data-v1")
    manager.remember_profile(registered)
    for filename in (
        "settings.json",
        "decks.json",
        "decks_sync.json",
        "environment_version_cache.json",
        "release_policy_cache.json",
    ):
        (tmp_path / filename).write_text("cached", encoding="utf-8")
    migration_marker = tmp_path / ".legacy-data-migrated"
    migration_marker.touch()
    unrelated_file = tmp_path / "다른 앱 파일.txt"
    unrelated_file.write_text("보존", encoding="utf-8")
    unrelated_dir = tmp_path / "다른 앱 폴더"
    unrelated_dir.mkdir()
    (unrelated_dir / "보존.txt").write_text("보존", encoding="utf-8")

    manager.reset_local_data()

    new_guest = manager.guest()
    assert new_guest.local_profile_id != guest.local_profile_id
    assert new_guest.installation_id != guest.installation_id
    assert manager.last_profile() is None
    assert not manager.has_data_consent("duel-data-v1")
    assert not guest.database_path.exists()
    assert not registered.database_path.exists()
    assert migration_marker.exists()
    assert unrelated_file.read_text(encoding="utf-8") == "보존"
    assert (unrelated_dir / "보존.txt").read_text(encoding="utf-8") == "보존"
    for filename in (
        "settings.json",
        "decks.json",
        "decks_sync.json",
        "environment_version_cache.json",
        "release_policy_cache.json",
    ):
        assert not (tmp_path / filename).exists()


def test_reset_local_data_restores_previous_data_when_fresh_state_creation_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    manager = ProfileManager(tmp_path)
    guest = manager.guest()
    games = open_profile(manager, guest)
    games.insert_game(sample("기존 기록"))
    games.close()
    original_state = (tmp_path / "global" / "profiles.json").read_text(encoding="utf-8")

    def fail_state_creation():
        raise ProfileError("상태 생성 실패")

    monkeypatch.setattr(manager, "_load_or_create_state", fail_state_creation)
    with pytest.raises(ProfileError, match="앱 데이터를 초기화할 수 없습니다"):
        manager.reset_local_data()

    assert guest.database_path.exists()
    assert (tmp_path / "global" / "profiles.json").read_text(
        encoding="utf-8"
    ) == original_state


def test_reset_retries_stale_staging_cleanup_before_reporting_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    manager = ProfileManager(tmp_path)
    guest = manager.guest()
    games = open_profile(manager, guest)
    games.insert_game(sample("기존 기록"))
    games.close()
    original_rmtree = profiles_module.shutil.rmtree
    failed_once = False

    def fail_first_staging_cleanup(path, *args, **kwargs):
        nonlocal failed_once
        if Path(path).name.startswith(".mdlogger-reset-") and not failed_once:
            failed_once = True
            raise OSError("격리 데이터 잠김")
        return original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(profiles_module.shutil, "rmtree", fail_first_staging_cleanup)
    with pytest.raises(ProfileError, match="완전히 제거할 수 없습니다"):
        manager.reset_local_data()

    stale_staging = list(tmp_path.glob(".mdlogger-reset-*"))
    assert len(stale_staging) == 1
    assert (stale_staging[0] / "guest" / "games.db").exists()

    monkeypatch.setattr(profiles_module.shutil, "rmtree", original_rmtree)
    manager.reset_local_data()

    assert not list(tmp_path.glob(".mdlogger-reset-*"))
    assert not guest.database_path.exists()


def test_remembered_registered_profiles_track_known_credential_accounts(tmp_path: Path):
    manager = ProfileManager(tmp_path)
    account_a = manager.registered(ACCOUNT_A, "계정 A")
    account_b = manager.registered(ACCOUNT_B, "계정 B")

    manager.remember_profile(account_a)
    manager.remember_profile(account_b)

    assert manager.credential_account_ids() == (ACCOUNT_A, ACCOUNT_B)
    assert ProfileManager(tmp_path).credential_account_ids() == (ACCOUNT_A, ACCOUNT_B)


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
