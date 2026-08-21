// Account Delete Edge Function (로드맵 단계 11, 결정 4, 검토 게이트 R11-1,
// 하드닝 H-4/H-9).
//
// - 데스크톱 클라이언트는 service-role key나 관리자 자격 증명을 전혀 갖지
//   않는다. 클라이언트가 보내는 것은 자신의 access token(JWT)뿐이다.
// - 이 함수는 JWT를 검증해 대상 사용자를 확인하고, service_role 자격으로
//   auth 사용자와 모든 세션/refresh token을 폐기하고 개인 데이터를 정리한다.
// - 하드닝 H-4(원자성): **auth 사용자 삭제를 먼저** 수행한다. `public.games`,
//   `devices`, `profiles`, `game_change_cursors`는 모두 `auth.users (id) on
//   delete cascade`이므로 FK cascade가 개인 데이터를 함께 정리한다. auth 삭제가
//   실패하면 아무것도 삭제되지 않아 복구 가능한 상태가 유지된다(개인 데이터만
//   지워지고 빈 계정이 남는 비원자 상태가 생기지 않는다).
// - 분석용 duel_observations는 0006의 계약대로 보존된다(계정 삭제는 듀얼 기록
//   철회가 아니므로 withdrawn_at을 설정하지 않는다, 로드맵 9.3).
// - 요청한 사용자와 대상 사용자가 일치해야만 삭제를 수행한다.

import { createClient, SupabaseClient } from "npm:@supabase/supabase-js@2";

const MAX_BODY_BYTES = 4 * 1024;

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

interface DeleteCounts {
    games: number;
    devices: number;
    profiles: number;
}

// cascade 전에 응답용 개수 스냅샷을 남긴다.
async function captureCounts(
    client: SupabaseClient,
    subject: string,
): Promise<DeleteCounts> {
    const [gamesRes, devicesRes, profilesRes] = await Promise.all([
        client
            .from("games")
            .select("id", { count: "exact", head: true })
            .eq("user_id", subject),
        client
            .from("devices")
            .select("id", { count: "exact", head: true })
            .eq("user_id", subject),
        client
            .from("profiles")
            .select("id", { count: "exact", head: true })
            .eq("id", subject),
    ]);
    return {
        games: gamesRes.count ?? 0,
        devices: devicesRes.count ?? 0,
        profiles: profilesRes.count ?? 0,
    };
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
    const requestedUserId =
        typeof body.user_id === "string" ? body.user_id : null;

    const authHeader = req.headers.get("Authorization") ?? "";
    const token = authHeader.replace(/^Bearer\s+/i, "").trim();
    if (!token) {
        return jsonResponse(401, { code: "unauthorized" });
    }

    const supabase = createClient(
        Deno.env.get("SUPABASE_URL")!,
        Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
        { auth: { persistSession: false } },
    );

    // 서명·exp·aud를 GoTrue가 검증한 사용자로 요청자를 확정한다(방어심도, R11-1).
    // base64 디코딩만으로 sub를 신뢰하면 --no-verify-jwt 로컬 서브나 직접 호출에서
    // 임의의 sub로 남의 계정을 삭제할 수 있다(P0-4).
    const { data: userData, error: userError } =
        await supabase.auth.getUser(token);
    if (userError || !userData?.user) {
        return jsonResponse(401, { code: "unauthorized" });
    }
    const subject = userData.user.id;

    if (requestedUserId !== null && requestedUserId !== subject) {
        return jsonResponse(403, { code: "target_mismatch" });
    }

    const counts = await captureCounts(supabase, subject);

    // 1) auth 사용자와 모든 세션/refresh token 폐기. 성공하면 FK cascade로
    //    개인 데이터(profiles/games/devices/game_change_cursors)가 함께 삭제된다.
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
        // 다운트림 체크는 fail-closed: auth 삭제 실패 시 아무것도 삭제되지 않아
        // 복구 가능한 상태가 유지된다. 재시도는 deleteUser를 멱등하게 처리한다.
        console.error("admin deleteUser failed", { code: deleteError.code });
        return jsonResponse(500, { code: "delete_user_failed" });
    }

    // 2) cascade 누락 방지용 멱등 정리(서비스 유지 관점 best-effort). 분석
    //    observation은 계약대로 건드리지 않는다.
    const { error: cleanupError } = await supabase.rpc("delete_account_data", {
        target_user: subject,
    });
    if (cleanupError) {
        console.warn("delete_account_data cleanup failed", {
            code: cleanupError.code,
        });
        return jsonResponse(200, {
            code: "account_deleted",
            user_id: subject,
            ...counts,
            deleted_auth_user: deletedUser?.id ?? subject,
            note: "delete_account_data cleanup skipped; FK cascade already removed personal data",
        });
    }

    return jsonResponse(200, {
        code: "account_deleted",
        user_id: subject,
        ...counts,
        deleted_auth_user: deletedUser?.id ?? subject,
    });
});
