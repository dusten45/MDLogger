"""앱 설정 모델·검증·저장소 테스트 (계획 2, spec §8.1)."""

import json
from pathlib import Path

from mdlogger.app_settings import (
    DEVICE_KEYS,
    PREFERENCE_KEYS,
    SCHEMA_VERSION,
    AccentPreset,
    AppSettings,
    MemorySettingsStore,
    ReduceMotion,
    ScoreInputMode,
    SettingsRepository,
)
from mdlogger.ui.theme import ThemeMode


def test_defaults() -> None:
    settings = AppSettings()
    assert settings.theme_mode is ThemeMode.SYSTEM
    assert settings.accent_color == AccentPreset.BLUE.value
    assert settings.ui_scale == 1.0
    assert settings.low_spec_mode is False
    assert settings.reduce_motion is ReduceMotion.SYSTEM
    assert settings.memo_enabled is True


def test_to_dict_roundtrip() -> None:
    settings = AppSettings(
        theme_mode=ThemeMode.DARK,
        accent_color=AccentPreset.TEAL.value,
        ui_scale=1.25,
        low_spec_mode=True,
        reduce_motion=ReduceMotion.ON,
        memo_enabled=False,
    )
    data = settings.to_dict()
    assert data["schema_version"] == SCHEMA_VERSION
    assert AppSettings.from_dict(data) == settings


def test_from_dict_replaces_out_of_range_ui_scale() -> None:
    assert AppSettings.from_dict({"ui_scale": 0.7}).ui_scale == 1.0
    assert AppSettings.from_dict({"ui_scale": 1.6}).ui_scale == 1.0
    assert AppSettings.from_dict({"ui_scale": 0.75}).ui_scale == 0.75
    assert AppSettings.from_dict({"ui_scale": 1.25}).ui_scale == 1.25
    assert AppSettings.from_dict({"ui_scale": "big"}).ui_scale == 1.0
    assert AppSettings.from_dict({"ui_scale": True}).ui_scale == 1.0


def test_from_dict_accepts_legacy_font_scale() -> None:
    assert AppSettings.from_dict({"font_scale": 1.25}).ui_scale == 1.25
    assert AppSettings.from_dict({"ui_scale": 0.9, "font_scale": 1.25}).ui_scale == 0.9


def test_from_dict_replaces_unknown_accent() -> None:
    assert AppSettings.from_dict({"accent_color": "red"}).accent_color == "blue"
    assert AppSettings.from_dict({"accent_color": 7}).accent_color == "blue"
    assert AppSettings.from_dict({"accent_color": "indigo"}).accent_color == "indigo"


def test_from_dict_replaces_unknown_enums() -> None:
    assert AppSettings.from_dict({"theme_mode": "sepia"}).theme_mode is ThemeMode.SYSTEM
    assert (
        AppSettings.from_dict({"reduce_motion": "sometimes"}).reduce_motion
        is ReduceMotion.SYSTEM
    )
    assert AppSettings.from_dict({"theme_mode": "dark"}).theme_mode is ThemeMode.DARK


def test_from_dict_replaces_non_bool_flags() -> None:
    assert AppSettings.from_dict({"low_spec_mode": "yes"}).low_spec_mode is False
    assert AppSettings.from_dict({"memo_enabled": 1}).memo_enabled is True
    assert AppSettings.from_dict({"low_spec_mode": True}).low_spec_mode is True
    assert AppSettings.from_dict({"memo_enabled": False}).memo_enabled is False


def test_sync_allowlists_are_disjoint() -> None:
    assert set(PREFERENCE_KEYS).isdisjoint(set(DEVICE_KEYS))
    assert "ui_scale" in DEVICE_KEYS
    assert "theme_mode" in PREFERENCE_KEYS
    assert "default_mode" in PREFERENCE_KEYS
    assert "score_input_mode" in PREFERENCE_KEYS


def test_score_input_mode_default_and_roundtrip() -> None:
    assert AppSettings().score_input_mode is ScoreInputMode.DELTA
    settings = AppSettings(score_input_mode=ScoreInputMode.DIRECT)
    data = settings.to_dict()
    assert data["score_input_mode"] == "direct"
    assert AppSettings.from_dict(data).score_input_mode is ScoreInputMode.DIRECT


def test_score_input_mode_invalid_falls_back_to_delta() -> None:
    assert (
        AppSettings.from_dict({"score_input_mode": "bogus"}).score_input_mode
        is ScoreInputMode.DELTA
    )
    assert (
        AppSettings.from_dict({"score_input_mode": 7}).score_input_mode
        is ScoreInputMode.DELTA
    )
    assert (
        AppSettings.from_dict({"score_input_mode": "direct"}).score_input_mode
        is ScoreInputMode.DIRECT
    )


def test_repository_roundtrip(tmp_path: Path) -> None:
    repo = SettingsRepository(tmp_path / "settings.json")
    assert repo.load() == AppSettings()

    settings = AppSettings(theme_mode=ThemeMode.LIGHT, accent_color="amber")
    repo.save(settings)
    assert repo.load() == settings


def test_repository_corrupt_file_returns_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{ not valid json", encoding="utf-8")
    assert SettingsRepository(path).load() == AppSettings()


def test_repository_non_object_returns_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert SettingsRepository(path).load() == AppSettings()


def test_repository_unknown_schema_returns_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"schema_version": 99, "memo_enabled": False}))
    assert SettingsRepository(path).load() == AppSettings()


def test_repository_single_corrupt_field_replaced(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "theme_mode": "dark",
                "accent_color": "nope",
                "ui_scale": 9.9,
                "memo_enabled": False,
            }
        )
    )
    loaded = SettingsRepository(path).load()
    assert loaded.theme_mode is ThemeMode.DARK
    assert loaded.accent_color == "blue"
    assert loaded.ui_scale == 1.0
    assert loaded.memo_enabled is False


def test_repository_save_is_atomic_and_leaves_no_temp(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    repo = SettingsRepository(path)
    repo.save(AppSettings())
    assert path.exists()
    assert list(tmp_path.glob(".*.tmp")) == []


def test_memory_store() -> None:
    store = MemorySettingsStore()
    assert store.load() == AppSettings()

    settings = AppSettings(memo_enabled=False)
    store.save(settings)
    assert store.load() == settings
