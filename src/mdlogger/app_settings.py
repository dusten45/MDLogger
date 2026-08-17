"""기기 전역 앱 설정 모델·검증·저장소 (계획 2, spec §2~§3).

프로필과 무관한 기기 전역 설정만 담는다. ``default_mode``/``last_used_mode``는
모드 id를 참조하므로 프로필 범위라 여기에 두지 않는다(spec §1.2, ``ModeSettings``).

설정은 기본적으로 기기 로컬이며, ``settings.json``(버전 있는 JSON)으로 원자적으로
저장한다. 동기화 대상은 ``PREFERENCE_KEYS``(취향 설정)뿐이고 ``DEVICE_KEYS``(기기
특성)는 어떤 경로로도 직렬화·전송하지 않는다(spec §1.1, §4.1).
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from .paths import SETTINGS_PATH
from .ui.theme import ThemeMode

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

# 동기화(취향 설정) allowlist. ``default_mode``는 프로필 DB에 저장되지만 취향
# 설정으로 동기화에 포함한다(spec §1.2, §4.1).
PREFERENCE_KEYS = ("theme_mode", "accent_color", "memo_enabled", "default_mode")
# 기기 특성 설정. 어떤 경로로도 직렬화·전송하지 않는다(클라이언트/서버 하드 차단).
DEVICE_KEYS = ("font_scale", "low_spec_mode", "reduce_motion")


class AccentPreset(StrEnum):
    """검증된 강조색 프리셋 id (spec §2.2)."""

    BLUE = "blue"
    INDIGO = "indigo"
    TEAL = "teal"
    MAGENTA = "magenta"
    AMBER = "amber"


class ReduceMotion(StrEnum):
    """애니메이션 감소 설정 (spec §2.2)."""

    SYSTEM = "system"
    OFF = "off"
    ON = "on"


@dataclass(frozen=True, slots=True)
class AppSettings:
    """기기 전역 설정 값 (spec §2.1)."""

    theme_mode: ThemeMode = ThemeMode.SYSTEM
    accent_color: str = AccentPreset.BLUE.value
    font_scale: float = 1.0  # 0.8 ~ 1.5
    low_spec_mode: bool = False
    reduce_motion: ReduceMotion = ReduceMotion.SYSTEM
    memo_enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        """버전 있는 JSON 직렬화 형식으로 변환한다(spec §3.1)."""
        return {
            "schema_version": SCHEMA_VERSION,
            "theme_mode": self.theme_mode.value,
            "accent_color": self.accent_color,
            "font_scale": self.font_scale,
            "low_spec_mode": self.low_spec_mode,
            "reduce_motion": self.reduce_motion.value,
            "memo_enabled": self.memo_enabled,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AppSettings:
        """손상된 단일 필드를 기본값으로 대체해 복원한다(spec §2.3)."""
        return cls(
            theme_mode=_parse_theme_mode(data.get("theme_mode")),
            accent_color=_parse_accent(data.get("accent_color")),
            font_scale=_parse_font_scale(data.get("font_scale")),
            low_spec_mode=_parse_bool(data.get("low_spec_mode"), False),
            reduce_motion=_parse_reduce_motion(data.get("reduce_motion")),
            memo_enabled=_parse_bool(data.get("memo_enabled"), True),
        )


def _parse_theme_mode(value: Any) -> ThemeMode:
    if isinstance(value, str):
        try:
            return ThemeMode(value)
        except ValueError:
            pass
    return ThemeMode.SYSTEM


def _parse_accent(value: Any) -> str:
    if isinstance(value, str) and value in {preset.value for preset in AccentPreset}:
        return value
    return AccentPreset.BLUE.value


def _parse_font_scale(value: Any) -> float:
    if isinstance(value, bool):
        return 1.0
    if isinstance(value, (int, float)):
        scale = float(value)
        if 0.8 <= scale <= 1.5:
            return scale
    return 1.0


def _parse_reduce_motion(value: Any) -> ReduceMotion:
    if isinstance(value, str):
        try:
            return ReduceMotion(value)
        except ValueError:
            pass
    return ReduceMotion.SYSTEM


def _parse_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    return default


def effective_reduce_motion(settings: AppSettings) -> bool:
    """실제 애니메이션 감소 여부 (spec §3.3, §5.3).

    저사양 모드 on이면 애니메이션을 강제로 끈다. 사용자의 ``reduce_motion`` 개별값은
    보존되어 저사양 모드를 끄면 복원된다. ``ReduceMotion.SYSTEM``은 초기에는
    ``off``와 동일하게 취급한다(spec §10-5).
    """
    return settings.reduce_motion is ReduceMotion.ON or settings.low_spec_mode


class SettingsStore(Protocol):
    """설정 저장소 계약 (파일/메모리 구현 공통)."""

    def load(self) -> AppSettings: ...

    def save(self, settings: AppSettings) -> None: ...


class SettingsRepository:
    """``settings.json`` 파일 기반 저장소 (spec §3.2).

    - ``load``: 파일 없음/JSON 파싱 실패/스키마 불일치는 기본값(비차단, 로그만).
      단일 필드 손상은 ``AppSettings.from_dict`` 검증으로 기본값 대체.
    - ``save``: 임시 파일에 쓰고 ``os.replace``로 원자적 교체. 실패는 조용히 무시
      (설정 저장 실패가 앱 동작을 막지 않음).
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path if path is not None else SETTINGS_PATH

    def load(self) -> AppSettings:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except OSError:
            return AppSettings()
        data = _parse_json(raw)
        if data is None:
            logger.warning(
                "설정 파일을 해석할 수 없어 기본값을 사용합니다: %s", self._path
            )
            return AppSettings()
        if data.get("schema_version") != SCHEMA_VERSION:
            logger.warning(
                "지원하지 않는 설정 스키마(%s)라 기본값을 사용합니다.",
                data.get("schema_version"),
            )
            return AppSettings()
        return AppSettings.from_dict(data)

    def save(self, settings: AppSettings) -> None:
        payload = json.dumps(settings.to_dict(), ensure_ascii=False, indent=2)
        temporary = self._path.with_name(f".{self._path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(payload, encoding="utf-8")
            if os.name != "nt":
                temporary.chmod(0o600)
            os.replace(temporary, self._path)
        except OSError:
            logger.warning("설정 저장에 실패했습니다: %s", self._path, exc_info=True)
        finally:
            temporary.unlink(missing_ok=True)


class MemorySettingsStore:
    """테스트용 인메모리 저장소 (spec §3.2)."""

    def __init__(self, initial: AppSettings | None = None) -> None:
        self._settings = initial

    def load(self) -> AppSettings:
        return self._settings if self._settings is not None else AppSettings()

    def save(self, settings: AppSettings) -> None:
        self._settings = settings


def _parse_json(raw: str) -> dict[str, Any] | None:
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None
