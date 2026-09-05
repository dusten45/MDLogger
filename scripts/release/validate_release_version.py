#!/usr/bin/env python3
"""Validate the immutable tag and version contract for a desktop release."""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

TAG_PATTERN = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+$")
VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
REQUIRED_RELEASE_FILES = (
    "scripts/release/create_source_archive.py",
    "scripts/release/create_release_manifest.py",
    "scripts/release/release_validation.py",
    "scripts/release/verify_windows_release.ps1",
    "scripts/release/verify_flatpak_release.sh",
    "scripts/release/third_party_source_delivery.json",
)


class ReleaseVersionError(RuntimeError):
    """Raised when a requested tag cannot safely produce a desktop release."""


@dataclass(frozen=True)
class ReleaseContext:
    """Validated identity of an immutable desktop release source tree."""

    tag: str
    version: str
    tag_object_sha: str
    commit_sha: str


def validate_tag_format(tag: str) -> str:
    """Return the version encoded by a supported ``vX.Y.Z`` tag."""

    if not TAG_PATTERN.fullmatch(tag):
        raise ReleaseVersionError(
            "Tag must use the exact v<major>.<minor>.<patch> format"
        )
    return tag.removeprefix("v")


def read_project_version(project_root: Path) -> str:
    """Read ``__version__`` without importing release-source application code."""

    version_path = project_root / "src/mdlogger/_version.py"
    try:
        module = ast.parse(
            version_path.read_text(encoding="utf-8"), filename=str(version_path)
        )
    except OSError as error:
        raise ReleaseVersionError(
            f"Cannot read project version: {version_path}"
        ) from error
    except SyntaxError as error:
        raise ReleaseVersionError(
            f"Project version file is invalid: {version_path}"
        ) from error

    for statement in module.body:
        if not isinstance(statement, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "__version__"
            for target in statement.targets
        ):
            continue
        try:
            version = ast.literal_eval(statement.value)
        except ValueError as error:
            raise ReleaseVersionError("__version__ must be a literal string") from error
        if isinstance(version, str) and VERSION_PATTERN.fullmatch(version):
            return version
        raise ReleaseVersionError("__version__ must use the exact X.Y.Z format")
    raise ReleaseVersionError("Project version file does not define __version__")


def validate_installer_contract(project_root: Path) -> None:
    """Require the Inno script to derive its release filename from injected version data."""

    installer_path = project_root / "scripts/installer_windows.iss"
    try:
        content = installer_path.read_text(encoding="utf-8")
    except OSError as error:
        raise ReleaseVersionError(
            f"Cannot read Inno Setup script: {installer_path}"
        ) from error

    required_fragments = (
        "#ifndef MyAppVersion",
        "OutputBaseFilename=MDLoggerSetup-{#MyAppVersion}",
        "VersionInfoVersion={#MyAppVersion}",
        "ArchitecturesAllowed=x64compatible",
    )
    missing = [fragment for fragment in required_fragments if fragment not in content]
    if missing:
        raise ReleaseVersionError(
            "Inno Setup script does not support the release version contract: "
            + ", ".join(missing)
        )


def git_output(project_root: Path, *arguments: str) -> str:
    """Run one non-interactive Git query and return stripped standard output."""

    try:
        completed = subprocess.run(
            ["git", "-C", str(project_root), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() or error.stdout.strip() or "Git command failed"
        raise ReleaseVersionError(detail) from error
    return completed.stdout.strip()


def validate_release(
    project_root: Path,
    tag: str,
    *,
    run_git: Callable[..., str] = git_output,
) -> ReleaseContext:
    """Validate that this clean checkout is exactly the requested annotated release tag."""

    project_root = project_root.resolve()
    version = validate_tag_format(tag)
    tracked_version = read_project_version(project_root)
    if tracked_version != version:
        raise ReleaseVersionError(
            f"Tag {tag} does not match src/mdlogger/_version.py ({tracked_version})"
        )

    missing_files = [
        relative
        for relative in REQUIRED_RELEASE_FILES
        if not (project_root / relative).is_file()
    ]
    if missing_files:
        raise ReleaseVersionError(
            "Tag predates the desktop release contract or is incomplete: "
            + ", ".join(missing_files)
        )
    validate_installer_contract(project_root)

    ref = f"refs/tags/{tag}"
    tag_type = run_git(project_root, "cat-file", "-t", ref)
    if tag_type != "tag":
        raise ReleaseVersionError(
            f"{tag} must be an annotated Git tag, not a {tag_type} tag"
        )

    tag_object_sha = run_git(project_root, "rev-parse", "--verify", ref)
    commit_sha = run_git(project_root, "rev-parse", "--verify", f"{ref}^{{commit}}")
    head_sha = run_git(project_root, "rev-parse", "--verify", "HEAD")
    if head_sha != commit_sha:
        raise ReleaseVersionError(
            "Checkout HEAD does not equal the requested tag commit"
        )

    status = run_git(project_root, "status", "--porcelain", "--untracked-files=all")
    if status:
        raise ReleaseVersionError("Release checkout is not clean")

    return ReleaseContext(
        tag=tag,
        version=version,
        tag_object_sha=tag_object_sha,
        commit_sha=commit_sha,
    )


def write_context(context: ReleaseContext, output_path: Path) -> None:
    """Write canonical release context JSON for later isolated workflow jobs."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(asdict(context), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def parse_args(arguments: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        description="Validate a desktop release tag and version"
    )
    parser.add_argument("--tag", required=True, help="Existing annotated vX.Y.Z tag")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Checked-out project root (default: current directory)",
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="Context JSON output path"
    )
    return parser.parse_args(arguments)


def main(arguments: list[str] | None = None) -> int:
    """Validate and persist the release context."""

    args = parse_args(arguments)
    try:
        context = validate_release(args.project_root, args.tag)
        write_context(context, args.output)
    except ReleaseVersionError as error:
        print(f"ERROR: {error}")
        return 1
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
