"""게임 기록용 repository 및 계정 범위 서비스 경계."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Protocol

from . import db, export, portable
from .paths import DB_PATH
from .profiles import ProfileKind


class GameRepository(Protocol):
    """현재 프로필의 게임 기록 저장소 계약."""

    def close(self) -> None: ...

    def insert_game(self, data: dict) -> int: ...

    def update_game(self, game_id: int, data: dict) -> None: ...

    def delete_game(self, game_id: int) -> None: ...

    def get_game(self, game_id: int) -> sqlite3.Row | None: ...

    def get_last_game(self) -> sqlite3.Row | None: ...

    def get_last_score(self) -> int: ...

    def get_last_my_deck(self) -> str: ...

    def get_today_record(self) -> tuple[int, int]: ...

    def count_games(self) -> int: ...

    def get_all_games(self) -> list[sqlite3.Row]: ...

    def get_summary(self) -> dict: ...

    def get_score_series(self) -> list[sqlite3.Row]: ...

    def get_deck_matchups(self, turn_filter: str | None = None) -> list[dict]: ...


class SqliteGameRepository:
    """기존 ``db.py`` 쿼리를 하나의 SQLite 연결에 결합한다."""

    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection

    @classmethod
    def open(cls, db_path: Path | str = DB_PATH) -> SqliteGameRepository:
        connection = db.connect(db_path)
        db.init_db(connection)
        return cls(connection)

    def close(self) -> None:
        self._connection.close()

    def insert_game(self, data: dict) -> int:
        return db.insert_game(self._connection, data)

    def update_game(self, game_id: int, data: dict) -> None:
        db.update_game(self._connection, game_id, data)

    def delete_game(self, game_id: int) -> None:
        db.delete_game(self._connection, game_id)

    def get_game(self, game_id: int) -> sqlite3.Row | None:
        return db.get_game(self._connection, game_id)

    def get_last_game(self) -> sqlite3.Row | None:
        return db.get_last_game(self._connection)

    def get_last_score(self) -> int:
        return db.get_last_score(self._connection)

    def get_last_my_deck(self) -> str:
        return db.get_last_my_deck(self._connection)

    def get_today_record(self) -> tuple[int, int]:
        return db.get_today_record(self._connection)

    def count_games(self) -> int:
        return db.count_games(self._connection)

    def get_all_games(self) -> list[sqlite3.Row]:
        return db.get_all_games(self._connection)

    def get_summary(self) -> dict:
        return db.get_summary(self._connection)

    def get_score_series(self) -> list[sqlite3.Row]:
        return db.get_score_series(self._connection)

    def get_deck_matchups(self, turn_filter: str | None = None) -> list[dict]:
        return db.get_deck_matchups(self._connection, turn_filter)


class GameService:
    """UI가 공유하는 현재 프로필 범위의 게임 기능 진입점."""

    def __init__(self, repository: GameRepository):
        self._repository = repository

    @classmethod
    def open(cls, db_path: Path | str = DB_PATH) -> GameService:
        return cls(SqliteGameRepository.open(db_path))

    def close(self) -> None:
        self._repository.close()

    def insert_game(self, data: dict) -> int:
        return self._repository.insert_game(data)

    def update_game(self, game_id: int, data: dict) -> None:
        self._repository.update_game(game_id, data)

    def delete_game(self, game_id: int) -> None:
        self._repository.delete_game(game_id)

    def get_game(self, game_id: int) -> sqlite3.Row | None:
        return self._repository.get_game(game_id)

    def get_last_game(self) -> sqlite3.Row | None:
        return self._repository.get_last_game()

    def get_last_score(self) -> int:
        return self._repository.get_last_score()

    def get_last_my_deck(self) -> str:
        return self._repository.get_last_my_deck()

    def get_today_record(self) -> tuple[int, int]:
        return self._repository.get_today_record()

    def count_games(self) -> int:
        return self._repository.count_games()

    def get_all_games(self) -> list[sqlite3.Row]:
        return self._repository.get_all_games()

    def get_summary(self) -> dict:
        return self._repository.get_summary()

    def get_score_series(self) -> list[sqlite3.Row]:
        return self._repository.get_score_series()

    def get_deck_matchups(self, turn_filter: str | None = None) -> list[dict]:
        return self._repository.get_deck_matchups(turn_filter)

    def export_csv(self, path: str | Path) -> None:
        export.export_csv(path, self._repository.get_all_games())

    def export_xlsx(self, path: str | Path) -> None:
        export.export_xlsx(path, self._repository.get_all_games())

    def export_portable_archive(
        self,
        path: str | Path,
        *,
        profile_kind: ProfileKind = ProfileKind.GUEST,
    ) -> Path:
        return portable.export_portable_archive(
            path,
            self._repository.get_all_games(),
            profile_kind=profile_kind,
        )
