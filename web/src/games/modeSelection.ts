// 시작 시 기본 모드 결정 + 마지막 사용 모드 기억 (데스크톱 `db.py`의
// resolve_default_mode_id와 동일한 의미, spec §1.1).
//
// 웹은 프로필 DB가 없으므로 `last_used_mode`를 localStorage에 둔다(동기화 대상
// 아님). `default_mode`는 설정(localStorage, 취향 설정)에서 온다.

import type { GameMode } from "./types";

const LAST_USED_KEY = "mdlogger.last_used_mode";

export function getLastUsedModeId(): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    return window.localStorage.getItem(LAST_USED_KEY);
  } catch {
    return null;
  }
}

export function setLastUsedModeId(modeId: string): void {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(LAST_USED_KEY, modeId);
  } catch {
    // 선택적 취향 저장 실패는 이미 확인된 경기 저장 성공을 바꾸지 않는다.
  }
}

/**
 * 시작 시 사용할 모드 id를 결정한다.
 * - defaultMode가 특정 모드면 그 모드
 * - 'last_used'(또는 빈 값)면 lastUsedModeId
 * - 둘 다 없거나 비활성이면 첫 활성 모드
 * - 활성 모드가 없으면 null
 */
export function resolveInitialModeId(
  modes: GameMode[],
  defaultMode: string,
  lastUsedModeId: string | null,
): string | null {
  if (modes.length === 0) {
    return null;
  }
  if (defaultMode && defaultMode !== "last_used") {
    const match = modes.find((mode) => mode.id === defaultMode);
    if (match) {
      return match.id;
    }
  }
  if (lastUsedModeId) {
    const match = modes.find((mode) => mode.id === lastUsedModeId);
    if (match) {
      return match.id;
    }
  }
  return modes[0].id;
}
