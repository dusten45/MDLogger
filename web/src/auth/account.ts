// 계정 운영 (spec §3.5, §6): 내보내기·모든 기기 로그아웃·계정 삭제.
// service-role key는 사용하지 않는다. 모든 호출은 사용자 access token으로 수행한다.

import { getSupabaseClient } from "../lib/supabase";

export interface AccountExport {
  user_id: string;
  exported_at: string;
  profile: unknown;
  games: unknown[];
  devices: unknown[];
}

export async function exportAccountData(): Promise<AccountExport> {
  const { data, error } = await getSupabaseClient().rpc("export_account_data");
  if (error) {
    throw error;
  }
  return data as AccountExport;
}

export async function revokeAllSessions(): Promise<void> {
  const { error } = await getSupabaseClient().functions.invoke("revoke-sessions", {
    method: "POST",
    body: {},
  });
  if (error) {
    throw error;
  }
}

export async function deleteAccount(): Promise<void> {
  const { error } = await getSupabaseClient().functions.invoke("account-delete", {
    method: "POST",
    body: {},
  });
  if (error) {
    throw error;
  }
}

export function downloadAccountExport(data: AccountExport): void {
  const blob = new Blob([JSON.stringify(data, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `mdlogger-export-${data.user_id}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}
