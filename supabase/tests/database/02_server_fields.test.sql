-- 단계 8: RPC allowlist와 서버 관리 필드 보호 테스트.
begin;
create extension if not exists pgtap with schema extensions;
set local search_path = extensions, public;

select plan(11);

insert into auth.users (id, email) values
    ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'user-a@test.local'),
    ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', 'user-b@test.local');

set local role authenticated;
set local request.jwt.claims to
    '{"sub":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","role":"authenticated"}';

select throws_ok(
    $$ insert into public.games (id, user_id, played_at, result, turn_order)
       values ('11111111-1111-4111-8111-111111111111',
               'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
               '2026-08-07T10:00:00', 'win', 'first') $$,
    '42501',
    'permission denied for table games',
    '서버 필드 위조가 가능한 직접 INSERT는 차단된다'
);

select is(
    public.apply_game_changes(1, 2,
        '[{"op":"create","id":"11111111-1111-4111-8111-111111111111",
           "payload":{"played_at":"2026-08-07T10:00:00","result":"win",
                      "turn_order":"first","standing_kind":"event_points","play_context_id":"dc_cup_2026_08"}}]'::jsonb
    ) -> 'results' -> 0 ->> 'status',
    'applied',
    'RPC create가 성공한다'
);

select results_eq(
    $$ select user_id from public.games
       where id = '11111111-1111-4111-8111-111111111111' $$,
    $$ values ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'::uuid) $$,
    'user_id는 요청자 본인으로 설정된다'
);

select ok(
    (select change_version > 0 from public.games
     where id = '11111111-1111-4111-8111-111111111111'),
    'change_version은 서버가 부여한다'
);

select throws_ok(
    $$ select public.apply_game_changes(1, 2,
           '[{"op":"update","id":"11111111-1111-4111-8111-111111111111",
              "expected_change_version":1,
              "payload":{"user_id":"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"}}]'::jsonb
       ) $$,
    '22023',
    'disallowed game payload field: user_id',
    'RPC는 user_id 위조 필드를 거부한다'
);

select throws_ok(
    $$ select public.apply_game_changes(1, 2,
           '[{"op":"update","id":"11111111-1111-4111-8111-111111111111",
              "expected_change_version":1,
              "payload":{"created_at":"1970-01-01T00:00:00+00"}}]'::jsonb
       ) $$,
    '22023',
    'disallowed game payload field: created_at',
    'RPC는 created_at 위조 필드를 거부한다'
);

select is(
    public.apply_game_changes(1, 2,
        jsonb_build_array(jsonb_build_object(
            'op', 'update',
            'id', '11111111-1111-4111-8111-111111111111',
            'expected_change_version',
                (select change_version from public.games
                 where id = '11111111-1111-4111-8111-111111111111'),
            'payload', jsonb_build_object('turns', 7)
        ))
    ) -> 'results' -> 0 ->> 'status',
    'applied',
    'expected version이 일치하는 UPDATE가 성공한다'
);

select results_eq(
    $$ select turns from public.games
       where id = '11111111-1111-4111-8111-111111111111' $$,
    $$ values (7) $$,
    'UPDATE payload가 반영된다'
);

select is(
    public.apply_game_changes(1, 2,
        jsonb_build_array(jsonb_build_object(
            'op', 'delete',
            'id', '11111111-1111-4111-8111-111111111111',
            'expected_change_version',
                (select change_version from public.games
                 where id = '11111111-1111-4111-8111-111111111111')
        ))
    ) -> 'results' -> 0 ->> 'status',
    'applied',
    'expected version이 일치하는 delete가 성공한다'
);

select cmp_ok(
    (select deleted_at from public.games
     where id = '11111111-1111-4111-8111-111111111111'),
    '>',
    '2020-01-01T00:00:00+00'::timestamptz,
    'tombstone 시각은 서버가 부여한다'
);

select throws_ok(
    $$ select public.apply_game_changes(
           1, 3,
           '[{"op":"create","id":"22222222-2222-4222-8222-222222222222",
              "payload":{"played_at":"2026-08-07T11:00:00",
                         "result":"lose","turn_order":"second","standing_kind":"event_points","play_context_id":"dc_cup_2026_08"}}]'::jsonb
       ) $$,
    '22023',
    'unsupported payload_version',
    '미래 payload version 쓰기는 차단된다'
);

select * from finish();
rollback;
