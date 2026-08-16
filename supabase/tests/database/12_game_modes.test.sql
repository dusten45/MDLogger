-- 1-G: game_modes 기준정보 RLS + 관리자 RPC(service_role) 권한 (spec §4.8, §6.7).
begin;
create extension if not exists pgtap with schema extensions;
set local search_path = extensions, public;

select plan(7);

-- anon/authenticated는 SELECT만 허용(공개 기준정보).
set local role anon;
select lives_ok(
    $$ select count(*) from public.game_modes $$,
    'anon은 game_modes를 읽을 수 있다'
);
select throws_ok(
    $$ insert into public.game_modes (id, standing_kind, display_name)
       values ('x', 'rank', 'X') $$,
    '42501', NULL,
    'anon은 game_modes를 쓸 수 없다'
);
reset role;

-- authenticated는 관리자 RPC를 실행할 수 없다.
set local role authenticated;
set local request.jwt.claims to
    '{"sub":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","role":"authenticated"}';
select throws_ok(
    $$ select public.manage_game_modes(
           'upsert', 'rank-2026-09', 'rank', '랭크', 'rank_2026_09', 9, true, '26.09'
       ) $$,
    '42501', NULL,
    'authenticated는 관리자 RPC를 실행할 수 없다'
);
reset role;

-- service_role(service-role key)만 관리자 RPC를 실행할 수 있다.
set local role service_role;
set local request.jwt.claims to '{"role":"service_role"}';
select is(
    (public.manage_game_modes(
        'upsert', 'rank-2026-09', 'rank', '랭크', 'rank_2026_09', 9, true, '26.09'
    ) ->> 'id'),
    'rank-2026-09',
    'service_role은 모드를 생성한다'
);
select is(
    (select count(*)::int from public.game_modes where id = 'rank-2026-09'),
    1,
    '생성된 모드가 저장된다'
);
select is(
    (public.manage_game_modes('delete', 'rank-2026-09') ->> 'id'),
    'rank-2026-09',
    'service_role은 모드를 삭제한다'
);
select is(
    (select count(*)::int from public.game_modes where id = 'rank-2026-09'),
    0,
    '삭제된 모드는 사라진다'
);
reset role;

select * from finish();
rollback;
