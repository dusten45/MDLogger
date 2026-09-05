#!/usr/bin/env python3
"""Create the MDLogger source release archive from a validated immutable commit."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

TAG_PATTERN = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+$")
VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
GIT_OBJECT_PATTERN = re.compile(r"^[0-9a-f]{40,64}$")


class SourceArchiveError(RuntimeError):
    """Raised when an immutable source archive cannot be created safely."""


def load_context(path: Path) -> dict[str, str]:
    """Load the minimal validated release identity needed by ``git archive``."""

    try:
        value: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SourceArchiveError(f"Cannot read release context: {path}") from error
    if not isinstance(value, dict):
        raise SourceArchiveError("Release context must be a JSON object")

    tag = value.get("tag")
    version = value.get("version")
    tag_object_sha = value.get("tag_object_sha")
    commit_sha = value.get("commit_sha")
    if (
        not isinstance(tag, str)
        or not TAG_PATTERN.fullmatch(tag)
        or not isinstance(version, str)
        or not VERSION_PATTERN.fullmatch(version)
        or tag.removeprefix("v") != version
        or not isinstance(tag_object_sha, str)
        or not GIT_OBJECT_PATTERN.fullmatch(tag_object_sha)
        or not isinstance(commit_sha, str)
        or not GIT_OBJECT_PATTERN.fullmatch(commit_sha)
    ):
        raise SourceArchiveError(
            "Release context has an invalid tag, version, or Git object"
        )
    return {
        "tag": tag,
        "version": version,
        "tag_object_sha": tag_object_sha,
        "commit_sha": commit_sha,
    }


def read_version_source(source: str) -> str:
    """Read a literal ``__version__`` value from a version module source string."""

    try:
        module = ast.parse(source)
    except SyntaxError as error:
        raise SourceArchiveError("Tagged project version module is invalid") from error
    for statement in module.body:
        if not isinstance(statement, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "__version__"
            for target in statement.targets
        ):
            continue
        try:
            value = ast.literal_eval(statement.value)
        except ValueError as error:
            raise SourceArchiveError(
                "Tagged __version__ must be a literal string"
            ) from error
        if isinstance(value, str) and VERSION_PATTERN.fullmatch(value):
            return value
        raise SourceArchiveError("Tagged __version__ must use X.Y.Z")
    raise SourceArchiveError(
        "Tagged project version module does not define __version__"
    )


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of one archive."""

    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_checksum(path: Path) -> Path:
    """Write a standard single-file SHA-256 sidecar for the source archive."""

    output = path.with_suffix(path.suffix + ".sha256")
    output.write_text(
        f"{sha256_file(path)}  {path.name}\n", encoding="ascii", newline="\n"
    )
    return output


def write_provenance(context: dict[str, str], archive: Path) -> Path:
    """Bind a validated tag context to the exact source archive digest and byte size."""

    provenance = archive.parent / "source-provenance.json"
    value = {
        "archive": {
            "filename": archive.name,
            "sha256": sha256_file(archive),
            "size_bytes": archive.stat().st_size,
        },
        "context": context,
        "schema_version": 1,
    }
    provenance.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return provenance


def create_source_archive(
    project_root: Path,
    *,
    commit_sha: str,
    version: str,
    output_directory: Path,
) -> tuple[Path, Path]:
    """Archive exactly ``commit_sha`` and return the archive plus its checksum sidecar."""

    if not GIT_OBJECT_PATTERN.fullmatch(commit_sha):
        raise SourceArchiveError("Source archive commit must be a Git object SHA")
    if not VERSION_PATTERN.fullmatch(version):
        raise SourceArchiveError("Source archive version must use X.Y.Z")

    output_directory.mkdir(parents=True, exist_ok=True)
    archive = output_directory / f"MDLogger-{version}-source.tar.gz"
    try:
        with archive.open("wb") as stream:
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(project_root.resolve()),
                    "archive",
                    "--format=tar.gz",
                    f"--prefix=MDLogger-{version}/",
                    commit_sha,
                    "--",
                ],
                check=True,
                stdout=stream,
                stderr=subprocess.PIPE,
            )
    except (OSError, subprocess.CalledProcessError) as error:
        archive.unlink(missing_ok=True)
        detail = (
            error.stderr.decode("utf-8", errors="replace").strip()
            if isinstance(error, subprocess.CalledProcessError) and error.stderr
            else str(error)
        )
        raise SourceArchiveError(f"Cannot create source archive: {detail}") from error

    if archive.stat().st_size == 0:
        archive.unlink(missing_ok=True)
        raise SourceArchiveError("Git created an empty source archive")
    return archive, write_checksum(archive)


def verify_context_matches_repository(
    project_root: Path, context: dict[str, str]
) -> None:
    """Reconfirm that context names the annotated tag and commit in this checkout."""

    ref = f"refs/tags/{context['tag']}"
    try:
        tag_type = subprocess.run(
            ["git", "-C", str(project_root.resolve()), "cat-file", "-t", ref],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        tag_object_sha = subprocess.run(
            ["git", "-C", str(project_root.resolve()), "rev-parse", "--verify", ref],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        commit_sha = subprocess.run(
            [
                "git",
                "-C",
                str(project_root.resolve()),
                "rev-parse",
                "--verify",
                f"{ref}^{{commit}}",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        version_source = subprocess.run(
            [
                "git",
                "-C",
                str(project_root.resolve()),
                "show",
                f"{commit_sha}:src/mdlogger/_version.py",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        detail = (
            error.stderr.strip()
            if isinstance(error, subprocess.CalledProcessError) and error.stderr
            else "Cannot resolve release tag"
        )
        raise SourceArchiveError(detail) from error
    if tag_type != "tag":
        raise SourceArchiveError("Release context tag is not annotated")
    if (
        tag_object_sha != context["tag_object_sha"]
        or commit_sha != context["commit_sha"]
    ):
        raise SourceArchiveError("Release context does not match the checked-out tag")
    if read_version_source(version_source) != context["version"]:
        raise SourceArchiveError(
            "Release context version does not match the tagged source"
        )


def parse_args(arguments: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        description="Create an immutable MDLogger source archive"
    )
    parser.add_argument(
        "--context", type=Path, required=True, help="Validated release context JSON"
    )
    parser.add_argument(
        "--project-root", type=Path, default=Path.cwd(), help="Checked-out project root"
    )
    parser.add_argument(
        "--output-dir", type=Path, required=True, help="Archive output directory"
    )
    return parser.parse_args(arguments)


def main(arguments: list[str] | None = None) -> int:
    """Create an archive and checksum from validated context."""

    args = parse_args(arguments)
    try:
        context = load_context(args.context)
        verify_context_matches_repository(args.project_root, context)
        archive, checksum = create_source_archive(
            args.project_root,
            commit_sha=context["commit_sha"],
            version=context["version"],
            output_directory=args.output_dir,
        )
        provenance = write_provenance(context, archive)
    except SourceArchiveError as error:
        print(f"ERROR: {error}")
        return 1
    print(archive)
    print(checksum)
    print(provenance)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
