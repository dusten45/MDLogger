"""취향 설정 동기화 클라이언트 테스트 (계획 2, spec §8.2)."""

from __future__ import annotations

import json

import pytest

from mdlogger.app_settings import DEVICE_KEYS, PREFERENCE_KEYS
from mdlogger.remote.client import HttpResponse, JsonHttpClient
from mdlogger.remote.config import RemoteConfig
from mdlogger.remote.errors import NetworkError
from mdlogger.remote.settings_sync import SettingsSyncClient, SettingsSyncError

CONFIG = RemoteConfig(base_url="https://example.supabase.co", anon_key="anon-key")
TOKEN = "access-token"


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
            }
        )
        return self.responses.pop(0)


def _client(transport) -> SettingsSyncClient:
    return SettingsSyncClient(CONFIG, client=JsonHttpClient(transport))


def test_upload_strips_device_keys_and_sends_only_preferences() -> None:
    transport = FakeTransport([HttpResponse(status=204)])
    client = _client(transport)

    client.upload(
        {
            "theme_mode": "dark",
            "accent_color": "teal",
            "memo_enabled": False,
            "default_mode": "rank-2026-08",
            "font_scale": 1.5,
            "low_spec_mode": True,
            "reduce_motion": "on",
        },
        TOKEN,
    )

    sent = transport.requests[0]["body"]["preferences"]
    assert set(sent) == set(PREFERENCE_KEYS)
    assert set(sent).isdisjoint(set(DEVICE_KEYS))
    assert sent["theme_mode"] == "dark"


def test_upload_omits_missing_preference_keys() -> None:
    transport = FakeTransport([HttpResponse(status=204)])
    client = _client(transport)

    client.upload({"theme_mode": "light"}, TOKEN)

    assert transport.requests[0]["body"]["preferences"] == {"theme_mode": "light"}


def test_download_returns_only_preference_keys() -> None:
    transport = FakeTransport(
        [
            HttpResponse(
                status=200,
                body=json.dumps(
                    [
                        {
                            "preferences": {
                                "theme_mode": "dark",
                                "accent_color": "amber",
                                "font_scale": 1.5,
                                "unknown": "x",
                            }
                        }
                    ]
                ).encode(),
            )
        ]
    )
    client = _client(transport)

    result = client.download(TOKEN)

    assert result == {"theme_mode": "dark", "accent_color": "amber"}


def test_download_returns_none_when_no_row() -> None:
    transport = FakeTransport([HttpResponse(status=200, body=json.dumps([]).encode())])
    client = _client(transport)

    assert client.download(TOKEN) is None


def test_upload_rejected_raises_error() -> None:
    transport = FakeTransport([HttpResponse(status=403, body=b"{}")])
    client = _client(transport)

    with pytest.raises(SettingsSyncError):
        client.upload({"theme_mode": "dark"}, TOKEN)


def test_download_rejected_raises_error() -> None:
    transport = FakeTransport([HttpResponse(status=401, body=b"{}")])
    client = _client(transport)

    with pytest.raises(SettingsSyncError):
        client.download(TOKEN)


class _FailingTransport:
    def request(self, method, url, headers, body, timeout):
        raise NetworkError("서버에 연결할 수 없습니다.")


def test_network_error_is_wrapped() -> None:
    client = _client(_FailingTransport())

    with pytest.raises(SettingsSyncError):
        client.upload({"theme_mode": "dark"}, TOKEN)
