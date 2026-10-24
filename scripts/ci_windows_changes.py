"""Windows 패키징과 무관한 변경만 확인된 경우 무거운 빌드 단계를 생략한다."""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def packaging_required(paths: list[str] | None) -> bool:
    # 알 수 없는 경로와 빈 비교 결과는 전체 검증으로 보낸다. 라이선스 검사는 별도다.
    independent_files = {"README.md", "AGENTS.md", "THIRD_PARTY_NOTICES.md"}
    return not paths or any(
        path not in independent_files
        and not path.startswith(("web/", "docs/", "tests/"))
        for path in paths
    )


def _git(project_root: Path, *arguments: str) -> bytes:
    return subprocess.run(
        ["git", *arguments],
        cwd=project_root,
        check=True,
        capture_output=True,
        timeout=60,
    ).stdout


def changed_paths(project_root: Path, base: object) -> list[str] | None:
    if (
        not isinstance(base, str)
        or not re.fullmatch(r"[0-9a-fA-F]{40}", base)
        or base == "0" * 40
    ):
        return None
    try:
        try:
            _git(project_root, "rev-parse", "--verify", f"{base}^{{commit}}")
        except subprocess.CalledProcessError:
            _git(project_root, "fetch", "--no-tags", "--depth=1", "origin", base)
        # 이름 변경은 삭제와 추가로 취급해 기존 데스크톱 경로도 놓치지 않는다.
        output = _git(
            project_root, "diff", "--no-renames", "--name-only", "-z", base, "HEAD"
        )
        return [os.fsdecode(path) for path in output.split(b"\0") if path]
    except (OSError, subprocess.SubprocessError):
        return None


def base_ci_succeeded(base: str) -> bool:
    # 이전 실패나 취소를 문서 변경으로 가리지 않는다. API 오류도 전체 검증으로 보낸다.
    try:
        repository = os.environ["GITHUB_REPOSITORY"]
        token = os.environ["GH_TOKEN"]
        api = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
        query = urllib.parse.urlencode(
            {"head_sha": base, "event": "push", "status": "success", "per_page": 1}
        )
        request = urllib.request.Request(
            f"{api}/repos/{repository}/actions/workflows/ci.yml/runs?{query}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            runs = json.load(response)["workflow_runs"]
        return any(
            run["head_sha"] == base and run["conclusion"] == "success" for run in runs
        )
    except (KeyError, OSError, ValueError, TypeError, urllib.error.URLError):
        return False


def main() -> None:
    paths = None
    base = None
    try:
        event = json.loads(
            Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8")
        )
        match os.environ.get("GITHUB_EVENT_NAME"):
            case "push":
                base = event["before"]
            case "pull_request":
                # checkout의 기본 PR 병합 커밋과 대상 브랜치의 차이를 검사한다.
                base = event["pull_request"]["base"]["sha"]
            case _:
                base = None
        paths = changed_paths(PROJECT_ROOT, base)
    except (KeyError, OSError, ValueError, TypeError):
        pass

    required = str(
        packaging_required(paths)
        or not isinstance(base, str)
        or not base_ci_succeeded(base)
    ).lower()
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
        output.write(f"required={required}\n")
    print(f"Windows packaging required: {required}")


if __name__ == "__main__":
    main()
