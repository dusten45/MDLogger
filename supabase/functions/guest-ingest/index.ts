// Guest Ingest Edge Function (로드맵 8.3, 결정 5·13, 12.3).
//
// - 게스트는 Supabase auth 사용자 없이 이 함수로만 분석용 필드를 업로드한다.
// - 정상 게스트 업로드는 로그인이나 CAPTCHA 없이 동작한다(결정 12).
// - payload 크기·batch 크기 제한과 idempotent batch는 DB 함수와 함께 처리한다.
// - 필드 allowlist(하드닝 H6)를 Edge 계층에서도 적용해 심층 방어를 만든다.
//   DB(0008/0013)의 allowlist와 동일한 키만 통과시킨다.
// - rate limit(하드닝 H5)을 installation pseudonym 단위·IP 단위로 적용한다.
//   임계값(결정 D-4 확정): 각각 1분 창 최대 10회. 게스트 배치 업로드(관찰 1~200건)는
//   1건당 1요청이므로 정상 사용을 방해하지 않는다.
//   Turnstile(challenge)은 여전히 범위 제외로, 남용이 관찰되면 붙인다.
// - service-role key는 서버 환경 변수로만 주입되며 클라이언트에 포함되지 않는다.

import { createClient } from "npm:@supabase/supabase-js@2";

const MAX_BODY_BYTES = 256 * 1024;
const MAX_BATCH_SIZE = 200;
// 1단계 payload v2 (spec §4.5): 클라이언트 GUEST_INGEST_PAYLOAD_VERSION와 정렬한다.
const PAYLOAD_VERSION = 2;
const RATE_WINDOW_MINUTES = 1;
const RATE_MAX_PER_WINDOW = 10;

interface GuestIngestRequest {
    batch_id: string;
    installation_id: string;
    client_version?: string;
    payload_version: number;
    challenge_token?: string;
    observations: unknown[];
}

interface AbuseDecision {
    allowed: boolean;
    challengeRequired: boolean;
    retryAfterSeconds?: number;
}

const UUID_PATTERN =
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// DB 계층(0008/0013)의 허용 키와 정확히 일치한다.
const OBSERVATION_ALLOWED_KEYS: ReadonlySet<string> = new Set([
    "op",
    "sync_id",
    "played_at_local",
    "timezone_offset_minutes",
    "result",
    "turn_order",
    "my_deck",
    "opp_deck",
    "turns",
    "end_reason",
    "play_context_id",
    "standing_kind",
    "rank_tier_before",
    "rank_tier_after",
    "rank_division_before",
    "rank_division_after",
    "rating_before",
    "rating_after",
    "event_points_before",
    "event_points_after",
    "event_id",
    "event_stage_id",
    "environment_version_id",
    "deck_catalog_version_id",
]);

const RESULTS = new Set(["win", "lose"]);
const TURN_ORDERS = new Set(["first", "second"]);
const END_REASONS = new Set(["regular", "surrender", "timeout", "disconnect"]);

function jsonResponse(status: number, body: Record<string, unknown>): Response {
    return new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
    });
}

// 남용 방어 방어 1·4(로드맵 12.3)의 anomaly 값 검사. 배치 전체의 책임은
// 허용 필드와 값 범위 검사가 담당하고, rate limit은 DB 함수로 집합한다.
function validateObservationEnvelope(observations: unknown[]): string | null {
    for (let i = 0; i < observations.length; i += 1) {
        const item = observations[i];
        if (typeof item !== "object" || item === null || Array.isArray(item)) {
            return "observation_not_object";
        }
        const obs = item as Record<string, unknown>;
        for (const key of Object.keys(obs)) {
            if (!OBSERVATION_ALLOWED_KEYS.has(key)) {
                return `disallowed_field:${key}`;
            }
        }
        if (obs.result !== undefined && !RESULTS.has(String(obs.result))) {
            return "invalid_result";
        }
        if (
            obs.turn_order !== undefined &&
            !TURN_ORDERS.has(String(obs.turn_order))
        ) {
            return "invalid_turn_order";
        }
        if (
            obs.end_reason !== undefined &&
            !END_REASONS.has(String(obs.end_reason))
        ) {
            return "invalid_end_reason";
        }
        if (obs.turns !== undefined) {
            const turns = Number(obs.turns);
            if (!Number.isInteger(turns) || turns < 0 || turns > 999) {
                return "invalid_turns";
            }
        }
        if (obs.timezone_offset_minutes !== undefined) {
            const offset = Number(obs.timezone_offset_minutes);
            if (!Number.isInteger(offset) || offset < -1440 || offset > 1440) {
                return "invalid_timezone_offset";
            }
        }
        if (
            obs.environment_version_id !== undefined &&
            obs.environment_version_id !== null &&
            typeof obs.environment_version_id !== "string"
        ) {
            return "invalid_environment_version";
        }
    }
    return null;
}

function validateShape(body: unknown): GuestIngestRequest | string {
    if (typeof body !== "object" || body === null || Array.isArray(body)) {
        return "body_not_object";
    }
    const request = body as Record<string, unknown>;
    if (
        typeof request.batch_id !== "string" ||
        !UUID_PATTERN.test(request.batch_id)
    ) {
        return "invalid_batch_id";
    }
    if (
        typeof request.installation_id !== "string" ||
        !UUID_PATTERN.test(request.installation_id)
    ) {
        return "invalid_installation_id";
    }
    if (request.payload_version !== PAYLOAD_VERSION) {
        return "unsupported_payload_version";
    }
    if (!Array.isArray(request.observations)) {
        return "observations_not_array";
    }
    if (
        request.observations.length < 1 ||
        request.observations.length > MAX_BATCH_SIZE
    ) {
        return "invalid_batch_size";
    }
    const envelopeReason = validateObservationEnvelope(request.observations);
    if (envelopeReason !== null) {
        return envelopeReason;
    }
    return request as unknown as GuestIngestRequest;
}

function checkAbuseGuards(
    _installationId: string,
    _challengeToken: string | undefined,
): AbuseDecision {
    // rate limit은 DB 함수 `guest_rate_check`로 적용한다(H5). 428 challenge는
    // Turnstile 도입 전이라 항상 통과(결정 12).
    return { allowed: true, challengeRequired: false };
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

    const request = validateShape(parsed);
    if (typeof request === "string") {
        return jsonResponse(422, { code: request });
    }

    const decision = checkAbuseGuards(
        request.installation_id,
        request.challenge_token,
    );
    if (decision.challengeRequired) {
        return jsonResponse(428, { code: "challenge_required" });
    }

    const supabase = createClient(
        Deno.env.get("SUPABASE_URL")!,
        Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
        { auth: { persistSession: false } },
    );

    // H5: installation pseudonym·IP 슬라이딩 창 rate limit. 허용치 초과 시 429.
    const forwarded =
        (req.headers.get("x-forwarded-for") ?? "").split(",")[0] ?? "";
    const ip = forwarded.trim();
    const { data: rateData, error: rateError } = await supabase.rpc(
        "guest_rate_check",
        {
            installation_id: request.installation_id,
            ip,
            window_minutes: RATE_WINDOW_MINUTES,
            max_per_window: RATE_MAX_PER_WINDOW,
        },
    );
    if (rateError) {
        console.error("guest rate check failed", { code: rateError.code });
        return jsonResponse(500, { code: "rate_check_failed" });
    }
    const rateDecided = rateData as {
        allowed?: boolean;
        retry_after_seconds?: number;
    } | null;
    if (!rateDecided?.allowed) {
        return jsonResponse(429, {
            code: "rate_limited",
            retry_after_seconds: rateDecided?.retry_after_seconds ?? 60,
        });
    }

    const { data, error } = await supabase.rpc("ingest_guest_batch", {
        batch_id: request.batch_id,
        installation_id: request.installation_id,
        client_version: request.client_version ?? null,
        payload_version: request.payload_version,
        observations: request.observations,
    });

    if (error) {
        if (error.code === "22023") {
            return jsonResponse(422, {
                code: "invalid_payload",
                detail: error.message,
            });
        }
        console.error("guest-ingest failed", { code: error.code });
        return jsonResponse(500, { code: "ingest_failed" });
    }

    return jsonResponse(200, data as Record<string, unknown>);
});
