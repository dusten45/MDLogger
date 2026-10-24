"""변경 범위 최적화가 필요한 Windows 패키징 검사를 생략하지 않는지 확인한다."""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import urllib.error
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "ci_windows_changes", PROJECT_ROOT / "scripts/ci_windows_changes.py"
)
assert SPEC is not None and SPEC.loader is not None
CHANGES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHANGES)


@pytest.mark.parametrize(
    "paths",
    [
        ["web/src/App.tsx"],
        ["web/package-lock.json"],
        ["docs/security-report.md"],
        ["tests/test_db.py"],
        ["THIRD_PARTY_NOTICES.md"],
        ["README.md", "AGENTS.md", "web/public/third-party-notices.txt"],
    ],
)
def test_only_known_independent_changes_skip_packaging(paths):
    assert not CHANGES.packaging_required(paths)


@pytest.mark.parametrize(
    "path",
    [
        "src/mdlogger/app.py",
        "run.py",
        "MDLogger.spec",
        "pyproject.toml",
        "uv.lock",
        ".github/workflows/ci.yml",
        "scripts/ensure_inno_setup.ps1",
        "scripts/desktop_license_policy.json",
        "LICENSE",
        "THIRD_PARTY_NOTICES.txt",
        "licenses/desktop/notice.txt",
        "licenses/inventory/desktop-windows.json",
        "licenses/sources/desktop-source-offer.md",
        "icon/MDLogger-icon.ico",
        "flatpak/requirements-runtime.txt",
        "unknown-file.txt",
        "website/config.json",
    ],
)
def test_any_shared_desktop_or_unknown_change_requires_packaging(path):
    assert CHANGES.packaging_required(["web/src/App.tsx", path])


@pytest.mark.parametrize("paths", [None, []])
def test_missing_or_empty_comparison_requires_packaging(paths):
    assert CHANGES.packaging_required(paths)


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / "repository"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.name", "CI test")
    _git(root, "config", "user.email", "ci@example.test")
    (root / "src").mkdir()
    (root / "src/runtime.txt").write_text("original", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "initial")
    return root, _git(root, "rev-parse", "HEAD")


def test_push_comparison_includes_all_commits(repository):
    root, base = repository
    (root / "src/runtime.txt").write_text("changed", encoding="utf-8")
    _git(root, "commit", "-am", "runtime change")
    (root / "README.md").write_text("documentation", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "documentation change")

    paths = CHANGES.changed_paths(root, base)

    assert set(paths) == {"src/runtime.txt", "README.md"}
    assert CHANGES.packaging_required(paths)


def test_rename_retains_deleted_desktop_path(repository):
    root, base = repository
    (root / "web").mkdir()
    (root / "src/runtime.txt").rename(root / "web/runtime.txt")
    _git(root, "add", "--all")
    _git(root, "commit", "-m", "move runtime")

    paths = CHANGES.changed_paths(root, base)

    assert set(paths) == {"src/runtime.txt", "web/runtime.txt"}
    assert CHANGES.packaging_required(paths)


def test_shallow_checkout_fetches_base_and_preserves_non_ascii_paths(repository):
    root, base = repository
    (root / "web").mkdir()
    (root / "web/한글 이름.ts").write_text("export {}", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "web change")
    shallow = root.parent / "shallow"
    _git(root, "clone", "--depth=1", root.as_uri(), str(shallow))

    paths = CHANGES.changed_paths(shallow, base)

    assert paths == ["web/한글 이름.ts"]
    assert not CHANGES.packaging_required(paths)


@pytest.mark.parametrize("base", [None, "0" * 40, "--upload-pack=command", {}, "abc"])
def test_invalid_base_does_not_invoke_git(tmp_path, monkeypatch, base):
    monkeypatch.setattr(CHANGES, "_git", lambda *args: pytest.fail("잘못된 비교 기준"))
    assert CHANGES.changed_paths(tmp_path, base) is None


def test_unavailable_base_requires_packaging(repository):
    root, _ = repository
    assert CHANGES.changed_paths(root, "f" * 40) is None


@pytest.mark.parametrize(
    ("event_name", "event", "expected_base"),
    [
        ("push", {"before": "a" * 40}, "a" * 40),
        ("pull_request", {"pull_request": {"base": {"sha": "b" * 40}}}, "b" * 40),
        ("workflow_dispatch", {}, None),
    ],
)
def test_event_uses_push_before_or_pull_request_base(
    tmp_path, monkeypatch, event_name, event, expected_base
):
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event), encoding="utf-8")
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_EVENT_NAME", event_name)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))

    def changed_paths(root, base):
        assert base == expected_base
        return ["web/src/App.tsx"] if base else None

    monkeypatch.setattr(CHANGES, "changed_paths", changed_paths)
    monkeypatch.setattr(CHANGES, "base_ci_succeeded", lambda base: True)
    CHANGES.main()

    required = "false" if expected_base else "true"
    assert output.read_text(encoding="utf-8") == f"required={required}\n"


def test_invalid_event_runs_packaging(tmp_path, monkeypatch):
    event = tmp_path / "event.json"
    event.write_text("not json", encoding="utf-8")
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))

    CHANGES.main()

    assert output.read_text(encoding="utf-8") == "required=true\n"


@pytest.mark.parametrize("successful_base", [False, True])
def test_independent_push_cannot_hide_an_unverified_base(
    tmp_path, monkeypatch, successful_base
):
    base = "a" * 40
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"before": base}), encoding="utf-8")
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(CHANGES, "changed_paths", lambda *args: ["README.md"])
    monkeypatch.setattr(CHANGES, "base_ci_succeeded", lambda base: successful_base)

    CHANGES.main()

    assert output.read_text(encoding="utf-8") == (
        f"required={str(not successful_base).lower()}\n"
    )


@pytest.mark.parametrize(
    ("runs", "expected"),
    [
        ([], False),
        ([{"head_sha": "a" * 40, "conclusion": "failure"}], False),
        ([{"head_sha": "b" * 40, "conclusion": "success"}], False),
        ([{"head_sha": "a" * 40, "conclusion": "success"}], True),
    ],
)
def test_base_verification_requires_success_for_the_same_commit(
    monkeypatch, runs, expected
):
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repository")
    monkeypatch.setenv("GH_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_API_URL", "https://api.github.test")

    def urlopen(request, *, timeout):
        assert request.full_url.startswith(
            "https://api.github.test/repos/owner/repository/actions/workflows/ci.yml/runs?"
        )
        assert f"head_sha={'a' * 40}" in request.full_url
        assert "event=push" in request.full_url
        assert "status=success" in request.full_url
        assert timeout == 10
        return io.BytesIO(json.dumps({"workflow_runs": runs}).encode())

    monkeypatch.setattr(CHANGES.urllib.request, "urlopen", urlopen)

    assert CHANGES.base_ci_succeeded("a" * 40) is expected


def test_api_failure_does_not_skip_packaging(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repository")
    monkeypatch.setenv("GH_TOKEN", "test-token")

    def urlopen(*args, **kwargs):
        raise urllib.error.URLError("unavailable")

    monkeypatch.setattr(CHANGES.urllib.request, "urlopen", urlopen)

    assert not CHANGES.base_ci_succeeded("a" * 40)
