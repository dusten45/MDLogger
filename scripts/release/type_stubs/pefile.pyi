"""태그 소스의 PE 검사에서 사용하는 동적 import-directory API 타입."""

from collections.abc import Sequence
from typing import Protocol

class _DirectoryEntryLookup(Protocol):
    def __getitem__(self, key: str, /) -> int: ...

DIRECTORY_ENTRY: _DirectoryEntryLookup

class _ImportDescriptor:
    dll: bytes

class PE:
    DIRECTORY_ENTRY_IMPORT: list[_ImportDescriptor]
    def __init__(self, name: str, *, fast_load: bool = False) -> None: ...
    def parse_data_directories(
        self, directories: Sequence[int] | None = None
    ) -> None: ...
    def close(self) -> None: ...
