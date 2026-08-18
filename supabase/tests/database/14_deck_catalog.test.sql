-- 3-C: deck_catalog_cache RLS 격리 + service_role 권한 (spec §3.6).
begin;
create extension if not exists pgtap with schema extensions;
set local search_path = extensions, public;

select plan(6);

-- anon은 deck_catalog_cache를 읽을 수 없다.
set local role anon;
select throws_ok(
    $$ select count(*) from public.deck_catalog_cache $$,
    '42501', NULL,
    'anon은 deck_catalog_cache를 읽을 수 없다'
);
reset role;

-- authenticated도 읽을 수 없다.
set local role authenticated;
set local request.jwt.claims to
    '{"sub":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","role":"authenticated"}';
select throws_ok(
    $$ select count(*) from public.deck_catalog_cache $$,
    '42501', NULL,
    'authenticated는 deck_catalog_cache를 읽을 수 없다'
);
select throws_ok(
    $$ insert into public.deck_catalog_cache (decks, source_url, content_hash)
       values ('["기타"]'::jsonb, 'https://example.com', 'h') $$,
    '42501', NULL,
    'authenticated는 deck_catalog_cache를 쓸 수 없다'
);
reset role;

-- service_role은 읽고 쓸 수 있다.
set local role service_role;
set local request.jwt.claims to '{"role":"service_role"}';
select lives_ok(
    $$ insert into public.deck_catalog_cache (id, decks, source_url, content_hash)
       values (1, '["기타"]'::jsonb, 'https://example.com', 'h') $$,
    'service_role은 캐시를 쓸 수 있다'
);
select is(
    (select decks ->> 0 from public.deck_catalog_cache where id = 1),
    '기타',
    'service_role이 쓴 캐시를 읽을 수 있다'
);
select lives_ok(
    $$ update public.deck_catalog_cache
       set decks = '["기타","티아라멘츠"]'::jsonb where id = 1 $$,
    'service_role은 캐시를 갱신할 수 있다'
);
reset role;

select * from finish();
rollback;
