"""하드닝 H3 — release policy 해석·조회·캐시·차단 테스트."""

from __future__ import annotations

import mdlogger.release_policy as rp
from mdlogger import __version__
from mdlogger.release_policy import (
    PolicyStatus,
    ReleasePolicy,
    ReleasePolicyClient,
    default_platform,
    evaluate_current,
    evaluate_policy,
    load_cached_policy,
    online_access_allowed,
    parse_version,
    resolve_policy_for_startup,
    save_cached_policy,
    version_less,
)
from mdlogger.remote.client import HttpResponse, JsonHttpClient
from mdlogger.remote.config import RemoteConfig

URL = "https://projects.supabase.co"
CONFIG = RemoteConfig(base_url=URL, anon_key="sb_publishable_x")


class FakeTransport:
    """요청 반환을 문자열/예외로 구성하는 주입 가능 transport."""

    def __init__(self, status: int = 200, body: bytes = b"[]", error=None):
        self.status = status
        self.body = body
        self.error = error
        self.last_url: str | None = None
        self.last_headers: dict[str, str] | None = None

    def request(self, method, url, headers, body, timeout):
        self.last_url = url
        self.last_headers = headers
        if self.error is not None:
            raise self.error
        return HttpResponse(status=self.status, body=self.body)


def _row(**overrides) -> dict:
    base = {
        "platform": "windows",
        "latest_version": "0.1.5",
        "minimum_supported_version": "0.1.0",
        "notice": None,
        "update_url": "",
        "effective_at": None,
        "payload_version_min": 1,
        "payload_version_max": 1,
        "sync_schema_version_min": 1,
        "sync_schema_version_max": 1,
        "block_online": True,
        "block_local_writes": False,
        "allow_export": True,
    }
    base.update(overrides)
    return base


def _policy(**overrides) -> ReleasePolicy:
    return ReleasePolicy.from_row(_row(**overrides))


# ----- 플랫폼 -----


def test_default_platform_maps_os(monkeypatch):
    assert default_platform() in (
        "windows",
        "macos",
        "linux",
    )
    monkeypatch.setattr(rp.sys, "platform", "darwin")
    assert default_platform() == "macos"
    monkeypatch.setattr(rp.sys, "platform", "linux")
    assert default_platform() == "linux"
    monkeypatch.setattr(rp.sys, "platform", "win32")
    assert default_platform() == "windows"
    # 알 수 없는 OS는 windows로 폴백한다.
    monkeypatch.setattr(rp.sys, "platform", "plan9")
    assert default_platform() == "windows"


def test_client_default_platform_is_os_aware(monkeypatch):
    body = (
        b'[{"platform":"linux","latest_version":"0.1.6",'
        b'"minimum_supported_version":"0.1.6"}]'
    )
    transport, client = _fake_client(body=body)
    monkeypatch.setattr(rp.sys, "platform", "linux")
    policy = ReleasePolicyClient(CONFIG, client=client).fetch()
    assert policy is not None
    assert "platform=eq.linux" in transport.last_url


# ----- 버전 해석/비교 -----


def test_parse_version_normalizes():
    assert parse_version("0.1.5") == (0, 1, 5)
    assert parse_version("v0.1.5") == (0, 1, 5)
    assert parse_version("1") == (1, 0, 0)
    assert parse_version("1.2") == (1, 2, 0)
    assert parse_version("1.2.3-rc1") == (1, 2, 3)
    assert parse_version("not-a-version") == (0, 0, 0)


def test_version_less():
    assert version_less("0.1.4", "0.1.5")
    assert version_less("0.9.0", "1.0.0")
    assert not version_less("0.1.5", "0.1.5")
    assert not version_less("0.2.0", "0.1.5")


# ----- 판정 -----


def test_evaluate_no_policy_is_current():
    assert evaluate_policy(__version__, None) is PolicyStatus.CURRENT


def test_evaluate_below_minimum():
    policy = _policy(minimum_supported_version="99.0.0", latest_version="99.0.0")
    assert evaluate_policy("0.1.5", policy) is PolicyStatus.BELOW_MINIMUM


def test_evaluate_update_available():
    policy = _policy(latest_version="0.2.0", minimum_supported_version="0.1.0")
    assert evaluate_policy("0.1.5", policy) is PolicyStatus.UPDATE_AVAILABLE


def test_evaluate_current():
    policy = _policy(latest_version="0.1.5", minimum_supported_version="0.1.0")
    assert evaluate_policy("0.1.5", policy) is PolicyStatus.CURRENT


def test_online_access_allowed():
    assert online_access_allowed(PolicyStatus.CURRENT)
    assert online_access_allowed(PolicyStatus.UPDATE_AVAILABLE)
    assert not online_access_allowed(PolicyStatus.BELOW_MINIMUM)


def test_evaluate_current_below_minimum_notice():
    policy = _policy(latest_version="0.2.0", minimum_supported_version="0.2.0")
    result = evaluate_current(policy, current_version="0.1.0")
    assert result.status is PolicyStatus.BELOW_MINIMUM
    assert "0.1.0" in (result.notice or "")


def test_evaluate_current_update_available_notice():
    policy = _policy(notice="새 버전이 있습니다.", latest_version="0.2.0")
    result = evaluate_current(policy, current_version="0.1.5")
    assert result.status is PolicyStatus.UPDATE_AVAILABLE
    assert result.notice == "새 버전이 있습니다."


# ----- 조회 -----


def _fake_client(status=200, body=b"[]", error=None):
    transport = FakeTransport(status=status, body=body, error=error)
    return transport, JsonHttpClient(transport=transport)


def test_fetch_returns_policy_from_row():
    body = (
        b'[{"platform":"windows","latest_version":"0.1.5",'
        b'"minimum_supported_version":"0.1.0","plan":1}]'
    )
    transport, client = _fake_client(body=body)
    policy = ReleasePolicyClient(CONFIG, client=client).fetch()
    assert policy is not None
    assert policy.latest_version == "0.1.5"
    assert "release_policies" in transport.last_url
    assert "apikey" in transport.last_headers


def test_fetch_empty_or_http_error_returns_none(tmp_path):
    policy = ReleasePolicyClient(CONFIG, client=_fake_client(body=b"[]")[1]).fetch()
    assert policy is None
    policy = ReleasePolicyClient(CONFIG, client=_fake_client(status=403)[1]).fetch()
    assert policy is None


def test_fetch_network_error_returns_none():
    from mdlogger.remote.errors import NetworkError

    # 실제 transport는 OSError/URLError를 NetworkError로 바꾸므로 그 경로를 검증한다.
    _, client = _fake_client(error=NetworkError("offline"))
    assert ReleasePolicyClient(CONFIG, client=client).fetch() is None


def test_fetch_malformed_row_returns_none():
    _, client = _fake_client(
        body=b'[{"platform":"windows",'
        b'"latest_version":"0.1.5",'
        b'"payload_version_min":"not-an-int"}]'
    )
    # from_row가 ValueError를 올리면 fetch는 None을 돌려준다.
    assert ReleasePolicyClient(CONFIG, client=client).fetch() is None


# ----- 캐시 -----


def test_cache_round_trip(tmp_path):
    cache = tmp_path / "release_policy_cache.json"
    policy = _policy(latest_version="0.2.0", minimum_supported_version="0.1.0")
    save_cached_policy(policy, cache)
    loaded = load_cached_policy(cache)
    assert loaded is not None
    assert loaded.to_dict() == policy.to_dict()


def test_save_cached_policy_swallows_os_error(tmp_path):
    """P1-12: 읽기 전용/가득 찬 데이터 디렉터리에서도 캐시 저장 실패가 앱 시작을 막지 않는다."""
    cache = tmp_path / "release_policy_cache.json"
    # 경로가 디렉터리면 write_text가 OSError를 일으킨다.
    cache.mkdir()

    save_cached_policy(_policy(), cache)


def test_cache_corrupted_returns_none(tmp_path):
    cache = tmp_path / "release_policy_cache.json"
    cache.write_text("not json", encoding="utf-8")
    assert load_cached_policy(cache) is None


# ----- startup 해석 -----


def test_resolve_online_fetches_and_caches(tmp_path):
    cache = tmp_path / "release_policy_cache.json"
    body = (
        b'[{"platform":"windows","latest_version":"0.1.5",'
        b'"minimum_supported_version":"0.1.0"}]'
    )
    _, client = _fake_client(body=body)
    policy, allowed = resolve_policy_for_startup(CONFIG, cache, client=client)
    assert allowed is True
    assert policy is not None and cache.exists()


def test_resolve_online_below_minimum_gates_off(tmp_path):
    cache = tmp_path / "release_policy_cache.json"
    body = (
        b'[{"platform":"windows","latest_version":"0.3.0",'
        b'"minimum_supported_version":"0.3.0"}]'
    )
    _, client = _fake_client(body=body)
    policy, allowed = resolve_policy_for_startup(CONFIG, cache, client=client)
    assert policy is not None
    assert allowed is False


def test_resolve_offline_falls_back_to_cache(tmp_path):
    cache = tmp_path / "release_policy_cache.json"
    save_cached_policy(_policy(), cache)
    policy, allowed = resolve_policy_for_startup(None, cache)
    assert policy is not None and allowed is True


def test_resolve_no_policy_allows(tmp_path):
    cache = tmp_path / "release_policy_cache.json"
    policy, allowed = resolve_policy_for_startup(None, cache)
    assert policy is None and allowed is True


def test_fetch_malformed_row_via_startup_is_safe(tmp_path):
    cache = tmp_path / "release_policy_cache.json"
    body = b'[{"platform":"windows","payload_version_min":"bad"}]'
    _, client = _fake_client(body=body)
    # 잘못된 행: from_row가 실패해 fetch가 None → 캐시도 없음 → 최신 동작 보존.
    policy, allowed = resolve_policy_for_startup(CONFIG, cache, client=client)
    assert policy is None and allowed is True


def test_fetch_malformed_json_body_is_safe(tmp_path):
    """B-3: 200 응답이 깨진 JSON이어도 response.json() 예외에 비차단으로
    처리되어 앱 시작을 막지 않는다."""
    cache = tmp_path / "release_policy_cache.json"
    _, client = _fake_client(body=b"not-json{")

    policy, allowed = resolve_policy_for_startup(CONFIG, cache, client=client)
    assert policy is None and allowed is True
