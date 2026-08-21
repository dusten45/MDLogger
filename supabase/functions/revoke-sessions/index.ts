// Revoke Sessions Edge Function (하드닝 D-6, "모든 기기에서 로그아웃" 실제 세션 폐기).
//
// 배경: `revoke_all_devices` RPC는 `public.devices` 행만 삭제할 뿐 GoTrue
// 활성 세션·refresh token을 폐기하지 않는다. 이 함수는 인증된 사용자 본인의
// **모든 세션/refresh token을 실제로 폐기**하고, 등록된 장치 행도 함께 정리한다.
//
// 보안 요점:
//   * 클라이언트는 service-role key나 관리자 자격 증명을 전혀 갖지 않는다.
//     클라이언트가 보내는 것은 자신의 access token(JWT)뿐이다.
//   * 게이트웨이 `verify_jwt=true` + 함수 내 `getUser` 재검증(방어심도, R11-1).
//     base64 디코딩만으로 sub를 신뢰하면 --no-verify-jwt 로컬 서브나 직접 호출에서
//     남의 세션을 폐기할 수 있다(P0-4 패턴).
//   * GoTrue Admin 로그아웃(`admin.auth.admin.signOut`)은 사용자 ID가 아니라
//     **요청자 본인의 JWT**만 받는다. 따라서 이 함수는 구조적으로 자기 세션만
//     폐기할 수 있고, 다른 사용자의 세션은 건드릴 방법이 없다(교차 사용자 공격 차단).
//   * scope='global'은 요청자 계정의 **모든 기기 세션을 폐기**한다. access token
//     (JWT)은 만료 전까지 무효화할 수 없으나 refresh token이 즉시 제거되므로
//     유효 기간이 끝나면 재로그인해야 한다(D-6 목표).
//   * service-role key는 오직 서버 환경 변수에만 존재한다. 로그·응답·코드에
//     절대 노출하지 않는다. 인증 토큰도 로그에 남기지 않고 오류 코드만 기록한다.
//   * 파괴적 경로이므로 메서드(POST)와 요청 크기만 엄격히 허용한다.

import { createClient } from "npm:@supabase/supabase-js@2";

const MAX_BODY_BYTES = 512;

const corsHeaders: Record<string, string> = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers":
        "authorization, x-client-info, apikey, content-type",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
};

function jsonResponse(status: number, body: Record<string, unknown>): Response {
    return new Response(JSON.stringify(body), {
        status,
        headers: {
            ...corsHeaders,
            "Content-Type": "application/json",
        },
    });
}

Deno.serve(async (req: Request): Promise<Response> => {
    if (req.method === "OPTIONS") {
        return new Response("ok", { headers: corsHeaders });
    }

    if (req.method !== "POST") {
        return jsonResponse(405, { code: "method_not_allowed" });
    }

    const rawBody = await req.text();
    if (rawBody.length > MAX_BODY_BYTES) {
        return jsonResponse(413, { code: "payload_too_large" });
    }

    const authHeader = req.headers.get("Authorization") ?? "";
    const token = authHeader.replace(/^Bearer\s+/i, "").trim();
    if (!token) {
        return jsonResponse(401, { code: "unauthorized" });
    }

    const supabase = createClient(
        Deno.env.get("SUPABASE_URL")!,
        Deno.env.get("SUPABASE_ANON_KEY")!,
        { auth: { persistSession: false } },
    );

    // 서명·exp·aud를 GoTrue가 검증한 사용자로 요청자를 확정한다(방어심도, R11-1).
    const { data: userData, error: userError } =
        await supabase.auth.getUser(token);
    if (userError || !userData?.user) {
        return jsonResponse(401, { code: "unauthorized" });
    }
    const subject = userData.user.id;

    // 1) 요청자 본인의 모든 세션/refresh token을 폐기한다(scope='global').
    //    실패하면 다른 변경 없이 중단한다(fail-closed).
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
    const { error: signOutError } = await admin.auth.admin.signOut(
        token,
        "global",
    );
    if (signOutError) {
        console.error("admin signOut failed", {
            user_id: subject,
            code: signOutError.code,
        });
        return jsonResponse(500, { code: "session_revocation_failed" });
    }

    // 2) 요청자의 등록 장치 행을 정리한다(장치 목록). 호출자 JWT는 여전히 유효하므로
    //    `revoke_all_devices`가 auth.uid()=요청자로 동작한다. 실패해도 세션 폐기는
    //    이미 성공했고 재로그인 시 장치는 재등록되므로, 폐기 결과를 막지 않는다
    //    (account-delete의 cleanup과 동일한 best-effort 패턴).
    const deviceClient = createClient(
        Deno.env.get("SUPABASE_URL")!,
        Deno.env.get("SUPABASE_ANON_KEY")!,
        {
            auth: { persistSession: false },
            global: {
                headers: {
                    apikey: Deno.env.get("SUPABASE_ANON_KEY")!,
                    Authorization: `Bearer ${token}`,
                },
            },
        },
    );
    const { data: rpcData, error: rpcError } =
        await deviceClient.rpc("revoke_all_devices");
    if (rpcError) {
        console.warn("revoke_all_devices cleanup failed", {
            user_id: subject,
            code: rpcError.code,
        });
        return jsonResponse(200, {
            code: "sessions_revoked",
            revoked_devices: 0,
            note: "revoke_all_devices cleanup skipped; sessions were revoked",
        });
    }

    const revokedDevices =
        typeof rpcData === "object" &&
        rpcData !== null &&
        "revoked_devices" in rpcData
            ? Number((rpcData as Record<string, unknown>).revoked_devices) || 0
            : 0;

    return jsonResponse(200, {
        code: "sessions_revoked",
        revoked_devices: revokedDevices,
    });
});
