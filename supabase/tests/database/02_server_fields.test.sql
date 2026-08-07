-- R4: 서버 관리 필드 위조 공격 테스트.
-- `user_id`, `change_version`, `created_at`, tombstone 시각은
-- 클라이언트가 위조할 수 없어야 한다.
begin;
create extension if not exists pgtap with schema extensions;
set local search_path = extensions, public;

select plan(9);

insert into auth.users (id, email) values
    ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'user-a@test.local'),
    ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', 'user-b@test.local');

set local role authenticated;
set local request.jwt.claims to
    '{"sub":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa","role":"authenticated"}';

select lives_ok(
    $$ insert into public.games (id, user_id, played_at, result, turn_order)
       values ('11111111-1111-4111-8111-111111111111',
               'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
               '2026-08-07T10:00:00', 'win', 'first') $$,
    'user_id를 위조한 INSERT는 거부 대신 소유자 강제로 처리된다'
);

select results_eq(
    $$ select user_id from public.games
       where id = '11111111-1111-4111-8111-111111111111' $$,
    $$ values ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'::uuid) $$,
    '위조된 user_id는 요청자 본인으로 강제된다'
);

select lives_ok(
    $$ insert into public.games
           (id, user_id, played_at, result, turn_order, change_version)
       values ('22222222-2222-4222-8222-222222222222',
               'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
               '2026-08-07T11:00:00', 'lose', 'second', 999999) $$,
    'change_version을 위조한 INSERT도 서버 값으로 처리된다'
);

select ok(
    (select change_version <> 999999 and change_version > 0
     from public.games
     where id = '22222222-2222-4222-8222-222222222222'),
    '클라이언트가 보낸 change_version은 무시되고 서버 sequence가 부여된다'
);

select cmp_ok(
    (select change_version from public.games
     where id = '22222222-2222-4222-8222-222222222222'),
    '>',
    (select change_version from public.games
     where id = '11111111-1111-4111-8111-111111111111'),
    '나중 변경이 더 큰 change_version을 받는다'
);

-- 수정 시 change_version이 단조 증가한다.
update public.games set turns = 7
where id = '11111111-1111-4111-8111-111111111111';

select cmp_ok(
    (select change_version from public.games
     where id = '11111111-1111-4111-8111-111111111111'),
    '>',
    (select change_version from public.games
     where id = '22222222-2222-4222-8222-222222222222'),
    'UPDATE도 새로운 change_version을 받는다'
);

-- 소유자 이전 시도: UPDATE로 user_id를 바꿀 수 없다.
update public.games set user_id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
where id = '11111111-1111-4111-8111-111111111111';

select results_eq(
    $$ select user_id from public.games
       where id = '11111111-1111-4111-8111-111111111111' $$,
    $$ values ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'::uuid) $$,
    'UPDATE로 user_id를 다른 계정으로 바꿀 수 없다'
);

-- created_at 위조 시도.
update public.games set created_at = '1970-01-01T00:00:00+00'
where id = '11111111-1111-4111-8111-111111111111';

select isnt(
    (select created_at from public.games
     where id = '11111111-1111-4111-8111-111111111111'),
    '1970-01-01T00:00:00+00'::timestamptz,
    'created_at은 클라이언트가 덮어쓸 수 없다'
);

-- tombstone 시각 위조 시도: 서버가 현재 시각을 부여한다.
update public.games set deleted_at = '1970-01-01T00:00:00+00'
where id = '11111111-1111-4111-8111-111111111111';

select cmp_ok(
    (select deleted_at from public.games
     where id = '11111111-1111-4111-8111-111111111111'),
    '>',
    '2020-01-01T00:00:00+00'::timestamptz,
    '새 tombstone 시각은 서버가 부여한다'
);

select * from finish();
rollback;
