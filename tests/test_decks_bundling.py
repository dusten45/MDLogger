"""하드닝 N-4 — 번들 덱 카탈로그 시드 테스트."""

from __future__ import annotations

import json
from pathlib import Path

from mdlogger import decks

DECK_FILE = (
    Path(__file__).resolve().parents[1] / "src" / "mdlogger" / "data" / "decks.json"
)
DECK_FILE = (
    decks.Path(__file__).resolve().parents[1]
    / "src"
    / "mdlogger"
    / "data"
    / "decks.json"
)


def test_bundled_catalog_reads_curated_list():
    catalog = decks.bundled_catalog()
    assert catalog is not None
    assert len(catalog) > 1
    assert all(isinstance(item, str) and item.strip() for item in catalog)


def test_bundled_catalog_matches_shipped_file():
    data = json.loads(DECK_FILE.read_text(encoding="utf-8"))
    assert decks.bundled_catalog() == [str(d).strip() for d in data if str(d).strip()]


def test_load_decks_seeds_from_bundled_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        decks, "bundled_catalog", lambda: ["엑조디아", "기타", "블루아이즈"]
    )
    path = tmp_path / "decks.json"
    result = decks.load_decks(path)
    assert "엑조디아" in result and "블루아이즈" in result
    assert decks.OTHER in result
    assert path.exists()
    assert decks.OTHER in json.loads(path.read_text(encoding="utf-8"))


def test_load_decks_seeds_default_when_no_bundle(tmp_path, monkeypatch):
    monkeypatch.setattr(decks, "bundled_catalog", lambda: None)
    path = tmp_path / "decks.json"
    result = decks.load_decks(path)
    assert result == [decks.OTHER]
