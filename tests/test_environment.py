"""하드닝 H4 — 환경 버전 캐시·조회·신규 기록 stamping 테스트."""

from __future__ import annotations

from mdlogger import db
from mdlogger.environment import (
    EnvironmentVersionClient,
    EnvironmentVersionProvider,
    load_env_id,
    refresh_from_server,
    save_env_id,
)
from mdlogger.remote.client import HttpResponse, JsonHttpClient
from mdlogger.remote.config import RemoteConfig

URL = "https://projects.supabase.co"
CONFIG = RemoteConfig(base_url=URL, anon_key="sb_publishable_x")


class FakeTransport:
    def __init__(self, status=200, body=b"[]", error=None):
        self.status = status
        self.body = body
        self.error = error
        self.last_url: str | None = None

    def request(self, method, url, headers, body, timeout):
        self.last_url = url
        if self.error is not None:
            raise self.error
        return HttpResponse(status=self.status, body=self.body)


def _sample() -> dict:
    return dict(
        played_at="2026-08-07T10:00:00",
        result="win",
        turn_order="first",
        my_deck="스네이크아이",
        opp_deck="블루아이즈",
        turns=5,
        end_reason="regular",
        score_after=2600,
        note="",
    )


# ----- 캐시 파일 -----


def test_env_cache_round_trip(tmp_path):
    cache = tmp_path / "env_cache.json"
    assert load_env_id(cache) is None
    save_env_id(cache, "md-2026-08")
    assert load_env_id(cache) == "md-2026-08"
    save_env_id(cache, None)
    assert load_env_id(cache) is None


def test_env_cache_corrupted_returns_none(tmp_path):
    cache = tmp_path / "env_cache.json"
    cache.write_text("broken", encoding="utf-8")
    assert load_env_id(cache) is None


def test_environment_provider_set_and_reload(tmp_path):
    cache = tmp_path / "env_cache.json"
    provider = EnvironmentVersionProvider(cache_path=cache)
    assert provider.current() is None
    provider.set_current("md-2026-08")
    assert provider.current() == "md-2026-08"
    reloaded = EnvironmentVersionProvider(cache_path=cache)
    assert reloaded.current() == "md-2026-08"


# ----- 조회 -----


def test_fetch_current_returns_id_and_queries_current_row():
    transport = FakeTransport(body=b'[{"id":"md-2026-08"}]')
    client = EnvironmentVersionClient(CONFIG, client=JsonHttpClient(transport))
    assert client.fetch_current() == "md-2026-08"
    assert transport.last_url is not None
    assert "environment_versions" in transport.last_url
    assert "lte.now" in transport.last_url
    assert "gte.now" in transport.last_url


def test_fetch_current_empty_or_error_returns_none():
    client = EnvironmentVersionClient(
        CONFIG, client=JsonHttpClient(FakeTransport(body=b"[]"))
    )
    assert client.fetch_current() is None
    bad_client = EnvironmentVersionClient(
        CONFIG, client=JsonHttpClient(FakeTransport(status=500))
    )
    assert bad_client.fetch_current() is None
    from mdlogger.remote.errors import NetworkError

    error_client = EnvironmentVersionClient(
        CONFIG, client=JsonHttpClient(FakeTransport(error=NetworkError("offline")))
    )
    assert error_client.fetch_current() is None


# ----- 신규 기록 stamping -----


def test_insert_game_stamps_environment_id_when_known(monkeypatch, tmp_path):
    cache = tmp_path / "env_cache.json"
    provider = EnvironmentVersionProvider(cache_path=cache)
    provider.set_current("md-2026-08")
    monkeypatch.setattr(db, "_environment_id", provider.current)
    conn = db.connect(":memory:")
    db.init_db(conn)
    gid = db.insert_game(conn, _sample())
    row = db.get_game(conn, gid)
    assert row is not None
    assert row["environment_version_id"] == "md-2026-08"


def test_insert_game_leaves_environment_null_when_unknown(monkeypatch):
    monkeypatch.setattr(db, "_environment_id", lambda: None)
    conn = db.connect(":memory:")
    db.init_db(conn)
    gid = db.insert_game(conn, _sample())
    row = db.get_game(conn, gid)
    assert row is not None
    assert row["environment_version_id"] is None


def test_update_game_does_not_change_environment(monkeypatch):
    monkeypatch.setattr(db, "_environment_id", lambda: "md-2026-08")
    conn = db.connect(":memory:")
    db.init_db(conn)
    gid = db.insert_game(conn, _sample())
    monkeypatch.setattr(db, "_environment_id", lambda: "md-2026-09")
    db.update_game(conn, gid, {**_sample(), "score_after": 5200})
    row = db.get_game(conn, gid)
    assert row is not None
    assert row["environment_version_id"] == "md-2026-08"
    assert row["score_after"] == 5200


# ----- startup refresh -----


def test_refresh_from_server_online_caches(monkeypatch, tmp_path):
    cache = tmp_path / "env_cache.json"
    provider = EnvironmentVersionProvider(cache_path=cache)
    monkeypatch.setattr("mdlogger.environment._PROVIDER", provider)
    monkeypatch.setattr(
        EnvironmentVersionClient,
        "fetch_current",
        lambda self: "md-2026-08",
    )
    assert refresh_from_server(CONFIG) == "md-2026-08"
    assert provider.current() == "md-2026-08"


def test_refresh_from_server_offline_uses_cache(monkeypatch, tmp_path):
    cache = tmp_path / "env_cache.json"
    provider = EnvironmentVersionProvider(cache_path=cache)
    provider.set_current("cached-env")
    monkeypatch.setattr("mdlogger.environment._PROVIDER", provider)
    assert refresh_from_server(None) == "cached-env"


# ----- allowlist wiring -----


def test_guest_observation_includes_environment_version_when_present():
    from mdlogger.remote.guest_ingest import build_observation

    observation = build_observation(
        {
            "sync_id": "11111111-1111-4111-8111-111111111111",
            "played_at": "2026-08-07T10:00:00",
            "result": "win",
            "turn_order": "first",
            "environment_version_id": "md-2026-08",
        }
    )
    assert observation["environment_version_id"] == "md-2026-08"


def test_registered_change_includes_environment_and_client_version():
    from mdlogger.remote.games import build_game_change

    change = build_game_change(
        {
            "played_at": "2026-08-07T10:00:00",
            "result": "win",
            "turn_order": "first",
            "environment_version_id": "md-2026-08",
        },
        sync_id="11111111-1111-4111-8111-111111111111",
        operation="upsert",
        remote_version=None,
    )
    assert change["client_version"]
    assert change["payload"]["environment_version_id"] == "md-2026-08"
