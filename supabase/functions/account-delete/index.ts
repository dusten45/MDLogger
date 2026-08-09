// Account Delete Edge Function (로드맵 단계 11, 결정 4, 검토 게이트 R11-1).
//
// - 데스크톱 클라이언트는 service-role key나 관리자 자격 증명을 전혀 갖지
//   않는다. 클라이언트가 보내는 것은 자신의 access token(JWT)뿐이다.
// - 이 함수는 JWT를 검증해 대상 사용자를 확인하고, service_role 자격으로
//   (1) public.delete_account_data(target_user)를 호출해 개인 데이터
//   (profiles, games, devices)를 삭제하고,
//   (2) Auth Admin API로 auth 사용자와 모든 세션/refresh token을 폐기한다.
// - 분석용 duel_observations는 0006의 계약대로 보존된다. 계정 삭제는 듀얼
//   기록 철회가 아니므로 withdrawn_at을 설정하지 않는다(로드맵 9.3).
// - 요청한 사용자와 대상 사용자가 일치해야만 삭제를 수행한다.

import { createClient } from "npm:@supabase/supabase-js@2";

const MAX_BODY_BYTES = 4 * 1024;

function jsonResponse(status: number, body: Record<string, unknown>): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

// JWT 페이로드 중 sub(사용자 UUID)를 추출한다. 서명 검증은 Supabase 게이트웨이가
// Authorization 헤더의 유효한 사용자 JWT로 이미 수행한다.
function subjectFromCtx(ctx: unknown): string | null {
  if (typeof ctx !== "object" || ctx === null) return null;
  const record = ctx as Record<string, unknown>;
  const sub = record.sub;
  return typeof sub === "string" && sub.length > 0 ? sub : null;
}

Deno.serve(async (req: Request): Promise<Response> => {
  if (req.method !== "POST") {
    return jsonResponse(405, { code: "method_not_allowed" });
  }

  const rawBody = await req.text();
  if (rawBody.length > MAX_BODY_BYTES) {
    return jsonResponse(413, { code: "payload_too_large" });
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(rawBody);
  } catch {
    return jsonResponse(400, { code: "invalid_json" });
  }

  const body =
    typeof parsed === "object" && parsed !== null
      ? (parsed as Record<string, unknown>)
      : {};
  const requestedUserId = typeof body.user_id === "string" ? body.user_id : null;

  // Authorization 헤더의 JWT를 디코딩해 sub(사용자 UUID)를 얻는다. 서명 검증은
  // Supabase 게이트웨이가 유효한 사용자 JWT에 대해 이미 수행한 상태다.
  const authHeader = req.headers.get("Authorization") ?? "";
  const token = authHeader.replace(/^Bearer\s+/i, "").trim();
  if (!token) {
    return jsonResponse(401, { code: "unauthorized" });
  }
  const payload = token.split(".")[1];
  if (!payload) {
    return jsonResponse(401, { code: "unauthorized" });
  }
  let decoded: unknown;
  try {
    decoded = JSON.parse(atob(payload.replace(/-/g, "+").replace(/_/g, "/")));
  } catch {
    return jsonResponse(401, { code: "unauthorized" });
  }
  const subject = subjectFromCtx(decoded);
  if (subject === null) {
    return jsonResponse(401, { code: "unauthorized" });
  }

  if (requestedUserId !== null && requestedUserId !== subject) {
    // 대상 사용자가 요청자와 다르면 거부한다. 권한 있는 사용자도 자기 외
    // 계정을 삭제할 수 없다(관리자 해제는 별도 절차).
    return jsonResponse(403, { code: "target_mismatch" });
  }

  const supabase = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
    { auth: { persistSession: false } },
  );

  // 1) 개인 데이터 삭제(service_role 전용 함수).
  const { data, error } = await supabase.rpc("delete_account_data", {
    target_user: subject,
  });
  if (error) {
    console.error("delete_account_data failed", { code: error.code });
    return jsonResponse(500, { code: "delete_data_failed" });
  }

  // 2) Auth Admin API로 auth 사용자와 모든 세션/refresh token 폐기.
  const admin = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
    {
      auth: {
        autoRefreshToken: false,
        persistSession: false,
      },
      global: {
        headers: {
          Authorization: `Bearer ${Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")}`,
        },
      },
    },
  );
  const { data: deletedUser, error: deleteError } =
    await admin.auth.admin.deleteUser(subject);
  if (deleteError) {
    // 개인 데이터는 이미 삭제됐지만 auth 사용자 삭제에 실패했다. 진단을 남기고
    // 500을 돌려준다. 재시도는 deleteUser를 멱등하게 처리하도록 한다.
    console.error("admin deleteUser failed", { code: deleteError.code });
    return jsonResponse(500, { code: "delete_user_failed" });
  }

  return jsonResponse(200, {
    code: "account_deleted",
    user_id: subject,
    deleted_games: (data as Record<string, unknown> | null)?.["deleted_games"] ?? 0,
    deleted_devices:
      (data as Record<string, unknown> | null)?.["deleted_devices"] ?? 0,
    deleted_profiles:
      (data as Record<string, unknown> | null)?.["deleted_profiles"] ?? 0,
    deleted_auth_user: deletedUser?.id ?? subject,
  });
});
