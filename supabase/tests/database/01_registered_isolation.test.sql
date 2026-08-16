-- 단계 8: 등록 사용자 격리와 RPC-only mutation 공격 테스트.
begin;
create extension if not exists pgtap with schema extensions;
set local search_path = extensions, public;

select plan(15);

insert into auth.users (id, email) values
    ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'user-a@test.local'),
    ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', 'user-b@test.local');

set local role authenticated;
set local request.jwt.claims to
    '{"sub":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","role":"authenticated"}';

select lives_ok(
    $$ insert into public.profiles (id, display_name)
       values ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'A') $$,
    'A는 자신의 profile을 만들 수 있다'
);

select is(
    public.apply_game_changes(1, 2,
        '[{"op":"create","id":"11111111-1111-4111-8111-111111111111",
           "payload":{"played_at":"2026-08-07T10:00:00","result":"win",
                      "turn_order":"first","standing_kind":"event_points","play_context_id":"dc_cup_2026_08","note":"A의 비밀 메모"}}]'::jsonb
    ) -> 'results' -> 0 ->> 'status',
    'applied',
    'A는 RPC로 자신의 게임을 만들 수 있다'
);

select results_eq(
    $$ select count(*)::int from public.games $$,
    $$ values (1) $$,
    'A는 자신의 게임을 조회한다'
);

set local request.jwt.claims to
    '{"sub":"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb","role":"authenticated"}';

select results_eq(
    $$ select count(*)::int from public.games $$,
    $$ values (0) $$,
    'B에게는 A의 게임이 보이지 않는다'
);

select results_eq(
    $$ select count(*)::int from public.games
       where id = '11111111-1111-4111-8111-111111111111' $$,
    $$ values (0) $$,
    'B는 game UUID를 알아도 A의 행을 읽을 수 없다'
);

select is(
    public.apply_game_changes(1, 2,
        '[{"op":"update","id":"11111111-1111-4111-8111-111111111111",
           "expected_change_version":1,"payload":{"note":"탈취됨"}}]'::jsonb
    ) -> 'results' -> 0 ->> 'status',
    'conflict',
    'B의 RPC mutation은 적용되지 않는다'
);

select ok(
    (public.apply_game_changes(1, 2,
        '[{"op":"update","id":"11111111-1111-4111-8111-111111111111",
           "expected_change_version":1,"payload":{"note":"탈취됨"}}]'::jsonb
     ) -> 'results' -> 0 -> 'remote') = 'null'::jsonb,
    'B에게 A의 원격 payload를 노출하지 않는다'
);

select throws_ok(
    $$ update public.games set note = '직접 탈취'
       where id = '11111111-1111-4111-8111-111111111111' $$,
    '42501',
    'permission denied for table games',
    'authenticated의 직접 games UPDATE는 차단된다'
);

select results_eq(
    $$ select count(*)::int from public.profiles $$,
    $$ values (0) $$,
    'B에게는 A의 profile이 보이지 않는다'
);

set local request.jwt.claims to
    '{"sub":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","role":"authenticated"}';

select results_eq(
    $$ select note from public.games
       where id = '11111111-1111-4111-8111-111111111111' $$,
    $$ values ('A의 비밀 메모') $$,
    'B의 mutation 시도 후에도 A의 데이터는 변경되지 않는다'
);

select throws_ok(
    $$ insert into public.games (id, user_id, played_at, result, turn_order)
       values (gen_random_uuid(),
               'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
               '2026-08-07T10:00:00', 'win', 'first') $$,
    '42501',
    'permission denied for table games',
    'authenticated의 직접 games INSERT는 차단된다'
);

select throws_ok(
    $$ delete from public.games
       where id = '11111111-1111-4111-8111-111111111111' $$,
    '42501',
    'permission denied for table games',
    '클라이언트는 물리 DELETE를 사용할 수 없다'
);

set local role anon;

select throws_ok(
    $$ select count(*) from public.games $$,
    '42501',
    'permission denied for table games',
    'anon은 games를 읽을 수 없다'
);

select throws_ok(
    $$ select public.apply_game_changes(1, 2,
           '[{"op":"create","id":"22222222-2222-4222-8222-222222222222",
              "payload":{"played_at":"2026-08-07T10:00:00",
                         "result":"win","turn_order":"first","standing_kind":"event_points","play_context_id":"dc_cup_2026_08"}}]'::jsonb
       ) $$,
    '42501',
    'permission denied for function apply_game_changes',
    'anon은 game mutation RPC를 실행할 수 없다'
);

select throws_ok(
    $$ select count(*) from public.profiles $$,
    '42501',
    'permission denied for table profiles',
    'anon은 profiles를 읽을 수 없다'
);

select * from finish();
rollback;
