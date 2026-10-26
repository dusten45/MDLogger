"""별도 관리자 모드 관리 client와 창 테스트."""

from __future__ import annotations

import json
import os

import pytest

from mdlogger.admin_modes import (
    AdminConfigurationError,
    AdminModesClient,
    AdminModesError,
    admin_client_from_environment,
)
from mdlogger.remote.client import HttpResponse, JsonHttpClient


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication

    application = QApplication.instance() or QApplication([])
    yield application


@pytest.fixture
def admin_env_file(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MDLOGGER_SUPABASE_URL", raising=False)
    monkeypatch.delenv("MDLOGGER_SERVICE_ROLE_KEY", raising=False)
    return tmp_path / ".env"


class _Transport:
    def __init__(self, response: HttpResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, str, dict[str, str], bytes | None]] = []

    def request(self, method, url, headers, body, timeout):
        self.calls.append((method, url, headers, body))
        return self.response


def _client(response: HttpResponse) -> tuple[AdminModesClient, _Transport]:
    transport = _Transport(response)
    return (
        AdminModesClient(
            "https://example.supabase.co",
            "service-role-key",
            client=JsonHttpClient(transport),
        ),
        transport,
    )


def test_admin_modes_client_fetches_with_service_role_key():
    client, transport = _client(
        HttpResponse(
            200,
            json.dumps(
                [
                    {
                        "id": "rank-2026-09",
                        "standing_kind": "rank",
                        "display_name": "랭크",
                        "play_context_id": "rank_2026_09",
                        "sort_order": 0,
                        "is_active": True,
                        "season_label": "26.09",
                    }
                ]
            ).encode(),
        )
    )

    assert client.fetch()[0]["id"] == "rank-2026-09"
    method, url, headers, body = transport.calls[0]
    assert method == "GET"
    assert url.startswith("https://example.supabase.co/rest/v1/game_modes?")
    assert headers == {
        "apikey": "service-role-key",
        "Authorization": "Bearer service-role-key",
    }
    assert body is None


def test_admin_modes_client_upsert_uses_admin_rpc():
    client, transport = _client(HttpResponse(200, b"{}"))

    client.upsert(
        {
            "id": "dc-cup-2026-09",
            "standing_kind": "event_points",
            "display_name": "26.09 DC컵",
            "play_context_id": "dc_cup_2026_09",
            "sort_order": 2,
            "is_active": True,
            "season_label": "26.09",
        }
    )

    method, url, headers, body = transport.calls[0]
    assert method == "POST"
    assert url == "https://example.supabase.co/rest/v1/rpc/manage_game_modes"
    assert headers["Authorization"] == "Bearer service-role-key"
    assert json.loads(body or b"{}") == {
        "operation": "upsert",
        "mode_id": "dc-cup-2026-09",
        "standing_kind": "event_points",
        "display_name": "26.09 DC컵",
        "play_context_id": "dc_cup_2026_09",
        "sort_order": 2,
        "is_active": True,
        "season_label": "26.09",
    }


def test_admin_client_requires_local_credentials(admin_env_file):
    with pytest.raises(AdminConfigurationError, match="MDLOGGER_SUPABASE_URL"):
        admin_client_from_environment()


def test_admin_client_reads_local_env_without_exporting_secrets(admin_env_file):
    admin_env_file.write_text(
        "# 관리자 전용 로컬 설정\n"
        '\nMDLOGGER_SUPABASE_URL="https://example.supabase.co/"\n'
        "export MDLOGGER_SERVICE_ROLE_KEY='local-service-role-key'\n"
        "MDLOGGER_SUPABASE_ANON_KEY=public-key\n"
        "ignored line\n",
        encoding="utf-8-sig",
    )
    transport = _Transport(HttpResponse(200, b"[]"))

    client = admin_client_from_environment(client=JsonHttpClient(transport))

    assert client.base_url == "https://example.supabase.co"
    assert client.fetch() == []
    assert transport.calls[0][2]["Authorization"] == "Bearer local-service-role-key"
    assert "MDLOGGER_SERVICE_ROLE_KEY" not in os.environ
    assert "MDLOGGER_SUPABASE_URL" not in os.environ


@pytest.mark.parametrize("with_env_file", [False, True])
def test_admin_client_prefers_environment(admin_env_file, monkeypatch, with_env_file):
    if with_env_file:
        admin_env_file.write_text(
            "MDLOGGER_SUPABASE_URL=https://file.supabase.co\n"
            "MDLOGGER_SERVICE_ROLE_KEY=file-service-role-key\n",
            encoding="utf-8",
        )
    monkeypatch.setenv("MDLOGGER_SUPABASE_URL", "https://environment.supabase.co")
    monkeypatch.setenv("MDLOGGER_SERVICE_ROLE_KEY", "environment-service-role-key")
    transport = _Transport(HttpResponse(200, b"[]"))

    client = admin_client_from_environment(client=JsonHttpClient(transport))

    assert client.base_url == "https://environment.supabase.co"
    client.fetch()
    assert transport.calls[0][2]["apikey"] == "environment-service-role-key"


def test_admin_client_uses_env_file_for_missing_environment_value(
    admin_env_file, monkeypatch
):
    admin_env_file.write_text(
        "MDLOGGER_SUPABASE_URL=https://example.supabase.co\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MDLOGGER_SERVICE_ROLE_KEY", "environment-service-role-key")

    client = admin_client_from_environment()

    assert client.base_url == "https://example.supabase.co"


def test_admin_client_rejects_anon_only_env_file(admin_env_file):
    admin_env_file.write_text(
        "MDLOGGER_SUPABASE_URL=https://example.supabase.co\n"
        "MDLOGGER_SUPABASE_ANON_KEY=public-key\n",
        encoding="utf-8",
    )
    transport = _Transport(HttpResponse(200, b"[]"))

    with pytest.raises(AdminConfigurationError, match="MDLOGGER_SERVICE_ROLE_KEY"):
        admin_client_from_environment(client=JsonHttpClient(transport))

    assert transport.calls == []


def test_admin_client_empty_environment_key_does_not_fall_back(
    admin_env_file, monkeypatch
):
    admin_env_file.write_text(
        "MDLOGGER_SUPABASE_URL=https://example.supabase.co\n"
        "MDLOGGER_SERVICE_ROLE_KEY=file-service-role-key\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MDLOGGER_SERVICE_ROLE_KEY", "")

    with pytest.raises(AdminConfigurationError, match="MDLOGGER_SERVICE_ROLE_KEY"):
        admin_client_from_environment()


@pytest.mark.parametrize("invalid_file", [False, True])
def test_admin_client_rejects_unreadable_env_file(admin_env_file, invalid_file):
    if invalid_file:
        admin_env_file.write_bytes(b"\xff")
    else:
        admin_env_file.mkdir()

    with pytest.raises(AdminConfigurationError, match="MDLOGGER_SERVICE_ROLE_KEY"):
        admin_client_from_environment()


@pytest.mark.parametrize("status", [401, 500])
def test_admin_modes_client_rejects_failed_response(status):
    client, _ = _client(HttpResponse(status, b'{"message":"denied"}'))

    with pytest.raises(AdminModesError, match=f"HTTP {status}"):
        client.fetch()


def test_admin_window_renders_server_modes(qapp):
    from mdlogger.ui.admin_window import AdminWindow

    class FakeClient:
        base_url = "https://example.supabase.co"

        def fetch(self):
            return [
                {
                    "id": "rating-2026-09",
                    "standing_kind": "rating",
                    "display_name": "레이팅",
                    "play_context_id": "rating_2026_09",
                    "sort_order": 1,
                    "is_active": True,
                    "season_label": "26.09",
                }
            ]

        def upsert(self, mode):
            return dict(mode)

        def delete(self, mode_id):
            return {"id": mode_id}

    window = AdminWindow(FakeClient())
    assert window._table.rowCount() == 1
    mode_id = window._table.item(0, 0)
    assert mode_id is not None and mode_id.text() == "rating-2026-09"
    assert "서버에서 불러왔습니다" in window._status.text()
    window.close()
