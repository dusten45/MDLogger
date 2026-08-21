// Deck Catalog Edge Function (3단계, spec §3.6, 로드맵 17.6).
//
// - 브라우저는 Gist를 직접 요청하지 않는다. 이 함수가 proxy한다.
// - 서버 전용 캐시 테이블(0027)에 마지막 정상 덱 JSON, Gist ETag, 확인/변경 시각,
//   content hash를 보존한다.
// - 조회 흐름: TTL(5분) 안이면 캐시 반환 → 지났으면 If-None-Match 재검증 →
//   304면 확인 시각 갱신 → 변경 시 배열/크기/문자열 검증 후 원자 교체 →
//   Gist 실패 시 마지막 정상 캐시(stale) 반환 → 캐시도 없으면 503.
// - 공백 제거·중복 제거·"기타" 포함을 보장한다.
// - 호출은 로그인 access token을 요구한다(무분별한 proxy 사용 방지).

import { createClient, type SupabaseClient } from "npm:@supabase/supabase-js@2";

const TTL_MS = 5 * 60 * 1000;
const MAX_DECKS = 500;
const MAX_DECK_LENGTH = 200;
const OTHER = "기타";
const DEFAULT_GIST_URL =
  "https://gist.githubusercontent.com/dusten45/f7c427c57a0842f05cf8b2e3aeb011c3/raw/decks.json";

interface CacheRow {
  id: number;
  decks: string[];
  etag: string | null;
  source_url: string;
  content_hash: string;
  last_checked_at: string;
  last_changed_at: string;
  updated_at: string;
}

const corsHeaders: Record<string, string> = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
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

async function sha256(text: string): Promise<string> {
  const data = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

// 공백 제거·중복 제거·"기타" 포함을 보장한다. 손상(비배열/비문자열/과대)은 null.
function normalizeDecks(raw: unknown): string[] | null {
  if (!Array.isArray(raw)) {
    return null;
  }
  const seen = new Set<string>();
  const out: string[] = [];
  for (const item of raw) {
    if (typeof item !== "string") {
      return null;
    }
    const trimmed = item.trim();
    if (!trimmed) {
      continue;
    }
    if (trimmed.length > MAX_DECK_LENGTH) {
      return null;
    }
    if (!seen.has(trimmed)) {
      seen.add(trimmed);
      out.push(trimmed);
    }
  }
  if (out.length > MAX_DECKS) {
    return null;
  }
  if (!out.includes(OTHER)) {
    out.push(OTHER);
  }
  return out;
}

function staleOr503(cacheRow: CacheRow | null): Response {
  if (cacheRow) {
    return jsonResponse(200, {
      decks: cacheRow.decks,
      stale: true,
      source: "stale",
      updated_at: cacheRow.last_changed_at,
    });
  }
  return jsonResponse(503, { code: "deck_catalog_unavailable" });
}

Deno.serve(async (req: Request): Promise<Response> => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  if (req.method !== "GET" && req.method !== "POST") {
    return jsonResponse(405, { code: "method_not_allowed" });
  }

  // 로그인 access token 요구(무분별한 proxy 사용 방지).
  const authHeader = req.headers.get("Authorization") ?? "";
  const token = authHeader.replace(/^Bearer\s+/i, "").trim();
  if (!token) {
    return jsonResponse(401, { code: "unauthorized" });
  }

  const supabase: SupabaseClient = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
    { auth: { persistSession: false } },
  );

  const { data: userData, error: userError } = await supabase.auth.getUser(token);
  if (userError || !userData?.user) {
    return jsonResponse(401, { code: "unauthorized" });
  }

  const { data: cacheRow, error: cacheError } = await supabase
    .from("deck_catalog_cache")
    .select("*")
    .eq("id", 1)
    .maybeSingle();
  if (cacheError) {
    console.error("deck cache read failed", { code: cacheError.code });
    return jsonResponse(500, { code: "cache_read_failed" });
  }

  const now = Date.now();
  const gistUrl = Deno.env.get("DECK_GIST_URL") ?? DEFAULT_GIST_URL;

  // TTL 안이면 캐시 반환.
  if (cacheRow) {
    const lastChecked = new Date(cacheRow.last_checked_at).getTime();
    if (now - lastChecked < TTL_MS) {
      return jsonResponse(200, {
        decks: cacheRow.decks,
        stale: false,
        source: "cache",
        updated_at: cacheRow.last_changed_at,
      });
    }
  }

  // TTL 지남: If-None-Match 재검증.
  const headers: Record<string, string> = {};
  if (cacheRow?.etag) {
    headers["If-None-Match"] = cacheRow.etag;
  }

  let gistResponse: Response;
  try {
    gistResponse = await fetch(gistUrl, { headers });
  } catch {
    return staleOr503(cacheRow);
  }

  if (gistResponse.status === 304) {
    // 변경 없음: 확인 시각만 갱신하고 캐시 반환.
    const nowIso = new Date().toISOString();
    await supabase
      .from("deck_catalog_cache")
      .update({ last_checked_at: nowIso, updated_at: nowIso })
      .eq("id", 1);
    return jsonResponse(200, {
      decks: cacheRow!.decks,
      stale: false,
      source: "cache",
      updated_at: cacheRow!.last_changed_at,
    });
  }

  if (!gistResponse.ok) {
    return staleOr503(cacheRow);
  }

  let raw: unknown;
  try {
    raw = await gistResponse.json();
  } catch {
    return staleOr503(cacheRow);
  }

  const decks = normalizeDecks(raw);
  if (decks === null) {
    return staleOr503(cacheRow);
  }

  const etag = gistResponse.headers.get("etag");
  const contentHash = await sha256(JSON.stringify(decks));
  const nowIso = new Date().toISOString();
  const changed = cacheRow?.content_hash !== contentHash;

  if (cacheRow) {
    await supabase
      .from("deck_catalog_cache")
      .update({
        decks,
        etag,
        source_url: gistUrl,
        content_hash: contentHash,
        last_checked_at: nowIso,
        last_changed_at: changed ? nowIso : cacheRow.last_changed_at,
        updated_at: nowIso,
      })
      .eq("id", 1);
  } else {
    await supabase
      .from("deck_catalog_cache")
      .insert({
        id: 1,
        decks,
        etag,
        source_url: gistUrl,
        content_hash: contentHash,
        last_checked_at: nowIso,
        last_changed_at: nowIso,
        updated_at: nowIso,
      });
  }

  return jsonResponse(200, {
    decks,
    stale: false,
    source: "gist",
    updated_at: nowIso,
  });
});
