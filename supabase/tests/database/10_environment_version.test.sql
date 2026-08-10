-- H4 하드닝: 환경 버전 기준정보·지정·거부 검증(0013).
--  - anon/authenticated는 environment_versions를 읽기 전용으로 조회할 수 있다.
--  - guest ingest는 미등록 environment_version_id를 거부한다.
--  - 등록 계정 관측치에 environment_version_id와 client_version이 채워진다.
--  - games.environment_version_id FK가 미등록 환경의 저장을 차단한다.
begin;
create extension if not exists pgtap with schema extensions;
set local search_path = extensions, public;

select plan(10);

-- 기준정보 RLS + 읽기 전용.
select results_eq(
    $$ select count(*)::int from pg_class c
       join pg_namespace n on n.oid = c.relnamespace
       where n.nspname = 'public' and c.relname = 'environment_versions'
         and c.relrowsecurity $$,
    $$ values (1) $$,
    'environment_versions에 RLS가 활성화되어 있다'
);
select policies_are(
    'public', 'environment_versions', ARRAY['environment_versions_select_public'],
    'environment_versions에는 SELECT 정책만 존재한다'
);

set local role anon;
select results_eq(
    $$ select id from public.environment_versions where id = 'md-2026-08' $$,
    $$ values ('md-2026-08'::text) $$,
    'anon은 로컬 개발 시드 환경을 읽을 수 있다'
);
reset role;

set local role authenticated;
set local request.jwt.claims to
    '{"sub":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","role":"authenticated"}';
select results_eq(
    $$ select id from public.environment_versions where id = 'md-2026-08' $$,
    $$ values ('md-2026-08'::text) $$,
    'authenticated도 환경 기준정보를 읽을 수 있다'
);
reset role;

-- guest ingest: 미등록 환경 → 거부, 등록 환경 → 수락.
set local role service_role;
select is(
    (public.ingest_guest_batch(
        '99999999-9999-4999-8999-999999999999',
        '77777777-7777-4777-8777-777777777777',
        '0.1.6', 1,
        '[{"sync_id":"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
           "played_at_local":"2026-08-07T10:00:00",
           "result":"win","turn_order":"first",
           "environment_version_id":"unknown-env"}]'::jsonb
    )) ->> 'rejected',
    '1',
    '미등록 환경으로 guest ingest가 거부된다'
);
reset role;

select results_eq(
    $$ select reason from analytics.rejected_observations
       where batch_id = '99999999-9999-4999-8999-999999999999' $$,
    $$ values ('unregistered_environment_version') $$,
    '거부 사유가 기록된다'
);

set local role service_role;
select is(
    (public.ingest_guest_batch(
        '88888888-8888-4888-8888-888888888888',
        '77777777-7777-4777-8777-777777777777',
        '0.1.6', 1,
        '[{"sync_id":"cccccccc-cccc-4ccc-8ccc-cccccccccccc",
           "played_at_local":"2026-08-07T10:00:00",
           "result":"win","turn_order":"first",
           "environment_version_id":"md-2026-08"}]'::jsonb
    )) ->> 'accepted',
    '1',
    '등록된 환경으로 guest ingest가 수락된다'
);
reset role;

-- 등록 계정 observe: apply_game_changes create에 환경/버전을 담아 전송한다.
insert into auth.users (id, email)
values ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'env-a@test.local');

set local role authenticated;
set local request.jwt.claims to
    '{"sub":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","role":"authenticated"}';
select is(
    (public.apply_game_changes(
        1, 1,
        '[{"op":"create","id":"dddddddd-dddd-4ddd-8ddd-dddddddddddd",
           "client_version":"0.1.6",
           "payload":{"played_at":"2026-08-07T10:00:00","result":"win",
                      "turn_order":"first",
                      "environment_version_id":"md-2026-08"}}]'::jsonb
    ) -> 'results' -> 0 ->> 'status'),
    'applied',
    '등록 계정 게임이 환경/버전과 함께 생성된다'
);
reset role;

select results_eq(
    $$ select environment_version_id, client_version, source_kind
       from analytics.duel_observations
       where source_game_id = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd' $$,
    $$ values ('md-2026-08', '0.1.6', 'registered') $$,
    '등록 계정 관측치에 환경 버전과 클라이언트 버전이 채워진다'
);

-- games.environment_version_id FK가 미등록 환경의 저장을 차단한다.
set local role authenticated;
set local request.jwt.claims to
    '{"sub":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","role":"authenticated"}';
select throws_ok(
    $$ select public.apply_game_changes(
           1, 1,
           '[{"op":"create","id":"eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
              "payload":{"played_at":"2026-08-07T10:00:00","result":"win",
                         "turn_order":"first",
                         "environment_version_id":"not-registered"}}]'::jsonb
       ) $$,
    NULL, NULL,
    '미등록 환경으로 등록 게임을 저장할 수 없다(FK 차단)'
);
reset role;

select * from finish();
rollback;
