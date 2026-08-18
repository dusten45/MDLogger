// 환경 변수 접근 (Vite `import.meta.env`, spec §5.1).
// publishable(anon) 값만 존재한다. service-role key는 번들에 포함하지 않는다.

export function getSupabaseUrl(): string {
  const url = import.meta.env.VITE_SUPABASE_URL;
  if (!url) {
    throw new Error("VITE_SUPABASE_URL이 설정되지 않았습니다.");
  }
  return url;
}

export function getSupabaseAnonKey(): string {
  const key = import.meta.env.VITE_SUPABASE_ANON_KEY;
  if (!key) {
    throw new Error("VITE_SUPABASE_ANON_KEY가 설정되지 않았습니다.");
  }
  return key;
}
