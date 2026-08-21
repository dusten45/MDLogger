// Cloudflare 배포 전에 웹앱이 동작할 최소 환경 변수를 확인한다.
// service-role key 등 secret 값은 빌드 후 check-secrets가 추가로 차단한다.

const required = ["VITE_SUPABASE_URL", "VITE_SUPABASE_ANON_KEY"];
const missing = required.filter((name) => !process.env[name]?.trim());

if (missing.length > 0) {
  console.error(`FAIL: 필요한 환경 변수가 없습니다: ${missing.join(", ")}`);
  process.exit(1);
}

try {
  const url = new URL(process.env.VITE_SUPABASE_URL);
  if (url.protocol !== "https:" || url.username || url.password) {
    throw new Error();
  }
} catch {
  console.error(
    "FAIL: VITE_SUPABASE_URL은 자격 증명이 없는 HTTPS Supabase project URL이어야 합니다.",
  );
  process.exit(1);
}

console.log("OK: deployment environment");
