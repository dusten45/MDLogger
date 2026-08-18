// Supabase 브라우저 클라이언트 (spec §6, P12).
// 로그인 상태 유지(persistSession)를 켠다. service-role key는 사용하지 않는다.

import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { getSupabaseAnonKey, getSupabaseUrl } from "./env";

let client: SupabaseClient | null = null;

export function getSupabaseClient(): SupabaseClient {
    if (client === null) {
        client = createClient(getSupabaseUrl(), getSupabaseAnonKey(), {
            auth: {
                persistSession: true,
                autoRefreshToken: true,
                detectSessionInUrl: true,
                flowType: "pkce",
            },
        });
    }
    return client;
}
