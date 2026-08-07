// Guest Ingest Edge Function (로드맵 8.3, 결정 5·13).
//
// - 게스트는 Supabase auth 사용자 없이 이 함수로만 분석용 필드를 업로드한다.
// - 정상 게스트 업로드는 로그인이나 CAPTCHA 없이 동작한다(결정 12).
// - payload 크기·batch 크기 제한과 idempotent batch는 DB 함수와 함께 처리한다.
// - rate limit·이상 탐지·Turnstile은 `checkAbuseGuards` 확장 경계에 나중에
//   추가한다. challenge가 필요하면 428 + {"code":"challenge_required"}를
//   돌려주는 응답 계약만 여기서 확정한다.
// - service-role key는 서버 환경 변수로만 주입되며 클라이언트에 포함되지 않는다.

import { createClient } from "npm:@supabase/supabase-js@2";

const MAX_BODY_BYTES = 256 * 1024;
const MAX_BATCH_SIZE = 200;
const PAYLOAD_VERSION = 1;

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

function jsonResponse(status: number, body: Record<string, unknown>): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

// 남용 방어 확장 경계. 초기 릴리스는 통과시키고, 실제 남용이 관찰되면
// installation pseudonym/IP 단기 rate limit과 이상 탐지, 의심 요청 한정
// Turnstile 검증을 이 함수에 추가한다(로드맵 12.3).
function checkAbuseGuards(
  _installationId: string,
  _challengeToken: string | undefined,
): AbuseDecision {
  return { allowed: true, challengeRequired: false };
}

function validateShape(body: unknown): GuestIngestRequest | string {
  if (typeof body !== "object" || body === null || Array.isArray(body)) {
    return "body_not_object";
  }
  const request = body as Record<string, unknown>;
  if (typeof request.batch_id !== "string" || !UUID_PATTERN.test(request.batch_id)) {
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
  return request as unknown as GuestIngestRequest;
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
  if (!decision.allowed) {
    return jsonResponse(429, {
      code: "rate_limited",
      retry_after_seconds: decision.retryAfterSeconds ?? 60,
    });
  }

  const supabase = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
    { auth: { persistSession: false } },
  );

  const { data, error } = await supabase.rpc("ingest_guest_batch", {
    batch_id: request.batch_id,
    installation_id: request.installation_id,
    client_version: request.client_version ?? null,
    payload_version: request.payload_version,
    observations: request.observations,
  });

  if (error) {
    // 22023: 함수 수준의 payload 계약 위반 → 클라이언트 오류로 구분한다.
    if (error.code === "22023") {
      return jsonResponse(422, { code: "invalid_payload", detail: error.message });
    }
    console.error("guest-ingest failed", { code: error.code });
    return jsonResponse(500, { code: "ingest_failed" });
  }

  return jsonResponse(200, data as Record<string, unknown>);
});
