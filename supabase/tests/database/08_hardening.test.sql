-- H2 하드닝: 서버 권한·경계 forward-fix 검증(0011).
--  - B2 : RPC 쓰기 함수·trigger 함수의 EXECUTE를 anon/authenticated에서 차단.
--  - M3 : 등록 projection이 게스트 철회 마커/출처를 조용히 되살리지 않는다.
--  - H-1: RLS 미활성 5개 테이블에 RLS가 활성화되어 있고 클라이언트는 접근 불가.
--  - H-2: profiles의 서버 필드(id/created_at/updated_at) 위조가 차단된다.
begin;
create extension if not exists pgtap with schema extensions;
set local search_path = extensions, public;

select plan(24);

-- ============================================================================
-- B2: 함수 EXECUTE 권한 회수 통일(anon/authenticated 명시 회수)
-- ============================================================================

select is(false, 
    has_function_privilege('anon', 'public.next_game_change_version(uuid)', 'EXECUTE'),
    'anon은 next_game_change_version을 실행할 수 없다'
);
select is(false, 
    has_function_privilege('authenticated',
                           'public.next_game_change_version(uuid)', 'EXECUTE'),
    'authenticated는 next_game_change_version을 실행할 수 없다'
);
select is(false, 
    has_function_privilege('anon', 'public.set_updated_at()', 'EXECUTE'),
    'anon은 set_updated_at을 실행할 수 없다'
);
select is(false, 
    has_function_privilege('authenticated', 'public.set_updated_at()', 'EXECUTE'),
    'authenticated는 set_updated_at을 실행할 수 없다'
);
select is(false, 
    has_function_privilege('anon', 'public.enforce_game_server_fields()', 'EXECUTE'),
    'anon은 enforce_game_server_fields를 실행할 수 없다'
);
select is(false, 
    has_function_privilege('authenticated',
                           'public.enforce_game_server_fields()', 'EXECUTE'),
    'authenticated는 enforce_game_server_fields를 실행할 수 없다'
);
select is(false, 
    has_function_privilege('anon', 'public.enforce_device_server_fields()', 'EXECUTE'),
    'anon은 enforce_device_server_fields를 실행할 수 없다'
);
select is(false, 
    has_function_privilege('authenticated',
                           'public.enforce_device_server_fields()', 'EXECUTE'),
    'authenticated는 enforce_device_server_fields를 실행할 수 없다'
);

-- RPC 노출 쓰기 함수가 실제로 42501로 거부되는지(런타임).
set local role anon;
select throws_ok(
    $$ select public.next_game_change_version(
           'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa') $$,
    '42501', NULL,
    'anon의 next_game_change_version 직접 호출은 42501이다'
);
reset role;

set local role authenticated;
set local request.jwt.claims to
    '{"sub":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","role":"authenticated"}';
select throws_ok(
    $$ select public.next_game_change_version(
           'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa') $$,
    '42501', NULL,
    'authenticated의 next_game_change_version 직접 호출도 42501이다'
);
reset role;

-- ============================================================================
-- M3: 게스트 철회 마커가 등록 upsert로 되살아나지 않는다
-- ============================================================================

set local role service_role;
select is(
    (public.ingest_guest_batch(
        '99999999-9999-4999-8999-999999999999',
        '77777777-7777-4777-8777-777777777777',
        '0.1.0', 1,
        '[{"sync_id":"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
           "played_at_local":"2026-08-07T10:00:00",
           "result":"win","turn_order":"first","turns":5}]'::jsonb
    )) ->> 'accepted',
    '1',
    '게스트 초기 observation이 수락된다'
);

select is(
    (public.ingest_guest_batch(
        '88888888-8888-4888-8888-888888888888',
        '77777777-7777-4777-8777-777777777777',
        '0.1.0', 1,
        '[{"op":"withdraw",
           "sync_id":"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"}]'::jsonb
    )) ->> 'accepted',
    '1',
    '게스트 observation이 철회된다'
);
reset role;

select ok(
    (select withdrawn_at is not null and withdrawal_source = 'guest'
     from analytics.duel_observations
     where source_game_id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'),
    '게스트 철회가 withdrawn_at으로 기록된다'
);

-- 같은 sync_id를 등록 계정이 생성(games)하면 projection upsert가 발화한다.
-- 이때 철회 마커와 게스트 출처가 보존돼야 한다.
insert into auth.users (id, email)
values ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'adopt-a@test.local');

set local role authenticated;
set local request.jwt.claims to
    '{"sub":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","role":"authenticated"}';
select lives_ok(
    $$ insert into public.profiles (id)
       values ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa') $$,
    '등록 사용자가 프로필을 만든다'
);
select is(
    (public.apply_game_changes(
        1, 1,
        '[{"op":"create","id":"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
           "payload":{"played_at":"2026-08-07T10:00:00","result":"win",
                      "turn_order":"first","turns":5}}]'::jsonb
    ) -> 'results' -> 0 ->> 'status'),
    'applied',
    '게스트와 같은 sync_id로 등록 게임이 생성된다'
);
reset role;

select ok(
    (select withdrawn_at is not null and source_kind = 'guest'
     from analytics.duel_observations
     where source_game_id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'),
    '등록 upsert가 철회 마커와 게스트 출처를 보존한다'
);

-- ============================================================================
-- H-1: RLS 활성화 테이블
-- ============================================================================

select results_eq(
    $$ select count(*)::int from pg_class c
       join pg_namespace n on n.oid = c.relnamespace
       where (
             (n.nspname = 'analytics'
              and c.relname in ('contributor_salt', 'duel_observations',
                                'ingestion_batches', 'rejected_observations'))
          or (n.nspname = 'public' and c.relname = 'game_change_cursors')
       )
         and c.relrowsecurity $$,
    $$ values (5) $$,
    '5개 테이블 모두 RLS가 활성화되어 있다'
);

set local role anon;
select throws_ok(
    $$ select * from analytics.duel_observations $$,
    '42501', NULL,
    'anon은 analytics.duel_observations에 접근할 수 없다'
);
reset role;

set local role authenticated;
set local request.jwt.claims to
    '{"sub":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","role":"authenticated"}';
select throws_ok(
    $$ select * from public.game_change_cursors $$,
    '42501', NULL,
    'authenticated는 change-version clock을 직접 조회할 수 없다'
);
reset role;

-- ============================================================================
-- H-2: profiles 서버 필드 강제
-- ============================================================================

insert into auth.users (id, email)
values ('cccccccc-cccc-4ccc-8ccc-cccccccccccc', 'forge-c@test.local');

set local role authenticated;
set local request.jwt.claims to
    '{"sub":"cccccccc-cccc-4ccc-8ccc-cccccccccccc","role":"authenticated"}';
select lives_ok(
    $$ insert into public.profiles (id, created_at, updated_at)
       values ('cccccccc-cccc-4ccc-8ccc-cccccccccccc',
               '1990-01-01 00:00:00+00', '1990-01-01 00:00:00+00') $$,
    '프로필 insert가 허용된다(서버 필드 위조 시도 포함)'
);
reset role;

select ok(
    (select created_at > '2020-01-01' and updated_at > '2020-01-01'
     from public.profiles where id = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'),
    'insert된 created_at/updated_at은 서버 값으로 강제된다'
);

set local role authenticated;
set local request.jwt.claims to
    '{"sub":"cccccccc-cccc-4ccc-8ccc-cccccccccccc","role":"authenticated"}';
select lives_ok(
    $$ update public.profiles
       set created_at = '1990-01-01 00:00:00+00'
       where id = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc' $$,
    '프로필 update가 허용된다(created_at 위조 시도 포함)'
);
reset role;

select ok(
    (select created_at > '2020-01-01'
     from public.profiles where id = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'),
    'update 시 created_at은 불변으로 유지된다'
);

select is(false, 
    has_function_privilege('anon',
                           'public.enforce_profile_server_fields()', 'EXECUTE'),
    'anon은 enforce_profile_server_fields를 실행할 수 없다'
);

select * from finish();
rollback;
