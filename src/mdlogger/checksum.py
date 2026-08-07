"""배포 파일의 SHA-256 체크섬을 생성한다."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def sha256_file(path: Path) -> str:
    """파일 전체의 SHA-256 해시를 16진수 문자열로 반환한다."""
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def write_checksum(path: Path) -> Path:
    """파일 옆에 표준 sha256sum 형식의 ``.sha256`` 파일을 쓴다."""
    output = path.with_suffix(path.suffix + ".sha256")
    output.write_text(f"{sha256_file(path)}  {path.name}\n", encoding="ascii")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="배포 파일의 SHA-256 체크섬 생성")
    parser.add_argument("file", type=Path, help="체크섬을 만들 파일")
    args = parser.parse_args()
    output = write_checksum(args.file)
    print(output)


if __name__ == "__main__":
    main()
