-- 0027_deck_catalog.sql
-- 3단계: deck-catalog Edge Function의 서버 전용 덱 캐시 테이블 (spec §3.6, 로드맵 17.6).
--
-- - 단일 행(id=1) 캐시: 마지막 정상 덱 JSON, Gist ETag, 마지막 확인/변경 시각,
--   원본 URL, content hash를 보존한다.
-- - RLS로 브라우저(anon/authenticated) 직접 접근을 막는다. Edge Function은
--   service_role로만 접근한다(service_role은 RLS를 우회하고 명시 grant로만 쓰기).

create table public.deck_catalog_cache (
    id integer primary key default 1 check (id = 1),
    decks jsonb not null,
    etag text,
    source_url text not null,
    content_hash text not null,
    last_checked_at timestamptz not null default now(),
    last_changed_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

comment on table public.deck_catalog_cache is
    'deck-catalog Edge Function의 서버 전용 덱 캐시(단일 행). 브라우저 직접 접근 금지.';

alter table public.deck_catalog_cache enable row level security;

-- 브라우저(anon/authenticated)는 어떤 권한도 갖지 않는다. RLS 정책도 없으므로
-- 접근이 차단된다. Edge Function은 service_role로만 접근한다.
revoke all on table public.deck_catalog_cache from anon, authenticated;
grant select, insert, update on table public.deck_catalog_cache to service_role;
