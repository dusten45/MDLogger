"""배포 파일의 SHA-256 체크섬을 생성한다.

PyInstaller onedir 산출물처럼 **폴더**를 검증할 때는 폴더 내 모든 일반 파일의
해시를 상대 경로로 담은 단일 ``.sha256`` manifest(표준 sha256sum 형식)를 만든다.
단일 파일이 주어지면 파일 옆에 `<이름>.sha256`를 만든다.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def sha256_file(path: Path) -> str:
    """파일 전체의 SHA-256 해시를 16진수 문자열로 반환한다."""
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def iter_deploy_files(path: Path):
    """검증 대상 파일을 순회한다. 폴더면 일반 파일을 재귀적으로, 파일이면 그것 하나."""
    if path.is_dir():
        yield from (p for p in sorted(path.rglob("*")) if p.is_file())
        return
    yield path


def write_checksum(path: Path) -> Path:
    """단일 파일 옆에 표준 sha256sum 형식의 ``<이름>.sha256`` 파일을 쓴다."""
    output = path.with_suffix(path.suffix + ".sha256")
    output.write_text(f"{sha256_file(path)}  {path.name}\n", encoding="ascii")
    return output


def write_checksum_tree(directory: Path) -> Path:
    """폴더 내 모든 파일의 sha256sum manifest를 ``<폴더이름>.sha256``로 쓴다.

    상대 경로는 manifest 파일 입장에서의 상대 경로로, 배포 후 파일 무결성 검사에
    그대로 쓰일 수 있어야 한다. 폴더 이름을 파일명으로 사용해 위치가 자명하게 한다.
    """
    root = directory.resolve()
    output = root.with_suffix(root.suffix + ".sha256")
    lines: list[str] = []
    for path in iter_deploy_files(root):
        rel = path.relative_to(root)
        lines.append(f"{sha256_file(path)}  {rel.as_posix()}")
    output.write_text("\n".join(lines) + "\n", encoding="ascii")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="배포 파일/폴더의 SHA-256 체크섬 생성")
    parser.add_argument("path", type=Path, help="체크섬을 만들 파일 또는 폴더")
    args = parser.parse_args()
    output = (
        write_checksum_tree(args.path)
        if args.path.is_dir()
        else write_checksum(args.path)
    )
    print(output)


if __name__ == "__main__":
    main()
