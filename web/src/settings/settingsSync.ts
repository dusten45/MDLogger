// 취향 설정 수동 동기화 (spec §4, §8.3). 게임 동기화처럼 자동 push/pull이 아니다.
// `PREFERENCE_KEYS`만 직렬화·전송하고 `DEVICE_KEYS`는 어떤 경로로도 전송하지
// 않는다(클라이언트 하드 차단). 서버 `upsert_user_settings`(0026)가 같은
// allowlist를 검증한다.

import { getSupabaseClient } from "../lib/supabase";
import {
  PREFERENCE_KEYS,
  type WebSettings,
} from "./webSettings";

export type PreferencePatch = Partial<
  Pick<WebSettings, (typeof PREFERENCE_KEYS)[number]>
>;

function extractPreferences(settings: WebSettings): PreferencePatch {
  const preferences: Record<string, unknown> = {};
  for (const key of PREFERENCE_KEYS) {
    preferences[key] = settings[key];
  }
  return preferences as PreferencePatch;
}

export async function uploadPreferences(
  settings: WebSettings,
): Promise<void> {
  const { error } = await getSupabaseClient().rpc("upsert_user_settings", {
    preferences: extractPreferences(settings),
  });
  if (error) {
    throw error;
  }
}

/** 서버 설정에서 `PREFERENCE_KEYS`만 취한다. 행이 없으면 null. */
export async function downloadPreferences(): Promise<PreferencePatch | null> {
  const { data, error } = await getSupabaseClient()
    .from("user_settings")
    .select("preferences");
  if (error) {
    throw error;
  }
  const rows = data as { preferences: unknown }[] | null;
  if (!Array.isArray(rows) || rows.length === 0) {
    return null;
  }
  const preferences = rows[0].preferences;
  if (
    typeof preferences !== "object" ||
    preferences === null ||
    Array.isArray(preferences)
  ) {
    return null;
  }
  const patch: Record<string, unknown> = {};
  for (const key of PREFERENCE_KEYS) {
    if (key in preferences) {
      patch[key] = (preferences as Record<string, unknown>)[key];
    }
  }
  return patch as PreferencePatch;
}
